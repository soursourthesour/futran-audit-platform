"""Employee attestation campaign: launch, public form, tracker (spec §9.5, §15; schematic D13)."""
import secrets
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.attestation.models import Attestation, AttestationAssignment, AttestationCampaign
from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import AppError, Conflict, Invalid, NotFound
from app.engagements.models import Engagement
from app.initiation.models import PackageDocument
from app.initiation.service import current_package
from app.documents.csvsafe import to_csv
from app.tenancy.models import Department, Organization, User

MIN_AGGREGATE = 3  # spec §15: no department count below 3 is shown (re-identification)
# Question 2 lists tools, then agents (tools that take actions for the user). Values are stored with each answer, so
# existing values never change meaning. has_name: a free-text name box; needs_name: the name is required;
# account: the account is fixed rather than asked. vendor/product: the inventory row the answer feeds.
TOOLS = [
    {"value": "chatgpt", "label": "ChatGPT", "kind": "tool", "vendor": "OpenAI", "product": "ChatGPT"},
    {"value": "copilot", "label": "Microsoft Copilot", "kind": "tool", "vendor": "Microsoft", "product": "Copilot"},
    {"value": "claude", "label": "Claude", "kind": "tool", "vendor": "Anthropic", "product": "Claude"},
    {"value": "gemini", "label": "Gemini", "kind": "tool", "vendor": "Google", "product": "Gemini"},
    {"value": "in_app", "label": "AI inside another app (for example an ATS or CRM)", "kind": "tool", "has_name": True},
    {"value": "other", "label": "Another AI tool", "kind": "tool", "has_name": True, "needs_name": True},
    {"value": "copilot_agents", "label": "Microsoft 365 Copilot agents or Copilot Studio agents", "kind": "agent", "vendor": "Microsoft", "product": "Copilot agents"},
    {"value": "chatgpt_agent", "label": "ChatGPT agent mode or custom GPTs", "kind": "agent", "vendor": "OpenAI", "product": "ChatGPT agent or custom GPTs"},
    {"value": "claude_agentic", "label": "Claude projects, Claude Code or other agentic use", "kind": "agent", "vendor": "Anthropic", "product": "Claude agentic use"},
    {"value": "gemini_agents", "label": "Google Gemini agents or Gems", "kind": "agent", "vendor": "Google", "product": "Gemini agents or Gems"},
    {"value": "agentforce", "label": "Salesforce Agentforce", "kind": "agent", "vendor": "Salesforce", "product": "Agentforce"},
    {"value": "servicenow_agents", "label": "ServiceNow AI agents", "kind": "agent", "vendor": "ServiceNow", "product": "AI agents"},
    {"value": "automations", "label": "Zapier or Make AI automations", "kind": "agent", "vendor": "Zapier or Make", "product": "AI automations"},
    {"value": "github_coding_agent", "label": "GitHub Copilot coding agent", "kind": "agent", "vendor": "GitHub", "product": "Copilot coding agent"},
    {"value": "in_house_agent", "label": "An agent built in-house", "kind": "agent", "has_name": True, "needs_name": True, "account": "company", "vendor": "In-house"},
    {"value": "other_agent", "label": "Another AI agent", "kind": "agent", "has_name": True, "needs_name": True},
]
TOOL_SPECS = {t["value"]: t for t in TOOLS}
TYPED_VENDORS = ("Other", "In-house")  # inventory rows named by an employee: shown only to those who see individual answers


def public_tools() -> list[dict]:
    return [{k: v for k, v in t.items() if k not in ("vendor", "product")} for t in TOOLS]


def inventory_identity(tool: str, name: str | None) -> tuple[str, str, str]:
    """(vendor, product, kind) of the inventory row an answer feeds."""
    spec = TOOL_SPECS.get(tool, {})
    kind = spec.get("kind", "tool")
    if spec.get("product"):
        return spec["vendor"], spec["product"], kind
    fallback = "Unnamed AI agent" if kind == "agent" else "Unnamed AI tool"
    return spec.get("vendor", "Other"), name or fallback, kind


ACCOUNT_TYPES = [
    {"value": "personal_free", "label": "Personal, free"},
    {"value": "personal_paid", "label": "Personal, paid"},
    {"value": "company", "label": "Company account"},
    {"value": "unknown", "label": "Not sure"},
]
PURPOSES = [
    {"value": "writing", "label": "Writing and editing"},
    {"value": "research", "label": "Research and summaries"},
    {"value": "code", "label": "Writing or reviewing code"},
    {"value": "analysis", "label": "Data analysis and spreadsheets"},
    {"value": "media", "label": "Images, audio or video"},
    {"value": "customer", "label": "Messages to customers or candidates"},
    {"value": "decisions", "label": "Decisions about people (hiring, performance, customers)"},
    {"value": "other", "label": "Something else"},
]
DATA_CATEGORIES = [
    {"value": "pii", "label": "Personal information about people (names, contact details, CVs)"},
    {"value": "phi", "label": "Health information"},
    {"value": "client", "label": "Client or customer data"},
    {"value": "confidential", "label": "Confidential company information"},
    {"value": "none", "label": "None of these"},
]
POLICY_TEXT = (
    "Use only AI tools the company has approved for work. Do not enter personal, health, client or confidential "
    "information into a personal AI account. Check AI output before you rely on it, and tell your manager if an AI "
    "tool produces something harmful or wrong."
)
DATA_SHORT = {"pii": "Personal information", "phi": "Health information", "client": "Client data", "confidential": "Confidential information", "none": "None"}
PURPOSE_LABELS = {p["value"]: p["label"] for p in PURPOSES}
TOOL_LABELS = {t["value"]: t["label"] for t in TOOLS}
ACCOUNT_LABELS = {a["value"]: a["label"] for a in ACCOUNT_TYPES}


class Gone(AppError):
    status_code = 410


def current_campaign(db: Session, e: Engagement) -> AttestationCampaign | None:
    return db.scalar(select(AttestationCampaign).where(AttestationCampaign.engagement_id == e.id, AttestationCampaign.deleted_at.is_(None)).order_by(AttestationCampaign.launched_at.desc()).limit(1))


def is_open(c: AttestationCampaign) -> bool:
    return c.status == "open" and c.closes_at > utcnow()


def notice_acknowledged(db: Session, e: Engagement) -> bool:
    pkg = current_package(db, e)
    doc = db.scalar(select(PackageDocument).where(PackageDocument.package_id == pkg.id, PackageDocument.item == 5)) if pkg else None
    return doc is not None and doc.completed_at is not None


def launch(db: Session, actor: User, e: Engagement, department_ids: list[str], closes_at: datetime, policy_version: str) -> AttestationCampaign:
    if e.stage > 3:
        raise Conflict("Discovery has finished, so a new campaign can't start. Ask your Futran Chief Auditor.")
    if not notice_acknowledged(db, e):
        raise Conflict("The Chief AI Compliance Officer must acknowledge the employee data notice before the campaign starts (New York Civil Rights Law §52-c).")
    current = current_campaign(db, e)
    if current is not None and is_open(current):
        raise Conflict("A campaign is already running. Close it before starting another.")
    depts = {d.id for d in db.scalars(select(Department).where(Department.organization_id == e.client_id, Department.deleted_at.is_(None), Department.in_scope.is_(True)))}
    chosen = [d for d in dict.fromkeys(department_ids) if d in depts]
    if not chosen:
        raise Invalid(errors=[{"field": "department_ids", "message": "Choose at least one department in scope."}])
    closes = closes_at.replace(tzinfo=None) if closes_at.tzinfo else closes_at
    if closes <= utcnow():
        raise Invalid(errors=[{"field": "closes_at", "message": "The closing date must be in the future."}])
    c = AttestationCampaign(organization_id=e.client_id, engagement_id=e.id, policy_version=(policy_version or "1.0").strip()[:40], launched_by=actor.id, launched_at=utcnow(), closes_at=closes, department_ids=chosen, link_token=secrets.token_urlsafe(24), status="open", created_by=actor.id)
    db.add(c)
    db.flush()
    audit.record(db, actor_id=actor.id, action="attestation.launch", obj=c, summary=f"Launched the AI use attestation for {len(chosen)} departments, closing {closes:%B %d, %Y}")
    return c


def close(db: Session, actor: User, c: AttestationCampaign) -> AttestationCampaign:
    if c.status != "closed":
        c.status, c.closed_at = "closed", utcnow()
        audit.record(db, actor_id=actor.id, action="attestation.close", obj=c, summary="Closed the AI use attestation campaign")
    return c


def by_token(db: Session, token: str) -> AttestationCampaign:
    c = db.scalar(select(AttestationCampaign).where(AttestationCampaign.link_token == token, AttestationCampaign.deleted_at.is_(None)))
    if c is None:
        raise NotFound("This link is not valid. Ask your compliance team for the current link.")
    return c


def public_view(db: Session, c: AttestationCampaign) -> dict:
    """Only what an employee needs to answer: no names, counts or other answers."""
    org = db.get(Organization, c.organization_id)
    depts = db.scalars(select(Department).where(Department.id.in_(c.department_ids)).order_by(Department.name))
    return {
        "client_name": org.name, "policy_version": c.policy_version, "policy_text": POLICY_TEXT,
        "departments": [{"id": d.id, "name": d.name} for d in depts], "tools": public_tools(), "account_types": ACCOUNT_TYPES,
        "purposes": PURPOSES, "data_categories": DATA_CATEGORIES, "closes_at": c.closes_at.isoformat(), "open": is_open(c),
    }


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _text(v, limit: int) -> str:
    return " ".join(str(v or "").split())[:limit]


MAX_TOOLS = 20


def _clean(payload: dict, c: AttestationCampaign) -> dict:
    errs = []
    name = _text(payload.get("respondent_name"), 120)
    if not name:
        errs.append({"field": "respondent_name", "message": "Enter your name."})
    email = str(payload.get("respondent_email") or "").strip().lower()[:254] or None
    if email and ("@" not in email or " " in email):
        errs.append({"field": "respondent_email", "message": "Enter a valid email address, or leave it blank."})
    if payload.get("department_id") not in c.department_ids:
        errs.append({"field": "department_id", "message": "Choose your department."})
    uses = bool(payload.get("uses_ai"))
    tools = []
    declared = payload.get("tools_declared") or []
    if not isinstance(declared, list):
        declared = [None]
    seen = set()
    for t in declared if uses else []:
        spec = TOOL_SPECS.get(t.get("tool")) if isinstance(t, dict) and isinstance(t.get("tool"), str) else None
        acct = (spec or {}).get("account") or (t.get("account_type") if isinstance(t, dict) else None)
        if spec is None or not isinstance(acct, str) or acct not in ACCOUNT_LABELS:
            errs.append({"field": "tools_declared", "message": "Choose each tool or agent and the account you use it with."})
            break
        item = {"tool": t["tool"], "account_type": acct, "name": _text(t.get("name"), 80) or None}
        if spec.get("needs_name") and not item["name"]:
            errs.append({"field": "tools_declared", "message": f"Give the name for “{spec['label']}”."})
            break
        key = (item["tool"], item["account_type"], (item["name"] or "").lower())
        if key not in seen and len(tools) < MAX_TOOLS:
            seen.add(key)
            tools.append(item)
    if uses and not tools and not any(e["field"] == "tools_declared" for e in errs):
        errs.append({"field": "tools_declared", "message": "Choose the AI tools and agents you use, or say you don't use AI for work."})
    valid_p, valid_d = {p["value"] for p in PURPOSES}, {d["value"] for d in DATA_CATEGORIES}
    purposes = list(dict.fromkeys(p for p in _list(payload.get("purposes")) if isinstance(p, str) and p in valid_p)) if uses else []
    purpose_other = _text(payload.get("purpose_other"), 200) or None if "other" in purposes else None
    if "other" in purposes and not purpose_other:
        errs.append({"field": "purpose_other", "message": "Say what else you use AI for."})
    data = list(dict.fromkeys(d for d in _list(payload.get("data_entered")) if isinstance(d, str) and d in valid_d)) if uses else []
    if not payload.get("policy_acknowledged"):
        errs.append({"field": "policy_acknowledged", "message": "Confirm you have read the AI use policy."})
    if errs:
        raise Invalid(errors=errs)
    return {"respondent_name": name, "respondent_email": email, "department_id": payload["department_id"], "uses_ai": uses, "tools_declared": tools, "purposes": purposes,
            "purpose_other": purpose_other, "data_entered": data, "policy_acknowledged": True}


ANSWER_FIELDS = ("uses_ai", "tools_declared", "purposes", "data_entered")


def current_answers(db: Session, campaign_id: str) -> list[Attestation]:
    return list(db.scalars(select(Attestation).where(Attestation.campaign_id == campaign_id, Attestation.deleted_at.is_(None), Attestation.superseded_by_id.is_(None))))


def _login_for(db: Session, c: AttestationCampaign, email: str | None) -> User | None:
    if not email:
        return None
    return db.scalar(select(User).where(User.organization_id == c.organization_id, func.lower(User.email) == email, User.deleted_at.is_(None)))


def _record(db: Session, c: AttestationCampaign, values: dict, *, user: User | None, source: str) -> Attestation:
    """Store one answer. The respondent's earlier current answer (same email, or same login) is superseded, never
    deleted, so a person counts once however many times and through whichever route they answer."""
    conds = []
    if values["respondent_email"]:
        conds.append(func.lower(Attestation.respondent_email) == values["respondent_email"])
    if user is not None:
        conds.append(Attestation.user_id == user.id)
    prevs = list(db.scalars(select(Attestation).where(Attestation.campaign_id == c.id, or_(*conds), Attestation.superseded_by_id.is_(None), Attestation.deleted_at.is_(None)).order_by(Attestation.submitted_at))) if conds else []
    a = Attestation(organization_id=c.organization_id, campaign_id=c.id, engagement_id=c.engagement_id, **values, user_id=user.id if user else None, source=source, submitted_at=utcnow())
    db.add(a)
    db.flush()
    for p in prevs:
        p.superseded_by_id = a.id
    prev = prevs[-1] if prevs else None
    before = None
    if prev is not None:
        before = {k: getattr(prev, k) for k in ANSWER_FIELDS} | ({"purpose_other": prev.purpose_other} if prev.purpose_other else {})
    # no name or IP in the audit log: the Futran Admin and Engagement Managers can read it (spec §6 rule 8)
    audit.record(db, actor_id=user.id if source == "in_app" and user else None, actor_name=None if source == "in_app" else "Employee (self-declared)", action="attestation.submit", obj=a, before=before,
                 summary=("An employee replaced their AI use check-in answer" if prev is not None else "An employee submitted the AI use check-in") + (" in the app" if source == "in_app" else ""))
    from app.inventory.service import sync_tools_from_attestations

    sync_tools_from_attestations(db, c.organization_id)
    return a


def submit(db: Session, token: str, payload: dict, request=None) -> Attestation:
    """Record one answer from the shared link. A later answer with the same email supersedes the earlier one; both are
    kept. When the email belongs to a client user with a login, the answer is tied to that user too."""
    c = by_token(db, token)
    if not is_open(c):
        raise Gone("This check-in has closed. Thank you; no answer is needed now.")
    values = _clean(payload, c)
    return _record(db, c, values, user=_login_for(db, c, values["respondent_email"]), source="link")


# ---- in-app attestation for client users with a login
def _active_users(db: Session, org_id: str) -> list[User]:
    return list(db.scalars(select(User).where(User.organization_id == org_id, User.status == "active", User.deleted_at.is_(None)).order_by(User.name)))


def _assignment(db: Session, c: AttestationCampaign, user_id: str) -> AttestationAssignment | None:
    return db.scalar(select(AttestationAssignment).where(AttestationAssignment.campaign_id == c.id, AttestationAssignment.user_id == user_id, AttestationAssignment.deleted_at.is_(None)))


def _assign(db: Session, settings, c: AttestationCampaign, user: User, actor_id: str | None) -> AttestationAssignment | None:
    """Create the user's line item and tell them, once. Returns None when they already have one."""
    if _assignment(db, c, user.id) is not None:
        return None
    a = AttestationAssignment(organization_id=c.organization_id, campaign_id=c.id, engagement_id=c.engagement_id, user_id=user.id, sent_at=utcnow(), created_by=actor_id)
    db.add(a)
    db.flush()
    from app.notifications.service import notify

    org = db.get(Organization, c.organization_id)
    closes = f"{c.closes_at:%B} {c.closes_at.day}, {c.closes_at.year}"
    notify(db, [user], "attestation_sent", f"{org.name}: AI use attestation to complete", f"Say which AI tools and agents you use for work. It takes about three minutes and closes on {closes}.",
           "/my-attestation", engagement=db.get(Engagement, c.engagement_id), settings=settings, email_template="attestation_sent", context={"client": org.name, "closes": closes})
    return a


def send_in_app(db: Session, settings, actor: User, c: AttestationCampaign) -> dict:
    """Give every client user who has accepted their invitation an "AI use attestation" line item."""
    if not is_open(c):
        raise Conflict("The campaign has closed, so the attestation can't be sent. Launch a new campaign first.")
    users = _active_users(db, c.organization_id)
    new = [u for u in users if _assign(db, settings, c, u, actor.id) is not None]
    first = c.sent_in_app_at is None
    c.sent_in_app_at = c.sent_in_app_at or utcnow()
    audit.record(db, actor_id=actor.id, action="attestation.send", obj=c, after={"users": len(new)},
                 summary=f"Sent the AI use attestation to {len(new)} {'user' if len(new) == 1 else 'users'} with a login" + ("" if first else " (sent again; earlier recipients were not told twice)"))
    return {"sent": len(new), "total": len(users), "sent_at": c.sent_in_app_at.isoformat()}


def on_user_activated(db: Session, settings, user: User) -> None:
    """A user who accepts their invitation while a sent campaign is open gets the line item straight away."""
    from app.tenancy.people import current_engagement

    org = db.get(Organization, user.organization_id)
    if org is None or org.type != "client":
        return
    e = current_engagement(db, org)
    c = current_campaign(db, e) if e is not None else None
    if c is not None and c.sent_in_app_at is not None and is_open(c):
        _assign(db, settings, c, user, None)


def _own_answer(db: Session, c: AttestationCampaign, user: User) -> Attestation | None:
    return db.scalar(select(Attestation).where(Attestation.campaign_id == c.id, Attestation.superseded_by_id.is_(None), Attestation.deleted_at.is_(None),
                                               or_(Attestation.user_id == user.id, func.lower(Attestation.respondent_email) == user.email.lower())).order_by(Attestation.submitted_at.desc()).limit(1))


def _prefill(db: Session, c: AttestationCampaign | None, user: User) -> dict:
    """The user's department, from their profile or else their one department role, when it is in the campaign."""
    from app.tenancy.service import roles_of

    in_campaign = set(c.department_ids or []) if c is not None else set()
    dept = user.department_id if user.department_id in in_campaign else None
    if dept is None:
        scoped = {r.scope_id for r in roles_of(db, user.id) if r.scope_type == "department" and r.scope_id in in_campaign}
        dept = scoped.pop() if len(scoped) == 1 else None
    return {"respondent_name": user.name, "respondent_email": user.email.lower(), "department_id": dept}


def my_attestation(db: Session, settings, user: User, e: Engagement | None) -> dict:
    c = current_campaign(db, e) if e is not None else None
    out = {"line_item": None, "prefill": _prefill(db, c, user), "form": None}
    if c is None:
        return out
    item = _assignment(db, c, user.id)
    if item is None and c.sent_in_app_at is not None and is_open(c) and user.status == "active":
        item = _assign(db, settings, c, user, None)  # safety net for users activated another way
    if item is None:
        return out
    answer = _own_answer(db, c, user)
    status = "submitted" if answer is not None else ("to_do" if is_open(c) else "closed")
    out["line_item"] = {"title": "AI use attestation", "status": status, "sent_at": item.sent_at.isoformat(), "closes_at": c.closes_at.isoformat(),
                        "submitted_at": answer.submitted_at.isoformat() if answer else None, "via": answer.source if answer else None}
    if status == "to_do":
        out["form"] = public_view(db, c)
    return out


def submit_own(db: Session, settings, user: User, e: Engagement | None, payload: dict) -> Attestation:
    c = current_campaign(db, e) if e is not None else None
    if c is None or (_assignment(db, c, user.id) is None and not (c.sent_in_app_at and is_open(c))):
        raise NotFound("No attestation has been sent to you.")
    if not is_open(c):
        raise Gone("The attestation has closed. Thank you; no answer is needed now.")
    prev = _own_answer(db, c, user)
    if prev is not None:
        raise Conflict(f"You submitted your attestation on {prev.submitted_at:%B} {prev.submitted_at.day}, {prev.submitted_at.year}. If something has changed, tell your Chief AI Compliance Officer.")
    pre = _prefill(db, c, user)
    data = dict(payload) | {"respondent_name": pre["respondent_name"], "respondent_email": pre["respondent_email"]}
    if pre["department_id"]:
        data["department_id"] = pre["department_id"]
    values = _clean(data, c)
    if _assignment(db, c, user.id) is None:
        _assign(db, settings, c, user, None)
    return _record(db, c, values, user=user, source="in_app")


def in_app_status(db: Session, c: AttestationCampaign, *, names: bool) -> dict:
    """Line items sent and completed. Names of those still to do go only to people who see individual answers."""
    items = list(db.scalars(select(AttestationAssignment).where(AttestationAssignment.campaign_id == c.id, AttestationAssignment.deleted_at.is_(None))))
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_([i.user_id for i in items])))} if items else {}
    rows = current_answers(db, c.id)
    by_user = {r.user_id for r in rows if r.user_id}
    by_email = {r.respondent_email.lower() for r in rows if r.respondent_email}
    done = lambda u: u.id in by_user or u.email.lower() in by_email  # noqa: E731
    live = [users[i.user_id] for i in items if i.user_id in users and users[i.user_id].deleted_at is None and users[i.user_id].status == "active"]
    out = {"sent_at": c.sent_in_app_at.isoformat() if c.sent_in_app_at else None, "assigned": len(live), "submitted": sum(1 for u in live if done(u))}
    if names:
        depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == c.organization_id))}
        out["outstanding"] = [{"id": u.id, "name": u.name, "email": u.email, "department": depts.get(u.department_id)} for u in sorted(live, key=lambda u: u.name) if not done(u)]
    return out


# ---- tracker
def _label(t: dict) -> str:
    spec = TOOL_SPECS.get(t["tool"], {})
    base = t.get("name") if spec.get("has_name") and t.get("name") else spec.get("label", t["tool"])
    return f"{base} · {ACCOUNT_LABELS.get(t['account_type'], t['account_type']).lower()}"


def _kind(t: dict) -> str:
    return TOOL_SPECS.get(t["tool"], {}).get("kind", "tool")


def _purposes(r: Attestation) -> list[str]:
    return [f"Something else: {r.purpose_other}" if p == "other" and r.purpose_other else PURPOSE_LABELS.get(p, p) for p in r.purposes or []]


def _mask(n: int) -> int | str:
    return n if n == 0 or n >= MIN_AGGREGATE else "fewer than 3"


def _user_names(db: Session, ids: set) -> dict:
    ids = {i for i in ids if i}
    return {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def individual_row(r: Attestation, depts: dict, people: dict) -> dict:
    return {
        "id": r.id, "name": r.respondent_name, "email": r.respondent_email, "department_id": r.department_id, "department": depts.get(r.department_id), "uses_ai": r.uses_ai,
        "tools": [_label(t) for t in r.tools_declared or []], "tool_items": [{"label": _label(t), "kind": _kind(t), "tool": t["tool"], "account_type": t["account_type"], "name": t.get("name"), "has_name": bool(TOOL_SPECS.get(t["tool"], {}).get("has_name"))} for t in r.tools_declared or []],
        "account_types": list(dict.fromkeys(ACCOUNT_LABELS.get(t["account_type"], t["account_type"]) for t in r.tools_declared or [])),
        "personal_account": any(t["account_type"].startswith("personal") for t in r.tools_declared or []),
        "purposes": _purposes(r), "purpose_other": r.purpose_other, "data_entered": [DATA_SHORT.get(d, d) for d in r.data_entered or []],
        "policy_acknowledged": r.policy_acknowledged, "submitted_at": r.submitted_at.isoformat(), "source": r.source or "link",
        "status": "reviewed" if r.reviewed_at else "new", "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None, "reviewed_by": people.get(r.reviewed_by),
        "edited_at": r.edited_at.isoformat() if r.edited_at else None, "edited_by": people.get(r.edited_by), "reviewer_note": r.reviewer_note,
    }


def tracker(db: Session, actor, c: AttestationCampaign, *, dept_scope: set[str] | None, individuals: bool) -> dict:
    """Counts by department and tools declared. For viewers without access to individual answers every count from
    1 to 2 is masked, and totals are hidden when any department is masked (so it can't be worked out by subtraction)."""
    rows = current_answers(db, c.id)
    if dept_scope is not None:
        rows = [r for r in rows if r.department_id in dept_scope]
    depts = list(db.scalars(select(Department).where(Department.id.in_(c.department_ids)).order_by(Department.name)))
    if dept_scope is not None:
        depts = [d for d in depts if d.id in dept_scope]
    names = {d.id: d.name for d in depts}
    per = {d.id: sum(1 for r in rows if r.department_id == d.id) for d in depts}
    out_depts = [{"id": d.id, "name": d.name, "responses": _mask(per[d.id]), "headcount": d.headcount} for d in depts]
    tools: dict[str, int] = {}
    kinds: dict[str, str] = {}
    for r in rows:
        for t in r.tools_declared or []:
            tools[_label(t)] = tools.get(_label(t), 0) + 1
            kinds[_label(t)] = _kind(t)
    personal = sum(1 for r in rows if any(t["account_type"].startswith("personal") for t in r.tools_declared or []))
    use_ai = sum(r.uses_ai for r in rows)
    show = (lambda n: n) if individuals else _mask
    any_masked = any(0 < n < MIN_AGGREGATE for n in per.values())
    result = {
        "campaign": {"id": c.id, "status": "open" if is_open(c) else "closed", "policy_version": c.policy_version, "launched_at": c.launched_at.isoformat(), "closes_at": c.closes_at.isoformat(), "closed_at": c.closed_at.isoformat() if c.closed_at else None, "link": f"/attest/{c.link_token}" if individuals else None,
                     "department_ids": list(c.department_ids or [])},
        "totals": {"responses": len(rows) if individuals else ("hidden" if any_masked else _mask(len(rows))), "use_ai": show(use_ai), "personal_accounts": show(personal), "headcount": sum(d.headcount or 0 for d in depts) or None},
        "departments": out_depts,
        "tools": sorted(({"label": k, "count": show(v), "kind": kinds[k]} for k, v in tools.items()), key=lambda x: -tools[x["label"]]),
        "individuals": None,
        "in_app": None,
    }
    if individuals:
        people = _user_names(db, {r.reviewed_by for r in rows} | {r.edited_by for r in rows})
        all_depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == c.organization_id))}
        result["individuals"] = [individual_row(r, all_depts | names, people) for r in sorted(rows, key=lambda r: r.submitted_at, reverse=True)]
        result["in_app"] = in_app_status(db, c, names=True)
        audit.record(db, actor_id=actor.id, action="attestation.view_individual", obj=c, summary=f"Viewed {len(rows)} individual attestation answers")
    return result


# ---- individual answers: review, correct, remove, export (CAICO and DPO; export also Futran)
def answers_by_ids(db: Session, c: AttestationCampaign, ids) -> list[Attestation]:
    ids = [i for i in dict.fromkeys(ids if isinstance(ids, list) else []) if isinstance(i, str)][:1000]
    if not ids:
        return []
    return list(db.scalars(select(Attestation).where(Attestation.campaign_id == c.id, Attestation.id.in_(ids), Attestation.deleted_at.is_(None), Attestation.superseded_by_id.is_(None)).order_by(Attestation.submitted_at.desc())))


def answer(db: Session, c: AttestationCampaign, answer_id: str) -> Attestation:
    rows = answers_by_ids(db, c, [answer_id])
    if not rows:
        raise NotFound()
    return rows[0]


def mark_reviewed(db: Session, actor: User, c: AttestationCampaign, ids) -> int:
    rows = [r for r in answers_by_ids(db, c, ids) if r.reviewed_at is None]
    now = utcnow()
    for r in rows:
        r.reviewed_at, r.reviewed_by = now, actor.id
        audit.record(db, actor_id=actor.id, action="attestation.review", obj=r, summary="Marked an attestation answer as reviewed")
    return len(rows)


def remove(db: Session, actor: User, c: AttestationCampaign, ids, reason) -> int:
    why = _text(reason, 300)
    if not why:
        raise Invalid(errors=[{"field": "reason", "message": "Say why the answers are being removed, for example a duplicate or a test."}])
    rows = answers_by_ids(db, c, ids)
    now = utcnow()
    for r in rows:
        r.deleted_at, r.removed_by, r.removed_reason = now, actor.id, why
        audit.record(db, actor_id=actor.id, action="attestation.remove", obj=r, before={k: getattr(r, k) for k in ANSWER_FIELDS} | {"department_id": r.department_id}, after={"reason": why},
                     summary=f"Removed an attestation answer: {why}")
    if rows:
        from app.inventory.service import sync_tools_from_attestations

        sync_tools_from_attestations(db, c.organization_id)
    return len(rows)


def _editable(r: Attestation, depts: dict) -> dict:
    return {"department": depts.get(r.department_id, r.department_id), "respondent_name": r.respondent_name, "purpose_other": r.purpose_other,
            "tool_names": [t.get("name") for t in r.tools_declared or [] if TOOL_SPECS.get(t["tool"], {}).get("has_name")], "reviewer_note": r.reviewer_note}


def edit(db: Session, actor: User, c: AttestationCampaign, r: Attestation, data: dict) -> Attestation:
    """Correct the department and the free-text fields, or add a reviewer note. The employee's tool, purpose and data
    answers are never changed here; every change is logged with the values before and after."""
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == c.organization_id))}
    before = _editable(r, depts)
    errs = []
    if "department_id" in data:
        if data["department_id"] not in (c.department_ids or []):
            errs.append({"field": "department_id", "message": "Choose a department in the campaign."})
    if "respondent_name" in data and not _text(data["respondent_name"], 120):
        errs.append({"field": "respondent_name", "message": "Enter the name."})
    if "purpose_other" in data and "other" in (r.purposes or []) and not _text(data["purpose_other"], 200):
        errs.append({"field": "purpose_other", "message": "Say what else they use AI for."})
    if errs:
        raise Invalid(errors=errs)
    if "department_id" in data:
        r.department_id = data["department_id"]
    if "respondent_name" in data:
        r.respondent_name = _text(data["respondent_name"], 120)
    if "purpose_other" in data and "other" in (r.purposes or []):
        r.purpose_other = _text(data["purpose_other"], 200)
    if "reviewer_note" in data:
        r.reviewer_note = str(data.get("reviewer_note") or "").strip()[:2000] or None
    names = data.get("tool_names")
    renamed = False
    if isinstance(names, dict):
        tools = [dict(t) for t in r.tools_declared or []]
        for k, v in names.items():
            i = int(k) if str(k).isdigit() else -1
            if 0 <= i < len(tools) and TOOL_SPECS.get(tools[i]["tool"], {}).get("has_name"):
                new = _text(v, 80) or None
                if new is None and TOOL_SPECS[tools[i]["tool"]].get("needs_name"):
                    raise Invalid(errors=[{"field": "tool_names", "message": "A tool or agent ticked as another one needs its name."}])
                if new != tools[i].get("name"):
                    tools[i]["name"], renamed = new, True
        if renamed:
            r.tools_declared = tools
    after = _editable(r, depts)
    changed = {k for k in before if before[k] != after[k]}
    if changed:
        r.edited_at, r.edited_by = utcnow(), actor.id
        audit.record(db, actor_id=actor.id, action="attestation.edit", obj=r, before={k: before[k] for k in changed}, after={k: after[k] for k in changed},
                     summary=f"Corrected an attestation answer ({', '.join(sorted(k.replace('_', ' ') for k in changed))})")
        if renamed:
            from app.inventory.service import sync_tools_from_attestations

            sync_tools_from_attestations(db, c.organization_id)
    db.flush()
    return r


EXPORT_HEADER = ["Name", "Email", "Department", "Uses AI", "Tools and agents", "Account types", "Purposes", "Data entered", "Policy acknowledged", "Submitted", "Answered through", "Status", "Reviewer note"]


def export_csv(db: Session, actor: User, c: AttestationCampaign, ids) -> str:
    rows = answers_by_ids(db, c, ids)
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == c.organization_id))}
    people = _user_names(db, {r.reviewed_by for r in rows} | {r.edited_by for r in rows})
    out = []
    for r in rows:
        x = individual_row(r, depts, people)
        out.append([x["name"], x["email"], x["department"], "Yes" if x["uses_ai"] else "No", "; ".join(x["tools"]), "; ".join(x["account_types"]), "; ".join(x["purposes"]), "; ".join(x["data_entered"]),
                    "Yes" if x["policy_acknowledged"] else "No", f"{r.submitted_at:%Y-%m-%d %H:%M}", "In the app" if x["source"] == "in_app" else "Staff link",
                    "Reviewed" if x["reviewed_at"] else "New", x["reviewer_note"]])
    audit.record(db, actor_id=actor.id, action="attestation.export", obj=c, after={"rows": len(out)}, summary=f"Exported {len(out)} individual attestation answers to CSV")
    return to_csv(EXPORT_HEADER, out)
