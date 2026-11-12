"""SM-13 Won — hand off to delivery (`/sales/opportunities/:id/handoff`). Sales roles and the Chief Auditor."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.commercial import handoff as svc
from app.commercial.access import futran_only, may
from app.core.db import get_db
from app.core.errors import NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization, User

router = APIRouter(tags=["handoff"])


class ConfirmIn(BaseModel):
    account_owner_id: str | None = None


class IndependenceIn(BaseModel):
    separate_team_user_ids: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=1000)


def _load(db: Session, actor: Actor, opp_id: str, action: Action):
    futran_only(actor)
    authorize(db, actor, action)
    h = svc.for_opportunity(db, opp_id)
    if h is None:
        raise NotFound("No accepted proposal has been handed off for this opportunity yet.")
    return h


def _out(db: Session, actor: Actor, h) -> dict:
    staff = db.scalars(select(User).join(Organization, Organization.id == User.organization_id)
                       .where(Organization.type == "futran", User.deleted_at.is_(None), User.status != "disabled").order_by(User.name))
    return svc.handoff_out(db, h) | {
        "can_confirm": may(db, actor, Action.CONFIRM_HANDOFF) and h.status != "confirmed",
        "can_confirm_independence": may(db, actor, Action.CONFIRM_INDEPENDENCE) and bool(h.needs_separate_team),
        "can_view_plan": may(db, actor, Action.VIEW_CLIENT_PLAN, org_id=h.organization_id),
        "staff": [{"id": u.id, "name": u.name} for u in staff],
    }


@router.get("/sales/opportunities/{opp_id}/handoff")
def get_handoff(opp_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _out(db, actor, _load(db, actor, opp_id, Action.VIEW_HANDOFF))


@router.post("/sales/opportunities/{opp_id}/handoff/confirm")
def confirm(opp_id: str, body: ConfirmIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    h = _load(db, actor, opp_id, Action.CONFIRM_HANDOFF)
    svc.confirm(db, actor.user, h, body.account_owner_id)
    return _out(db, actor, h)


@router.post("/sales/opportunities/{opp_id}/handoff/independence")
def independence(opp_id: str, body: IndependenceIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    h = _load(db, actor, opp_id, Action.CONFIRM_INDEPENDENCE)
    svc.confirm_independence(db, actor.user, h, body.separate_team_user_ids, body.note)
    return _out(db, actor, h)
