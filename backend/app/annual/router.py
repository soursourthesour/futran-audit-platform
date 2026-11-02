"""Annual review carry-forward (spec §21 F16): start, confirm or update carried answers, and the year-over-year view."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.annual import service as svc
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.questionnaire.models import Response
from app.systems.models import AISystem

router = APIRouter(tags=["annual review"])
CLIENT_SCORE_STAGE = 7  # as the scoring screens: clients see scores from the draft report on


class ScopeIn(BaseModel):
    system_id: str | None = None


def _engagement(db: Session, engagement_id: str) -> Engagement:
    e = db.get(Engagement, engagement_id)
    if e is None or e.deleted_at is not None:
        raise NotFound()
    return e


def _client_systems(db: Session, actor: Actor, e: Engagement) -> set[str] | None:
    """The systems a department-scoped client role may confirm; None = all."""
    depts = departments_for(actor, Action.CONFIRM_CARRIED_ANSWERS)
    if depts is None:
        return None
    return {s.id for s in db.query(AISystem).filter(AISystem.engagement_id == e.id, AISystem.department_id.in_(depts or {""}))}


@router.post("/engagements/{engagement_id}/annual-review")
def start(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    prior = _engagement(db, engagement_id)
    authorize(db, actor, Action.START_ANNUAL_REVIEW, engagement_id=prior.id)
    e = svc.start_annual_review(db, actor.user, prior)
    return {"engagement_id": e.id, "client_id": e.client_id, "audit_ref": e.audit_ref, "status": e.status}


@router.get("/engagements/{engagement_id}/carried")
def carried(engagement_id: str, changed: bool = False, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _engagement(db, engagement_id)
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=e.id)
        return svc.carried_items(db, e, changed_only=changed)
    authorize(db, actor, Action.CONFIRM_CARRIED_ANSWERS, engagement_id=e.id, list_view=True)
    return svc.carried_items(db, e, system_ids=_client_systems(db, actor, e), changed_only=changed, client=True)


@router.post("/responses/{response_id}/confirm-carried")
def confirm(response_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    r = db.get(Response, response_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    s = db.get(AISystem, r.ai_system_id) if r.ai_system_id else None
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=r.engagement_id)
        raise Forbidden("The client confirms its own carried-forward answers.")
    authorize(db, actor, Action.CONFIRM_CARRIED_ANSWERS, engagement_id=r.engagement_id, department_id=s.department_id if s else None, list_view=s is None)
    return svc.confirm(db, actor.user, r)


@router.post("/engagements/{engagement_id}/carried/confirm-unchanged")
def confirm_unchanged(engagement_id: str, body: ScopeIn | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _engagement(db, engagement_id)
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=e.id)
        raise Forbidden("The client confirms its own carried-forward answers.")
    authorize(db, actor, Action.CONFIRM_CARRIED_ANSWERS, engagement_id=e.id, list_view=True)
    allowed = _client_systems(db, actor, e)
    if body is not None and body.system_id:
        allowed = {body.system_id} if allowed is None or body.system_id in allowed else set()
    return {"confirmed": svc.confirm_unchanged(db, actor.user, e, allowed)}


@router.get("/engagements/{engagement_id}/year-over-year")
def yoy(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _engagement(db, engagement_id)
    authorize(db, actor, Action.VIEW_SCORES, engagement_id=e.id)
    if not actor.is_futran and e.stage < CLIENT_SCORE_STAGE:
        raise Forbidden("Risk scores are shared with the draft report.")
    out = svc.year_over_year(db, e)
    if out is None:
        raise NotFound("This engagement does not carry forward an earlier one.")
    return out
