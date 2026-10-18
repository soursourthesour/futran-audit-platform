"""AI inventory: tools, use cases, risk tiering (spec §11) and named-user confirmation links (schematic D13)."""
import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import AppError, Conflict, Invalid, NotFound
from app.engagements.models import Engagement
from app.inventory.models import AITool, NamedUser, NamedUserLink, UsageRecord, UseCase
from app.tenancy.models import Department, Organization, User
from app.tenancy.service import find_user_by_email

ACCOUNT_TYPES = ("enterprise", "team", "personal_paid", "personal_free", "unknown")
RISKY_ACCOUNTS = {"personal_free", "personal_paid", "unknown"}
SENSITIVE_DATA = {"pii", "phi", "client", "confidential"}
DATA_CATEGORIES = ("pii", "phi", "client", "confidential", "none")
IMPACTS = ("none", "informs", "consequential")
AEDT = ("in_scope", "out_of_scope", "undetermined")
LINK_DAYS = 14
TIER_NAMES = {1: "Tier 1 · Baseline", 2: "Tier 2 · Elevated", 3: "Tier 3 · High-risk"}
ATTESTATION_TOOLS = {"chatgpt": ("OpenAI", "ChatGPT"), "copilot": ("Microsoft", "Copilot"), "claude": ("Anthropic", "Claude"), "gemini": ("Google", "Gemini")}
ATTESTATION_ACCOUNTS = {"company": "enterprise", "personal_free": "personal_free", "personal_paid": "personal_paid", "unknown": "unknown"}


class Gone(AppError):
    status_code = 410


def propose_tier(decision_impact: str | None, data_categories: list[str], tools: list[AITool]) -> int:
    """Spec §11, first match wins. (The plan's extra "training on inputs unknown" rule is not in the spec and is not applied.)"""
    if decision_impact == "consequential":
        return 3
    if SENSITIVE_DATA & set(data_categories or []):
        return 2
    if any(t.account_type in RISKY_ACCOUNTS for t in tools):
        return 2
    return 1


def tier_reason(decision_impact: str | None, data_categories: list[str], tools: list[AITool]) -> str:
    if decision_impact == "consequential":
        return "The output substantially assists or makes decisions about people. Employment use in New York City may be an AEDT under Local Law 144."
    if SENSITIVE_DATA & set(data_categories or []):
        return "Personal, health, client or confidential data goes into the tool."
    if any(t.account_type in RISKY_ACCOUNTS for t in tools):
        return "At least one tool is used on a personal or unknown account."
    return "No personal data, company accounts only, and no effect on decisions about people."


def effective_tier(uc: UseCase) -> int:
    return uc.final_tier or uc.proposed_tier or 1


# ---- tools
def tools_for(db: Session, org_id: str) -> list[AITool]:
    return list(db.scalars(select(AITool).where(AITool.organization_id == org_id, AITool.deleted_at.is_(None)).order_by(AITool.vendor, AITool.product)))


def _find_tool(db: Session, org_id: str, vendor: str, product: str, account_type: str) -> AITool | None:
    return db.scalar(select(AITool).where(
        AITool.organization_id == org_id, AITool.deleted_at.is_(None), func.lower(AITool.vendor) == vendor.lower(),
        func.lower(AITool.product) == product.lower(), AITool.account_type == account_type,
    ))


def assert_inventory_open(db: Session, e: Engagement | None) -> None:
    """Sign-off 4 locks the inventory snapshot. Changing it means reopening sign-off 4, which re-locks a new version."""
    from app.signoffs.service import current

    from app.signoffs.service import CORRECTABLE_UNTIL

    if e is not None and e.stage > CORRECTABLE_UNTIL[4]:
        raise Conflict("The AI inventory is locked: fieldwork is complete and the audit is reported on this inventory.")
    so = current(db, e, 4) if e is not None else None
    if so is not None and so.status == "approved":
        raise Conflict("The AI inventory is locked by sign-off 4 (management representation). To change it, the CAICO corrects sign-off 4.")


def save_tool(db: Session, actor: User, org: Organization, data: dict, tool: AITool | None = None, can_approve: bool = False) -> AITool:
    """Create or edit a tool. Only the CAICO approves tools (spec §5), so `approval_status` is ignored otherwise."""
    from app.tenancy.people import current_engagement

    assert_inventory_open(db, current_engagement(db, org))
    vendor, product = " ".join(str(data.get("vendor") or "").split())[:120], " ".join(str(data.get("product") or "").split())[:120]
    acct = data.get("account_type", tool.account_type if tool else "unknown")
    errs = []
    if not vendor:
        errs.append({"field": "vendor", "message": "Enter the vendor."})
    if not product:
        errs.append({"field": "product", "message": "Enter the product."})
    if acct not in ACCOUNT_TYPES:
        errs.append({"field": "account_type", "message": "Choose the account type."})
    if data.get("training_on_inputs", "unknown") not in ("yes", "no", "unknown"):
        errs.append({"field": "training_on_inputs", "message": "Choose yes, no or unknown."})
    if errs:
        raise Invalid(errors=errs)
    dup = _find_tool(db, org.id, vendor, product, acct)
    if dup is not None and (tool is None or dup.id != tool.id):
        raise Conflict(f"{vendor} {product} on that account type is already in the inventory.")
    if tool is None:
        tool = AITool(organization_id=org.id, source="manual", created_by=actor.id)
        db.add(tool)
    tool.vendor, tool.product, tool.account_type = vendor, product, acct
    tool.plan = str(data.get("plan") or "").strip()[:80] or None
    tool.training_on_inputs = data.get("training_on_inputs", tool.training_on_inputs or "unknown")
    if "sso" in data:
        tool.sso = None if data["sso"] is None else bool(data["sso"])
    if "retention_terms" in data:
        tool.retention_terms = str(data.get("retention_terms") or "").strip()[:4000] or None
    if can_approve and data.get("approval_status") in ("unreviewed", "approved", "not_approved"):
        tool.approval_status = data["approval_status"]
    db.flush()
    audit.record(db, actor_id=actor.id, action="inventory.tool", obj=tool, summary=f"Saved AI tool {vendor} {product} ({acct.replace('_', ' ')})")
    return tool


def sync_tools_from_attestations(db: Session, org_id: str) -> None:
    """Every tool employees declare becomes an inventory tool (matched case-insensitively); declared counts are
    recomputed from current answers, so replaced answers and repeated entries never inflate them."""
    from app.attestation.models import Attestation

    counts: dict[tuple[str, str, str], int] = {}
    for a in db.scalars(select(Attestation).where(Attestation.organization_id == org_id, Attestation.superseded_by_id.is_(None), Attestation.deleted_at.is_(None))):
        for t in {(t["tool"], t["account_type"], (t.get("name") or "")) for t in a.tools_declared or []}:
            vendor, product = ATTESTATION_TOOLS.get(t[0], ("Other", t[2] or "Unnamed AI tool"))
            key = (vendor, product, ATTESTATION_ACCOUNTS.get(t[1], "unknown"))
            counts[key] = counts.get(key, 0) + 1
    for tool in tools_for(db, org_id):
        tool.declared_count = 0
    for (vendor, product, acct), n in counts.items():
        tool = _find_tool(db, org_id, vendor, product, acct)
        if tool is None:
            tool = AITool(organization_id=org_id, vendor=vendor, product=product, account_type=acct, source="attestation")
            db.add(tool)
        tool.declared_count = n
    db.flush()


# ---- use cases
def _clean_use_case(db: Session, org: Organization, data: dict) -> dict:
    errs = []
    name = " ".join(str(data.get("name") or "").split())[:160]
    if not name:
        errs.append({"field": "name", "message": "Name the use case."})
    dept = db.get(Department, data.get("department_id")) if isinstance(data.get("department_id"), str) else None
    if dept is None or dept.organization_id != org.id or dept.deleted_at:
        errs.append({"field": "department_id", "message": "Choose the department."})
    valid_tools = {t.id for t in tools_for(db, org.id)}
    raw_tools = data.get("tool_ids") if isinstance(data.get("tool_ids"), list) else []
    tool_ids = [t for t in dict.fromkeys(x for x in raw_tools if isinstance(x, str)) if t in valid_tools]
    if not tool_ids:
        errs.append({"field": "tool_ids", "message": "Choose at least one AI tool."})
    raw_cats = data.get("data_categories") if isinstance(data.get("data_categories"), list) else []
    cats = [c for c in dict.fromkeys(x for x in raw_cats if isinstance(x, str)) if c in DATA_CATEGORIES]
    if "none" in cats and len(cats) > 1:
        cats = [c for c in cats if c != "none"]
    impact = data.get("decision_impact")
    if not isinstance(impact, str) or impact not in IMPACTS:
        errs.append({"field": "decision_impact", "message": "Say how the output affects people."})
    usage = []
    for u in (data.get("usage") if isinstance(data.get("usage"), list) else [])[:50]:
        if isinstance(u, dict) and str(u.get("role_name") or "").strip():
            hc = str(u.get("headcount") or "").strip()
            usage.append({"role_name": str(u["role_name"]).strip()[:120], "headcount": int(hc) if hc.isascii() and hc.isdigit() else None, "frequency": (str(u.get("frequency") or "").strip()[:20] or None)})
    named = []
    for n in (data.get("named_users") if isinstance(data.get("named_users"), list) else [])[:200]:
        if isinstance(n, dict) and str(n.get("person_name") or "").strip():
            email = str(n.get("email") or "").strip().lower() or None
            if email and ("@" not in email or " " in email):
                errs.append({"field": "named_users", "message": f"{n['person_name']}: enter a valid work email."})
            named.append({"person_name": " ".join(str(n["person_name"]).split())[:120], "email": email, "role_name": (str(n.get("role_name") or "").strip()[:120] or None), "oversight_role": (str(n.get("oversight_role") or "").strip()[:200] or None)})
    if errs:
        raise Invalid(errors=errs)
    return {"name": name, "department_id": dept.id, "purpose": (str(data.get("purpose") or "").strip() or None), "tool_ids": tool_ids, "data_categories": cats, "decision_impact": impact, "usage": usage, "named": named}


def _tools(db: Session, uc: UseCase) -> list[AITool]:
    return list(db.scalars(select(AITool).where(AITool.id.in_(uc.tool_ids or []))))


def save_use_case(db: Session, actor: User, org: Organization, e: Engagement, data: dict, uc: UseCase | None = None) -> UseCase:
    assert_inventory_open(db, e)
    if uc is not None and uc.status not in ("draft", "returned"):
        raise Conflict("This use case has been submitted. Ask your Department Compliance Lead to return it if it needs changes.")
    v = _clean_use_case(db, org, data)
    if uc is None:
        uc = UseCase(organization_id=org.id, engagement_id=e.id, status="draft", owner_user_id=actor.id, created_by=actor.id)
        db.add(uc)
    for k in ("name", "department_id", "purpose", "tool_ids", "data_categories", "decision_impact"):
        setattr(uc, k, v[k])
    uc.updated_by = actor.id
    uc.editor_ids = list(dict.fromkeys([*(uc.editor_ids or []), actor.id]))
    db.flush()
    uc.proposed_tier = propose_tier(uc.decision_impact, uc.data_categories, _tools(db, uc))
    from app.systems.service import sync_depth_for_use_case

    sync_depth_for_use_case(db, actor, uc)
    for r in db.scalars(select(UsageRecord).where(UsageRecord.use_case_id == uc.id, UsageRecord.deleted_at.is_(None))):
        r.deleted_at = utcnow()
    for u in v["usage"]:
        db.add(UsageRecord(organization_id=org.id, use_case_id=uc.id, **u))
    existing = {(n.email or n.person_name).lower(): n for n in db.scalars(select(NamedUser).where(NamedUser.use_case_id == uc.id, NamedUser.deleted_at.is_(None)))}
    keep = set()
    for n in v["named"]:
        key = (n["email"] or n["person_name"]).lower()
        row = existing.get(key)
        if row is None:
            row = NamedUser(organization_id=org.id, use_case_id=uc.id)
            db.add(row)
        row.person_name, row.email, row.role_name, row.oversight_role = n["person_name"], n["email"], n["role_name"], n["oversight_role"]
        account = find_user_by_email(db, n["email"]) if n["email"] else None
        row.user_id = account.id if account is not None and account.organization_id == org.id else None
        keep.add(key)
    for key, row in existing.items():
        if key not in keep:
            row.deleted_at = utcnow()
            _revoke_links(db, row)
    db.flush()
    audit.record(db, actor_id=actor.id, action="inventory.use_case", obj=uc, after={"proposed_tier": uc.proposed_tier, "status": uc.status}, summary=f"Saved use case {uc.name} (proposed tier {uc.proposed_tier})")
    return uc


def _revoke_links(db: Session, n: NamedUser) -> None:
    for link in db.scalars(select(NamedUserLink).where(NamedUserLink.named_user_id == n.id, NamedUserLink.revoked_at.is_(None))):
        link.revoked_at = utcnow()


def named_users(db: Session, uc: UseCase) -> list[NamedUser]:
    return list(db.scalars(select(NamedUser).where(NamedUser.use_case_id == uc.id, NamedUser.deleted_at.is_(None)).order_by(NamedUser.created_at)))


def _check_named(db: Session, uc: UseCase, tier: int) -> None:
    if tier < 2:
        return
    people = named_users(db, uc)
    if not people or any(not n.email for n in people):
        raise Invalid("Name the people who use this AI.", [{"field": "named_users", "message": "Tier 2 and 3 use cases need the people who use them, with their work email."}])
    if tier == 3:
        missing = [n for n in people if not n.oversight_role]
        if missing:
            raise Invalid("Tier 3 use cases need a human oversight role for each person.", [{"field": "named_users", "message": f"{n.person_name} needs a human oversight role (for example, reviews the ranked list)."} for n in missing])


def send_links(db: Session, settings: Settings, actor: User | None, uc: UseCase) -> int:
    """Send a personal confirmation link to each named user without an account; earlier links stop working."""
    org = db.get(Organization, uc.organization_id)
    sent = 0
    for n in named_users(db, uc):
        if n.user_id or not n.email:
            continue
        for old in db.scalars(select(NamedUserLink).where(NamedUserLink.named_user_id == n.id, NamedUserLink.revoked_at.is_(None), NamedUserLink.completed_at.is_(None))):
            old.revoked_at = utcnow()
        raw = secrets.token_urlsafe(32)
        db.add(NamedUserLink(organization_id=uc.organization_id, named_user_id=n.id, token_hash=hashlib.sha256(raw.encode()).hexdigest(), sent_at=utcnow(), expires_at=utcnow() + timedelta(days=LINK_DAYS)))
        from app.mail.service import send

        link = f"{settings.base_url}/confirm/{raw}"
        send(db, settings, "named_user_confirm", to=[n.email], organization_id=uc.organization_id, related=n, actor_id=actor.id if actor else None,
             context={"name": n.person_name.split()[0], "client": org.name, "use_case": uc.name, "link": link, "days": LINK_DAYS}, redact={"link": f"{settings.base_url}/confirm/[sent to {n.email}]"})
        sent += 1
    db.flush()
    return sent


def submit_use_case(db: Session, settings: Settings, actor: User, uc: UseCase) -> UseCase:
    assert_inventory_open(db, db.get(Engagement, uc.engagement_id))
    if uc.status not in ("draft", "returned"):
        raise Conflict("This use case has already been submitted.")
    uc.proposed_tier = propose_tier(uc.decision_impact, uc.data_categories, _tools(db, uc))
    _check_named(db, uc, effective_tier(uc))
    uc.status, uc.submitted_at, uc.returned_comment, uc.submitted_by = "submitted", utcnow(), None, actor.id
    sent = send_links(db, settings, actor, uc) if effective_tier(uc) >= 2 else 0
    audit.record(db, actor_id=actor.id, action="inventory.submit", obj=uc, summary=f"Submitted use case {uc.name} (proposed tier {uc.proposed_tier}; {sent} confirmation links sent)")
    return uc


def review_use_case(db: Session, actor: User, uc: UseCase, approve: bool, comment: str | None = None) -> UseCase:
    assert_inventory_open(db, db.get(Engagement, uc.engagement_id))
    if uc.status != "submitted":
        raise Conflict("Only a submitted use case can be approved or returned.")
    if approve:
        from app.policy.sod import assert_not_self_approval

        assert_not_self_approval(actor.id, uc.created_by, uc.submitted_by, *(uc.editor_ids or []))
        uc.status = "dept_approved"
    else:
        if not (comment or "").strip():
            raise Invalid(errors=[{"field": "comment", "message": "Say what needs to change."}])
        uc.status, uc.returned_comment = "returned", comment.strip()
    audit.record(db, actor_id=actor.id, action="inventory.approve" if approve else "inventory.return", obj=uc, summary=f"{'Approved' if approve else 'Returned'} use case {uc.name}")
    return uc


def set_final_tier(db: Session, settings: Settings, actor: User, uc: UseCase, tier: int, rationale: str, aedt_determination: str | None = None) -> UseCase:
    from app.findings.service import assert_open

    assert_open(db, db.get(Engagement, uc.engagement_id))  # sign-off 5 locks the final tiers
    if tier not in (1, 2, 3):
        raise Invalid(errors=[{"field": "tier", "message": "Choose tier 1, 2 or 3."}])
    if not (rationale or "").strip():
        raise Invalid(errors=[{"field": "rationale", "message": "Give the reason for the final tier."}])
    if aedt_determination is not None and aedt_determination not in AEDT:
        raise Invalid(errors=[{"field": "aedt_determination", "message": "Choose in scope, out of scope or undetermined."}])
    if uc.status in ("draft", "returned"):
        raise Conflict("The client has not submitted this use case yet.")
    before = effective_tier(uc)
    prev = {"final_tier": uc.final_tier, "rationale": uc.final_tier_rationale}
    uc.final_tier, uc.final_tier_rationale, uc.final_tier_set_by, uc.final_tier_set_at = tier, rationale.strip(), actor.id, utcnow()
    if aedt_determination is not None:
        uc.aedt_determination = aedt_determination
    resent = 0
    if tier > before and tier >= 2:
        try:
            _check_named(db, uc, tier)
        except Invalid as exc:
            detail = "; ".join(e["message"] for e in exc.errors) or exc.detail
            uc.status, uc.returned_comment = "returned", f"Futran set this use case to tier {tier}. {detail}"
        else:
            resent = send_links(db, settings, actor, uc)
    from app.systems.service import sync_depth_for_use_case

    sync_depth_for_use_case(db, actor, uc)
    audit.record(db, actor_id=actor.id, action="inventory.final_tier", obj=uc, before=prev, after={"final_tier": tier, "rationale": uc.final_tier_rationale, "aedt": uc.aedt_determination}, summary=f"Set the final tier of {uc.name} to {tier}{f'; {resent} links re-sent' if resent else ''}")
    return uc


# ---- public confirmation link
def link_by_token(db: Session, token: str) -> NamedUserLink:
    link = db.scalar(select(NamedUserLink).where(NamedUserLink.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if link is None or link.revoked_at is not None:
        raise NotFound("This link is not valid. A newer link may have been sent to you.")
    n = db.get(NamedUser, link.named_user_id)
    uc = db.get(UseCase, n.use_case_id) if n else None
    if n is None or n.deleted_at is not None or uc is None or uc.deleted_at is not None:
        raise NotFound("This link is not valid. A newer link may have been sent to you.")
    return link


def public_confirm_view(db: Session, link: NamedUserLink) -> dict:
    from app.attestation.service import POLICY_TEXT

    if link.completed_at is None and link.expires_at < utcnow():
        raise Gone("This link has expired. Ask your compliance team for a new one.")
    n = db.get(NamedUser, link.named_user_id)
    uc = db.get(UseCase, n.use_case_id)
    org = db.get(Organization, uc.organization_id)
    tool = _tools(db, uc)
    return {
        "client_name": org.name, "first_name": n.person_name.split()[0], "use_case": uc.name,
        "tool": ", ".join(f"{t.vendor} {t.product}" for t in tool), "oversight_role": n.oversight_role, "policy_text": POLICY_TEXT,
        "completed": link.completed_at is not None,
    }


def confirm(db: Session, token: str, payload: dict, request=None) -> NamedUserLink:
    link = link_by_token(db, token)
    if link.completed_at is not None:
        raise Gone("You have already answered. Thank you.")
    if link.expires_at < utcnow():
        raise Gone("This link has expired. Ask your compliance team for a new one.")
    for k in ("training_complete", "policy_acknowledged", "oversight_role_confirmed"):
        if not isinstance(payload.get(k), bool):
            raise Invalid(errors=[{"field": k, "message": "Answer yes or no."}])
    n = db.get(NamedUser, link.named_user_id)
    link.training_complete, link.policy_acknowledged, link.oversight_role_confirmed = payload["training_complete"], payload["policy_acknowledged"], payload["oversight_role_confirmed"]
    link.unable_reason = (str(payload.get("unable_reason") or "").strip()[:2000]) or None
    link.completed_at = utcnow()
    n.training_complete, n.policy_acknowledged, n.oversight_role_confirmed = link.training_complete, link.policy_acknowledged, link.oversight_role_confirmed
    db.flush()
    from app.inventory.snapshot import add_snapshot_addendum, current_snapshot

    uc = db.get(UseCase, n.use_case_id)
    snap = current_snapshot(db, db.get(Engagement, uc.engagement_id)) if uc else None
    if snap is not None:  # arrived after the lock: recorded as a dated addendum, the snapshot itself is unchanged
        add_snapshot_addendum(db, snap, "named_user_confirmation", {"person_name": n.person_name, "use_case": uc.name, "training_complete": n.training_complete,
                                                                     "policy_acknowledged": n.policy_acknowledged, "oversight_role_confirmed": n.oversight_role_confirmed, "unable_reason": link.unable_reason})
    audit.record(db, actor_id=None, actor_name=n.person_name, action="inventory.named_user_confirm", obj=n, request=request, after={"training_complete": n.training_complete, "policy_acknowledged": n.policy_acknowledged, "oversight_role_confirmed": n.oversight_role_confirmed}, summary=f"{n.person_name} answered the use-case confirmation")
    return link
