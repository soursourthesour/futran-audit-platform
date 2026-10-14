"""AI systems in scope, the vendor register and system additions after initiation (spec §19.1, template §1.3, §9.1)."""
import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.engagements.models import Engagement, EngagementTeam
from app.inventory.models import AITool, UseCase
from app.inventory.service import effective_tier
from app.notifications.service import notify
from app.policy.sod import assert_not_self_approval
from app.systems.models import BUILT_BY, DEPTHS, RISK_LEVELS, AISystem, SystemAdditionRequest, Vendor
from app.tenancy.models import Department, Organization, User

BUILT_BY_LABELS = {"in_house": "In-house", "vendor": "Vendor", "open_source_customized": "Open source (customized)", "hybrid": "Hybrid"}


def methodology_version(db: Session) -> str:
    from app.reference.models import RiskMethodology

    versions = list(db.scalars(select(RiskMethodology.version)))
    return max(versions, key=lambda v: tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)) if versions else "1.0"


def systems_for(db: Session, e: Engagement) -> list[AISystem]:
    return list(db.scalars(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.deleted_at.is_(None)).order_by(AISystem.reference_id)))


def next_reference(db: Session, e: Engagement) -> str:
    """SYS-001, SYS-002 … per engagement. Removed systems keep their number, so a number is never reused."""
    refs = db.scalars(select(AISystem.reference_id).where(AISystem.engagement_id == e.id))
    n = max((int(r[4:]) for r in refs if r and r[4:].isdigit()), default=0)
    return f"SYS-{n + 1:03d}"


def _use_cases(db: Session, e: Engagement, ids) -> list[UseCase]:
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise Invalid(errors=[{"field": "use_case_ids", "message": "Choose use cases from this engagement's inventory."}])
    ucs = []
    for uc_id in dict.fromkeys(ids):
        uc = db.get(UseCase, uc_id)
        if uc is None or uc.deleted_at is not None or uc.engagement_id != e.id:
            raise Invalid(errors=[{"field": "use_case_ids", "message": "Choose use cases from this engagement's inventory."}])
        if (effective_tier(uc) or 1) < 2:
            raise Invalid(errors=[{"field": "use_case_ids", "message": f"{uc.name} is Tier 1. Tier 1 use cases stay in the inventory and are not assessed."}])
        ucs.append(uc)
    return ucs


def depth_for(ucs: list[UseCase]) -> str | None:
    """Full if any linked use case is Tier 3 (final tier, else proposed), light for Tier 2 only, None when nothing is linked."""
    if not ucs:
        return None
    return "full" if any(effective_tier(u) == 3 for u in ucs) else "light"


def _clean(db: Session, e: Engagement, data: dict, current: AISystem | None = None) -> dict:
    """Validate a create or edit payload. Returns only the fields present."""
    out: dict = {}
    errs = []
    org_id = e.client_id
    if "name" in data or current is None:
        name = " ".join(str(data.get("name") or "").split())
        if not name and not data.get("use_case_ids"):
            errs.append({"field": "name", "message": "Enter the system name."})
        elif len(name) > 160:
            errs.append({"field": "name", "message": "The name must be 160 characters or fewer."})
        out["name"] = name
    if "version" in data:
        out["version"] = str(data.get("version") or "").strip()[:40] or None
    if "built_by" in data or current is None:
        bb = data.get("built_by")
        if bb is None and current is not None:
            out["built_by"] = None
        elif bb not in BUILT_BY:
            errs.append({"field": "built_by", "message": "Choose who built the system: in-house, vendor, open source (customized) or hybrid."})
        else:
            out["built_by"] = bb
    if "vendor_id" in data:
        v = data.get("vendor_id")
        if v:
            vendor = db.get(Vendor, v) if isinstance(v, str) else None
            if vendor is None or vendor.deleted_at is not None or vendor.organization_id != org_id:
                errs.append({"field": "vendor_id", "message": "Choose a vendor from the register."})
        out["vendor_id"] = v or None
    if "department_id" in data:
        d = data.get("department_id")
        if d:
            dept = db.get(Department, d) if isinstance(d, str) else None
            if dept is None or dept.deleted_at is not None or dept.organization_id != org_id:
                errs.append({"field": "department_id", "message": "Choose a department."})
        out["department_id"] = d or None
    for f in ("owner_user_id", "technical_owner_user_id"):
        if f in data:
            u_id = data.get(f)
            if u_id:
                u = db.get(User, u_id) if isinstance(u_id, str) else None
                if u is None or u.deleted_at is not None or u.organization_id != org_id:
                    errs.append({"field": f, "message": "Choose a person from the client's users."})
            out[f] = u_id or None
    if "tool_ids" in data:
        tools = data.get("tool_ids")
        valid = set(db.scalars(select(AITool.id).where(AITool.organization_id == org_id, AITool.deleted_at.is_(None))))
        if not isinstance(tools, list) or not all(isinstance(t, str) and t in valid for t in tools):
            errs.append({"field": "tool_ids", "message": "Choose tools from the inventory."})
        else:
            out["tool_ids"] = list(dict.fromkeys(tools))
    if "assessment_depth" in data:
        if data["assessment_depth"] not in DEPTHS:
            errs.append({"field": "assessment_depth", "message": "Choose full or light."})
        else:
            out["assessment_depth"] = data["assessment_depth"]
    if errs:
        raise Invalid(errors=errs)
    if "use_case_ids" in data or current is None:
        ucs = _use_cases(db, e, data.get("use_case_ids") or [])
        out["use_case_ids"] = [u.id for u in ucs]
        out["_ucs"] = ucs
    return out


def _apply_depth(s: AISystem, ucs: list[UseCase], requested: str | None) -> None:
    needed = depth_for(ucs)
    if requested == "light" and needed == "full":
        raise Conflict("A system with a Tier 3 use case needs a full assessment.")
    s.assessment_depth = requested or needed or s.assessment_depth or "full"


def create_system(db: Session, actor: User, e: Engagement, data: dict, *, source: str = "auditor", created_by: str | None = None) -> AISystem:
    v = _clean(db, e, data)
    ucs = v.pop("_ucs", [])
    if not v.get("name"):
        v["name"] = ucs[0].name[:160]
    if "department_id" not in v and ucs:
        v["department_id"] = ucs[0].department_id
    if "tool_ids" not in v and ucs:
        v["tool_ids"] = list(dict.fromkeys(t for u in ucs for t in (u.tool_ids or [])))
    requested = v.pop("assessment_depth", None)
    s = AISystem(organization_id=e.client_id, engagement_id=e.id, reference_id=next_reference(db, e), source=source, status="not_started", completion_pct=0,
                 methodology_version=methodology_version(db), created_by=created_by or actor.id, updated_by=actor.id, **v)
    _apply_depth(s, ucs, requested)
    db.add(s)
    db.flush()
    audit.record(db, actor_id=actor.id, action="system.create", obj=s, after={"name": s.name, "reference_id": s.reference_id, "depth": s.assessment_depth, "use_case_ids": s.use_case_ids}, summary=f"Added {s.reference_id} {s.name} ({s.assessment_depth} assessment)")
    return s


def create_from_use_case(db: Session, actor: User, e: Engagement, uc_ids: list[str], built_by: str, name: str | None = None, vendor_id: str | None = None, department_id: str | None = None) -> AISystem:
    data: dict = {"use_case_ids": uc_ids, "built_by": built_by, "name": name or ""}
    if vendor_id:
        data["vendor_id"] = vendor_id
    if department_id:
        data["department_id"] = department_id
    return create_system(db, actor, e, data)


def convert_planned(db: Session, actor: User, e: Engagement) -> list[AISystem]:
    """At approve-and-send, the systems listed in the wizard become AI systems with a full assessment until tiers are known."""
    have = {s.name.casefold() for s in systems_for(db, e)}
    out = []
    for name in e.planned_systems or []:
        name = " ".join(str(name).split())[:160]
        if name and name.casefold() not in have:
            s = AISystem(organization_id=e.client_id, engagement_id=e.id, reference_id=next_reference(db, e), name=name, source="wizard", assessment_depth="full",
                         status="not_started", completion_pct=0, methodology_version=methodology_version(db), tool_ids=[], use_case_ids=[], created_by=actor.id)
            db.add(s)
            db.flush()
            have.add(name.casefold())
            out.append(s)
    if out:
        audit.record(db, actor_id=actor.id, action="system.create", obj=e, after={"systems": [s.reference_id for s in out]}, summary=f"Listed {len(out)} AI systems in scope from the engagement setup")
    return out


def update_system(db: Session, actor: User, s: AISystem, data: dict) -> AISystem:
    if s.status == "locked":
        raise Conflict("This system's assessment is locked.")
    e = db.get(Engagement, s.engagement_id)
    v = _clean(db, e, data, current=s)
    ucs = v.pop("_ucs", None)
    requested = v.pop("assessment_depth", None)
    if "name" in v and not v["name"]:
        v.pop("name")
    before = {k: getattr(s, k) for k in v} | {"assessment_depth": s.assessment_depth}
    for k, val in v.items():
        setattr(s, k, val)
    linked = ucs if ucs is not None else [u for u in (db.get(UseCase, i) for i in s.use_case_ids or []) if u is not None and u.deleted_at is None]
    if ucs is not None or requested:
        _apply_depth(s, linked, requested or (None if depth_for(linked) == "full" else s.assessment_depth))
    s.updated_by = actor.id
    from app.questionnaire.service import Target, after_change

    after_change(db, Target(e, s))
    audit.record(db, actor_id=actor.id, action="system.edit", obj=s, before=before, after={k: getattr(s, k) for k in before}, summary=f"Edited {s.reference_id} {s.name}")
    return s


def sync_depth_for_use_case(db: Session, actor: User | None, uc: UseCase) -> list[AISystem]:
    """A use case that becomes Tier 3 makes every light system it maps to a full assessment (never the other way)."""
    changed = []
    for s in db.scalars(select(AISystem).where(AISystem.engagement_id == uc.engagement_id, AISystem.deleted_at.is_(None))):
        if uc.id not in (s.use_case_ids or []) or s.status == "locked" or s.assessment_depth == "full":
            continue
        linked = [u for u in (db.get(UseCase, i) for i in s.use_case_ids) if u is not None and u.deleted_at is None]
        if depth_for(linked) == "full":
            s.assessment_depth = "full"
            audit.record(db, actor_id=actor.id if actor else None, action="system.edit", obj=s, before={"assessment_depth": "light"}, after={"assessment_depth": "full"},
                         summary=f"{s.reference_id} {s.name} now needs a full assessment: {uc.name} is Tier 3")
            changed.append(s)
    if changed:
        from app.questionnaire.service import Target, after_change

        e = db.get(Engagement, uc.engagement_id)
        for s in changed:
            after_change(db, Target(e, s))
    return changed


def unmapped_tier3(db: Session, e: Engagement) -> list[UseCase]:
    """Tier 3 use cases (final tier, else proposed) that no system in scope covers. Each needs a full assessment."""
    mapped = {i for s in systems_for(db, e) for i in (s.use_case_ids or [])}
    ucs = db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None)).order_by(UseCase.name))
    return [u for u in ucs if effective_tier(u) == 3 and u.id not in mapped]


# ---- additions after initiation
def engagement_managers(db: Session, e: Engagement) -> list[User]:
    return list(db.scalars(select(User).join(EngagementTeam, EngagementTeam.user_id == User.id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.role == "engagement_manager", EngagementTeam.deleted_at.is_(None))))


def request_addition(db: Session, settings, actor: User, e: Engagement, data: dict) -> SystemAdditionRequest:
    reason = " ".join(str(data.get("reason") or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why the system is being added to the scope."}])
    payload = {k: data[k] for k in ("name", "version", "built_by", "vendor_id", "department_id", "owner_user_id", "technical_owner_user_id", "tool_ids", "use_case_ids", "assessment_depth") if k in data}
    trial = db.begin_nested()  # validate exactly as the approval will, then throw the trial row away
    try:
        create_system(db, actor, e, payload)
    finally:
        trial.rollback()
    req = SystemAdditionRequest(organization_id=e.client_id, engagement_id=e.id, requested_by=actor.id, payload=payload, reason=reason[:2000], status="pending", created_by=actor.id)
    db.add(req)
    db.flush()
    label = payload.get("name") or ", ".join(u.name for u in _use_cases(db, e, payload.get("use_case_ids") or []))
    audit.record(db, actor_id=actor.id, action="system.addition_request", obj=req, after={"payload": payload, "reason": req.reason}, summary=f"Asked to add {label} to the scope of {e.audit_ref}")
    org = db.get(Organization, e.client_id)
    notify(db, [u for u in engagement_managers(db, e) if u.id != actor.id], "system_addition_requested", f"{org.name}: approve adding {label} to the scope", f"Requested by {actor.name}. Reason: {req.reason}", f"/clients/{org.id}/systems", engagement=e, settings=settings)
    return req


def decide_addition(db: Session, settings, actor: User, req: SystemAdditionRequest, approve: bool, comment: str | None) -> SystemAdditionRequest:
    assert_not_self_approval(actor.id, req.requested_by)
    if req.status != "pending":
        raise Conflict("This request has already been decided.")
    comment = " ".join(str(comment or "").split()) or None
    if not approve and not comment:
        raise Invalid(errors=[{"field": "comment", "message": "Say why the system is not being added."}])
    e = db.get(Engagement, req.engagement_id)
    if approve:
        requester = db.get(User, req.requested_by)
        s = create_system(db, actor, e, dict(req.payload), created_by=requester.id if requester else None)
        req.system_id = s.id
    req.status, req.decided_by, req.decided_at, req.decision_comment = ("approved" if approve else "rejected"), actor.id, utcnow(), comment
    audit.record(db, actor_id=actor.id, action="system.addition_decided", obj=req, after={"status": req.status, "comment": comment}, summary=f"{'Approved' if approve else 'Declined'} a scope addition for {e.audit_ref}")
    org = db.get(Organization, e.client_id)
    notify(db, [db.get(User, req.requested_by)], "system_addition_decided", f"{org.name}: scope addition {'approved' if approve else 'declined'}", comment, f"/clients/{org.id}/systems", engagement=e, settings=settings)
    return req


# ---- vendors
def vendors_for(db: Session, org_id: str) -> list[Vendor]:
    return list(db.scalars(select(Vendor).where(Vendor.organization_id == org_id, Vendor.deleted_at.is_(None)).order_by(Vendor.legal_name)))


def _bool(v, field: str, errs: list) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    errs.append({"field": field, "message": "Answer yes, no or not known."})
    return None


def save_vendor(db: Session, actor: User, org: Organization, data: dict, vendor: Vendor | None = None) -> Vendor:
    merged = ({c: getattr(vendor, c) for c in ("legal_name", "capability", "personal_data_processed", "baa_dpa_signed", "last_risk_review", "risk_level")} if vendor else {}) | data
    errs: list[dict] = []
    name = " ".join(str(merged.get("legal_name") or "").split())
    if not name:
        errs.append({"field": "legal_name", "message": "Enter the vendor's legal name."})
    elif len(name) > 200:
        errs.append({"field": "legal_name", "message": "The name must be 200 characters or fewer."})
    risk = merged.get("risk_level") or None
    if risk is not None and risk not in RISK_LEVELS:
        errs.append({"field": "risk_level", "message": "Choose high, medium or low."})
    review = merged.get("last_risk_review")
    if isinstance(review, str) and review:
        try:
            review = date.fromisoformat(review)
        except ValueError:
            errs.append({"field": "last_risk_review", "message": "Enter a date."})
    elif not isinstance(review, date):
        review = None
    pdp = _bool(merged.get("personal_data_processed"), "personal_data_processed", errs)
    baa = _bool(merged.get("baa_dpa_signed"), "baa_dpa_signed", errs)
    if errs:
        raise Invalid(errors=errs)
    dup = db.scalar(select(Vendor).where(Vendor.organization_id == org.id, Vendor.deleted_at.is_(None), func.lower(Vendor.legal_name) == name.lower()))
    if dup is not None and (vendor is None or dup.id != vendor.id):
        raise Conflict(f"{name} is already in the vendor register.")
    before = None
    if vendor is None:
        vendor = Vendor(organization_id=org.id, created_by=actor.id)
        db.add(vendor)
    else:
        before = {"legal_name": vendor.legal_name, "risk_level": vendor.risk_level, "baa_dpa_signed": vendor.baa_dpa_signed}
    vendor.legal_name, vendor.capability = name, str(merged.get("capability") or "").strip()[:300] or None
    vendor.personal_data_processed, vendor.baa_dpa_signed, vendor.last_risk_review, vendor.risk_level = pdp, baa, review, risk
    vendor.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="vendor.save", obj=vendor, before=before, after={"legal_name": vendor.legal_name, "risk_level": vendor.risk_level, "baa_dpa_signed": vendor.baa_dpa_signed}, summary=f"{'Added' if before is None else 'Edited'} vendor {vendor.legal_name}")
    return vendor


def get_system(db: Session, system_id: str) -> AISystem:
    s = db.get(AISystem, system_id)
    if s is None or s.deleted_at is not None:
        raise NotFound()
    return s
