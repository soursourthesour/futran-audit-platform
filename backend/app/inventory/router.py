from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.core.ratelimit import client_ip, limiter
from app.engagements.models import Engagement
from app.inventory import service as inv
from app.inventory.models import AITool, NamedUserLink, UsageRecord, UseCase
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.policy.sod import assert_not_admin_judgment
from app.tenancy.models import Department, Organization, User
from app.tenancy.people import current_engagement

router = APIRouter(tags=["inventory"])


class TierIn(BaseModel):
    tier: int
    rationale: str = ""
    aedt_determination: str | None = None


class ReviewIn(BaseModel):
    approve: bool
    comment: str | None = None


class PreviewIn(BaseModel):
    decision_impact: str | None = None
    data_categories: list[str] = []
    tool_ids: list[str] = []


def _ctx(db: Session, actor: Actor, client_id: str, action: Action, department_id: str | None = None, list_view: bool = False) -> tuple[Organization, Engagement]:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=e.id, department_id=department_id, list_view=list_view)
    return org, e


def _may(db: Session, actor: Actor, action: Action, engagement_id: str) -> bool:
    try:
        authorize(db, actor, action, engagement_id=engagement_id)
    except (Forbidden, NotFound):
        return False
    return True


def tool_out(t: AITool, counts: bool = True) -> dict:
    return {"id": t.id, "vendor": t.vendor, "product": t.product, "plan": t.plan, "account_type": t.account_type, "sso": t.sso, "training_on_inputs": t.training_on_inputs, "retention_terms": t.retention_terms, "approval_status": t.approval_status, "source": t.source, "declared_count": t.declared_count if counts else None}


def use_case_out(db: Session, uc: UseCase, detail: bool = False) -> dict:
    dept = db.get(Department, uc.department_id)
    tools = [t for t in inv.tools_for(db, uc.organization_id) if t.id in (uc.tool_ids or [])]
    out = {
        "id": uc.id, "name": uc.name, "department_id": uc.department_id, "department": dept.name if dept else None, "status": uc.status,
        "tools": [f"{t.product} · {t.account_type.replace('_', ' ')}" for t in tools], "tool_ids": uc.tool_ids, "proposed_tier": uc.proposed_tier,
        "final_tier": uc.final_tier, "final_tier_rationale": uc.final_tier_rationale, "aedt_determination": uc.aedt_determination, "returned_comment": uc.returned_comment,
    }
    if detail:
        out |= {
            "purpose": uc.purpose, "data_categories": uc.data_categories, "decision_impact": uc.decision_impact,
            "tier_reason": inv.tier_reason(uc.decision_impact, uc.data_categories, tools),
            "usage": [{"role_name": u.role_name, "headcount": u.headcount, "frequency": u.frequency} for u in db.scalars(select(UsageRecord).where(UsageRecord.use_case_id == uc.id, UsageRecord.deleted_at.is_(None)))],
            "named_users": [
                {"id": n.id, "person_name": n.person_name, "email": n.email, "role_name": n.role_name, "oversight_role": n.oversight_role, "has_account": n.user_id is not None,
                 "training_complete": n.training_complete, "policy_acknowledged": n.policy_acknowledged, "oversight_role_confirmed": n.oversight_role_confirmed,
                 "link_sent": db.scalar(select(NamedUserLink.sent_at).where(NamedUserLink.named_user_id == n.id, NamedUserLink.revoked_at.is_(None)).order_by(NamedUserLink.sent_at.desc()).limit(1)) is not None}
                for n in inv.named_users(db, uc)
            ],
        }
    return out


@router.get("/clients/{client_id}/inventory")
def get_inventory(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org, e = _ctx(db, actor, client_id, Action.VIEW_INVENTORY, list_view=True)
    scope = None if actor.is_futran else departments_for(actor, Action.VIEW_INVENTORY)
    ucs = [u for u in db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None)).order_by(UseCase.name)) if scope is None or u.department_id in scope]
    tiers = {t: sum(1 for u in ucs if inv.effective_tier(u) == t) for t in (1, 2, 3)}
    depts = db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None), Department.in_scope.is_(True)).order_by(Department.name))
    # Declared counts and employee-typed tool names come from individual attestations: aggregate viewers don't see them.
    individual = _may(db, actor, Action.VIEW_INDIVIDUAL_ATTESTATIONS, e.id)
    tools = [t for t in inv.tools_for(db, org.id) if individual or not (t.source == "attestation" and t.vendor == "Other" and t.approval_status == "unreviewed")]
    return {
        "tools": [tool_out(t, counts=individual) for t in tools],
        "use_cases": [use_case_out(db, u) for u in ucs],
        "tiers": tiers,
        "departments": [{"id": d.id, "name": d.name} for d in depts if scope is None or d.id in scope],
        "is_futran": actor.is_futran,
    }


@router.post("/clients/{client_id}/tools")
def post_tool(client_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org, e = _ctx(db, actor, client_id, Action.REGISTER_AI_TOOL, list_view=True)
    return tool_out(inv.save_tool(db, actor.user, org, {k: v for k, v in data.items() if k != "approval_status"}))


@router.patch("/tools/{tool_id}")
def patch_tool(tool_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    t = db.get(AITool, tool_id)
    if t is None or t.deleted_at:
        raise NotFound()
    org, e = _ctx(db, actor, t.organization_id, Action.REGISTER_AI_TOOL, list_view=True)
    caico = not actor.is_futran and actor.has_role("caico")
    if not caico and not actor.is_futran:
        raise Forbidden("Only the Chief AI Compliance Officer can change a tool already in the inventory.")
    if "approval_status" in data and data["approval_status"] != t.approval_status and not caico:
        raise Forbidden("Only the Chief AI Compliance Officer can approve tools.")
    return tool_out(inv.save_tool(db, actor.user, org, {**tool_out(t), **data}, tool=t, can_approve=caico))


@router.post("/clients/{client_id}/use-cases/tier-preview")
def tier_preview(client_id: str, body: PreviewIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org, e = _ctx(db, actor, client_id, Action.VIEW_INVENTORY, list_view=True)
    tools = [t for t in inv.tools_for(db, org.id) if t.id in body.tool_ids]
    tier = inv.propose_tier(body.decision_impact, body.data_categories, tools)
    return {"tier": tier, "label": inv.TIER_NAMES[tier], "reason": inv.tier_reason(body.decision_impact, body.data_categories, tools)}


@router.post("/clients/{client_id}/use-cases")
def post_use_case(client_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    dept = data.get("department_id") if isinstance(data.get("department_id"), str) else None
    org, e = _ctx(db, actor, client_id, Action.SUBMIT_USE_CASE, department_id=dept)
    return use_case_out(db, inv.save_use_case(db, actor.user, org, e, data), detail=True)


def _uc(db: Session, actor: Actor, uc_id: str, action: Action) -> UseCase:
    uc = db.get(UseCase, uc_id)
    if uc is None or uc.deleted_at:
        raise NotFound()
    authorize(db, actor, action, engagement_id=uc.engagement_id, department_id=uc.department_id)
    return uc


@router.get("/use-cases/{uc_id}")
def get_use_case(uc_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return use_case_out(db, _uc(db, actor, uc_id, Action.VIEW_INVENTORY), detail=True)


@router.put("/use-cases/{uc_id}")
def put_use_case(uc_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    uc = _uc(db, actor, uc_id, Action.SUBMIT_USE_CASE)
    if isinstance(data.get("department_id"), str) and data["department_id"] != uc.department_id:
        authorize(db, actor, Action.SUBMIT_USE_CASE, engagement_id=uc.engagement_id, department_id=data["department_id"])
    org = db.get(Organization, uc.organization_id)
    return use_case_out(db, inv.save_use_case(db, actor.user, org, db.get(Engagement, uc.engagement_id), data, uc), detail=True)


@router.post("/use-cases/{uc_id}/submit")
def submit(uc_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    uc = _uc(db, actor, uc_id, Action.SUBMIT_USE_CASE)
    return use_case_out(db, inv.submit_use_case(db, request.app.state.settings, actor.user, uc), detail=True)


@router.post("/use-cases/{uc_id}/review")
def review(uc_id: str, body: ReviewIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    uc = _uc(db, actor, uc_id, Action.APPROVE_USE_CASE)
    return use_case_out(db, inv.review_use_case(db, actor.user, uc, body.approve, body.comment), detail=True)


@router.post("/use-cases/{uc_id}/final-tier")
def final_tier(uc_id: str, body: TierIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    uc = db.get(UseCase, uc_id)
    if uc is None or uc.deleted_at:
        raise NotFound()
    assert_not_admin_judgment(actor)
    try:
        authorize(db, actor, Action.SET_FINAL_TIER, engagement_id=uc.engagement_id)
    except Forbidden:
        authorize(db, actor, Action.OVERRIDE_FINAL_TIER, engagement_id=uc.engagement_id)
    return use_case_out(db, inv.set_final_tier(db, request.app.state.settings, actor.user, uc, body.tier, body.rationale, body.aedt_determination), detail=True)


# ---- public named-user confirmation (D13)
@router.get("/public/confirm/{token}")
def public_confirm_get(token: str, db: Session = Depends(get_db)):
    return inv.public_confirm_view(db, inv.link_by_token(db, token))


@router.post("/public/confirm/{token}")
def public_confirm_post(token: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    limiter(request, "confirm", 30).check(f"{token}:{client_ip(request)}")
    inv.confirm(db, token, payload, request)
    return {"received": True}


class UnableIn(BaseModel):
    reason: str | None = None


@router.post("/named-users/{named_user_id}/unable")
def mark_unable(named_user_id: str, body: UnableIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """The Department Lead records that a named user cannot confirm (left, on leave), so sign-off 2 can proceed (§8a)."""
    from app.audit_log import service as audit
    from app.core.errors import Invalid
    from app.inventory.models import NamedUser

    n = db.get(NamedUser, named_user_id)
    uc = db.get(UseCase, n.use_case_id) if n is not None and n.deleted_at is None else None
    if uc is None or uc.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.APPROVE_USE_CASE, engagement_id=uc.engagement_id, department_id=uc.department_id)
    reason = " ".join(str(body.reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why this person cannot confirm."}])
    n.unable_reason, n.unable_marked_by = reason[:2000], actor.id
    audit.record(db, actor_id=actor.id, action="inventory.named_user_unable", obj=n, after={"reason": n.unable_reason}, summary=f"Marked {n.person_name} unable to confirm ({uc.name})")
    return {"ok": True}
