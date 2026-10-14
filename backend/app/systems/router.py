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
        # filled by the scoring engine (Task 25)
        "inherent": None, "maturity": None, "residual": None, "rating": None, "knockouts": [],
    }


def request_out(db: Session, r: SystemAdditionRequest) -> dict:
    who = db.get(User, r.requested_by)
    return {"id": r.id, "payload": r.payload, "reason": r.reason, "status": r.status, "requested_by": {"id": who.id, "name": who.name} if who else None,
            "requested_at": r.created_at.isoformat(), "decision_comment": r.decision_comment}


@router.get("/clients/{client_id}/systems")
def get_register(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
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
        "can_manage": _may(db, actor, Action.MANAGE_SYSTEMS, e.id),
        "can_approve_additions": _may(db, actor, Action.APPROVE_SYSTEM_ADDITION, e.id),
    }


@router.post("/clients/{client_id}/systems")
def add_system(client_id: str, data: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """After initiation every addition goes to the Engagement Manager (template §1.3)."""
    org, e = _ctx(db, actor, client_id, Action.MANAGE_SYSTEMS)
    return request_out(db, svc.request_addition(db, request.app.state.settings, actor.user, e, data))


@router.post("/system-requests/{request_id}/decide")
def decide(request_id: str, body: DecideIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    r = db.get(SystemAdditionRequest, request_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.APPROVE_SYSTEM_ADDITION, engagement_id=r.engagement_id)
    return request_out(db, svc.decide_addition(db, request.app.state.settings, actor.user, r, body.approve, body.comment))


@router.patch("/systems/{system_id}")
def patch_system(system_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    s = svc.get_system(db, system_id)
    authorize(db, actor, Action.MANAGE_SYSTEMS, engagement_id=s.engagement_id)
    return system_out(db, svc.update_system(db, actor.user, s, data))


@router.post("/clients/{client_id}/vendors")
def post_vendor(client_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org, e = _ctx(db, actor, client_id, Action.MANAGE_SYSTEMS)
    return vendor_out(svc.save_vendor(db, actor.user, org, data))


@router.patch("/vendors/{vendor_id}")
def patch_vendor(vendor_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    v = db.get(Vendor, vendor_id)
    if v is None or v.deleted_at is not None:
        raise NotFound()
    org, e = _ctx(db, actor, v.organization_id, Action.MANAGE_SYSTEMS)
    return vendor_out(svc.save_vendor(db, actor.user, org, data, vendor=v))
