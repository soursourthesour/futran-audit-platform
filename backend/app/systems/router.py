from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement
from app.inventory.models import AITool, UseCase
from app.inventory.service import effective_tier, tools_for
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.systems import service as svc
from app.systems.models import AISystem, SystemAdditionRequest, Vendor
from app.tenancy.models import Department, Organization, User
from app.tenancy.people import current_engagement

router = APIRouter(tags=["systems"])


class DecideIn(BaseModel):
    approve: bool
    comment: str | None = None


def _ctx(db: Session, actor: Actor, client_id: str, action: Action) -> tuple[Organization, Engagement]:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=e.id)
    return org, e


def _may(db: Session, actor: Actor, action: Action, engagement_id: str) -> bool:
    try:
        authorize(db, actor, action, engagement_id=engagement_id)
    except (Forbidden, NotFound):
        return False
    return True


def vendor_out(v: Vendor) -> dict:
    return {"id": v.id, "legal_name": v.legal_name, "capability": v.capability, "personal_data_processed": v.personal_data_processed, "baa_dpa_signed": v.baa_dpa_signed,
            "last_risk_review": v.last_risk_review.isoformat() if v.last_risk_review else None, "risk_level": v.risk_level}


def system_out(db: Session, s: AISystem) -> dict:
    dept = db.get(Department, s.department_id) if s.department_id else None
    vendor = db.get(Vendor, s.vendor_id) if s.vendor_id else None
    ucs = [u for u in (db.get(UseCase, i) for i in s.use_case_ids or []) if u is not None and u.deleted_at is None]
    tools = [t for t in (db.get(AITool, i) for i in s.tool_ids or []) if t is not None and t.deleted_at is None]
    person = lambda uid: (lambda u: {"id": u.id, "name": u.name} if u else None)(db.get(User, uid) if uid else None)  # noqa: E731
    return {
        "id": s.id, "reference_id": s.reference_id, "name": s.name, "version": s.version, "built_by": s.built_by, "built_by_label": svc.BUILT_BY_LABELS.get(s.built_by or "", "Not set"),
        "vendor_id": s.vendor_id, "vendor": vendor.legal_name if vendor else None, "department_id": s.department_id, "department": dept.name if dept else None,
        "owner": person(s.owner_user_id), "technical_owner": person(s.technical_owner_user_id),
        "use_cases": [{"id": u.id, "name": u.name, "tier": effective_tier(u)} for u in ucs], "tools": [{"id": t.id, "label": f"{t.vendor} {t.product}"} for t in tools],
        "assessment_depth": s.assessment_depth, "status": s.status, "completion_pct": s.completion_pct, "methodology_version": s.methodology_version, "source": s.source,
        "register_system": _register_ref(db, s.register_system_id),
        **_score(db, s),
    }


def _register_ref(db: Session, rs_id: str | None) -> dict | None:
    from app.register.models import RegisterSystem

    rs = db.get(RegisterSystem, rs_id) if rs_id else None
    return {"id": rs.id, "reference": rs.reference, "name": rs.name} if rs else None


def register_options(db: Session, org_id: str, e: Engagement) -> list[dict]:
    """The client's register rows an auditor can start a system from, with the facts that will be copied."""
    from app.register.models import RegisterSystem
    from app.register.service import SOURCING_LABELS, STAGE_LABELS, TYPE_LABELS

    linked = {s.register_system_id: s.reference_id for s in svc.systems_for(db, e) if s.register_system_id}
    rows = db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None), RegisterSystem.stage != "retired").order_by(RegisterSystem.reference))
    out = []
    for rs in rows:
        f = svc.register_facts(db, rs.id)
        out.append({"id": rs.id, "reference": rs.reference, "name": rs.name, "type_label": TYPE_LABELS.get(rs.type, rs.type), "sourcing_label": SOURCING_LABELS.get(rs.sourcing, rs.sourcing),
                    "stage_label": STAGE_LABELS.get(rs.stage, rs.stage), "risk_tier": rs.risk_tier, "built_by": f.get("built_by"), "vendor_id": f.get("vendor_id"),
                    "department_id": f.get("department_id"), "owner_user_id": f.get("owner_user_id"), "linked_to": linked.get(rs.id)})
    return out


def _score(db: Session, s: AISystem) -> dict:
    from app.scoring.service import latest, methodology

    row = latest(db, s)
    if row is None:
        return {"inherent": None, "maturity": None, "residual": None, "rating": None, "knockouts": []}
    labels = {k["code"]: k["label"].split(" (")[0] for k in methodology(db, s.methodology_version).knockout_rules}
    return {"inherent": row.inherent, "maturity": row.maturity, "residual": row.residual, "rating": row.final_rating.capitalize() if row.final_rating and row.maturity is not None else None,
            "knockouts": [labels.get(k, k) for k in row.knockouts_triggered or []]}


def request_out(db: Session, r: SystemAdditionRequest) -> dict:
    who = db.get(User, r.requested_by)
    return {"id": r.id, "payload": r.payload, "reason": r.reason, "status": r.status, "requested_by": {"id": who.id, "name": who.name} if who else None,
            "requested_at": r.created_at.isoformat(), "decision_comment": r.decision_comment}


@router.get("/clients/{client_id}/systems")
def get_register(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:
        raise NotFound()  # the client's systems page is the pre-fill screen
    org, e = _ctx(db, actor, client_id, Action.VIEW_ENGAGEMENT)
    systems = svc.systems_for(db, e)
    ucs = list(db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None)).order_by(UseCase.name)))
    requests = db.scalars(select(SystemAdditionRequest).where(SystemAdditionRequest.engagement_id == e.id, SystemAdditionRequest.deleted_at.is_(None), SystemAdditionRequest.status == "pending").order_by(SystemAdditionRequest.created_at))
    users = db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None)).order_by(User.name))
    depts = db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None), Department.in_scope.is_(True)).order_by(Department.name))
    return {
        "client": {"id": org.id, "name": org.name}, "audit_ref": e.audit_ref, "stage": e.stage,
        "systems": [system_out(db, s) for s in systems],
        "unmapped_tier3": [{"id": u.id, "name": u.name, "department_id": u.department_id} for u in svc.unmapped_tier3(db, e)],
        "use_case_options": [{"id": u.id, "name": u.name, "tier": effective_tier(u)} for u in ucs if (effective_tier(u) or 1) >= 2],
        "tool_options": [{"id": t.id, "label": f"{t.vendor} {t.product}"} for t in tools_for(db, org.id)],
        "vendors": [vendor_out(v) for v in svc.vendors_for(db, org.id)],
        "departments": [{"id": d.id, "name": d.name} for d in depts],
        "people": [{"id": u.id, "name": u.name} for u in users],
        "pending_requests": [request_out(db, r) for r in requests],
        "register_options": register_options(db, org.id, e),
        "can_manage": _may(db, actor, Action.MANAGE_SYSTEMS, e.id),
        "can_approve_additions": _may(db, actor, Action.APPROVE_SYSTEM_ADDITION, e.id),
    }


@router.post("/clients/{client_id}/systems")
def add_system(client_id: str, data: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """After initiation every addition goes to the Engagement Manager (template §1.3)."""
    org, e = _ctx(db, actor, client_id, Action.MANAGE_SYSTEMS)
    return request_out(db, svc.request_addition(db, request.app.state.settings, actor.user, e, data))


@router.post("/system-requests/{request_id}/decide")
def decide(request_id: str, body: DecideIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    r = db.get(SystemAdditionRequest, request_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.APPROVE_SYSTEM_ADDITION, engagement_id=r.engagement_id)
    return request_out(db, svc.decide_addition(db, request.app.state.settings, actor.user, r, body.approve, body.comment))


@router.patch("/systems/{system_id}")
def patch_system(system_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = svc.get_system(db, system_id)
    authorize(db, actor, Action.MANAGE_SYSTEMS, engagement_id=s.engagement_id)
    return system_out(db, svc.update_system(db, actor.user, s, data))


@router.post("/clients/{client_id}/vendors")
def post_vendor(client_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org, e = _ctx(db, actor, client_id, Action.MANAGE_SYSTEMS)
    return vendor_out(svc.save_vendor(db, actor.user, org, data))


@router.patch("/vendors/{vendor_id}")
def patch_vendor(vendor_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    v = db.get(Vendor, vendor_id)
    if v is None or v.deleted_at is not None:
        raise NotFound()
    org, e = _ctx(db, actor, v.organization_id, Action.MANAGE_SYSTEMS)
    return vendor_out(svc.save_vendor(db, actor.user, org, data, vendor=v))


@router.get("/systems/{system_id}/register-record")
def get_register_record(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The client's register record behind an audit system: bias tests and history, read-only for the audit team."""
    s = svc.get_system(db, system_id)
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.VIEW_REGISTER, engagement_id=s.engagement_id)
    from app.register.history import entry_out, statement_out
    from app.register.models import BiasTest, HistoryEntry, RegisterSystem
    from app.register.service import STAGE_LABELS, TYPE_LABELS, bias_status

    rs = db.get(RegisterSystem, s.register_system_id) if s.register_system_id else None
    if rs is None or rs.deleted_at is not None or rs.organization_id != s.organization_id:
        return {"system": None, "bias_tests": [], "history": [], "statement": None}
    tests = db.scalars(select(BiasTest).where(BiasTest.register_system_id == rs.id, BiasTest.deleted_at.is_(None)).order_by(BiasTest.tested_on.desc()))
    entries = db.scalars(select(HistoryEntry).where(HistoryEntry.register_system_id == rs.id, HistoryEntry.deleted_at.is_(None)).order_by(HistoryEntry.occurred_on.desc()))
    from app.audit_log import service as audit

    audit.record(db, actor_id=actor.id, action="register.view_by_auditor", obj=rs, engagement_id=s.engagement_id, summary=f"Viewed the register record of {rs.reference} {rs.name}")
    return {
        "system": {"id": rs.id, "reference": rs.reference, "name": rs.name, "type_label": TYPE_LABELS.get(rs.type, rs.type), "stage_label": STAGE_LABELS.get(rs.stage, rs.stage),
                   "risk_tier": rs.risk_tier, "live_since": rs.live_since.isoformat() if rs.live_since else None, "bias": bias_status(db, rs), "history_answers": rs.history_answers or {}},
        "bias_tests": [{"id": b.id, "tested_on": b.tested_on.isoformat(), "next_due": b.next_due.isoformat() if b.next_due else None, "tester_type": b.tester_type, "tester_name": b.tester_name,
                        "method": b.method, "groups_tested": b.groups_tested, "result": b.result, "result_text": b.result_text, "unknown_share": b.unknown_share,
                        "null_compliance": (b.unknown_share or 0) > 50} for b in tests],
        "history": [entry_out(db, h) for h in entries],
        "statement": statement_out(db, rs),
    }
