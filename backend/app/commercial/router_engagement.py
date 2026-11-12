"""G-02 Engagement commercials (`/e/:id/commercial`) and change orders. Fee, value and price fields are checked
server-side: only people holding `view_engagement_fees` ever receive them (never Auditors). The client's CAICO approves
change orders at `/change-orders` in the client app."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.commercial import commercials as svc
from app.commercial.access import engagement_for, may
from app.commercial.models import ChangeOrder
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(tags=["engagement commercials"])


class MilestoneIn(BaseModel):
    label: str = Field(max_length=120)
    trigger: str = "manual"
    pct: float
    reached_on: str | None = None


class CommercialIn(BaseModel):
    fee_total: float | None = None
    milestones: list[MilestoneIn] | None = None


class ChangeOrderIn(BaseModel):
    code: str = Field(max_length=12)
    qty: float = 1
    reason: str = Field(max_length=2000)
    unit_price: float | None = None


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=1000)


def _fees(db: Session, actor: Actor, e: Engagement) -> bool:
    return may(db, actor, Action.VIEW_ENGAGEMENT_FEES, engagement_id=e.id)


def _view(db: Session, actor: Actor, e: Engagement) -> dict:
    return svc.commercial_view(db, e) | {
        "can_edit": may(db, actor, Action.EDIT_ENGAGEMENT_COMMERCIAL, engagement_id=e.id),
        "can_raise": may(db, actor, Action.RAISE_CHANGE_ORDER, engagement_id=e.id),
        "can_approve_price": may(db, actor, Action.APPROVE_CHANGE_ORDER_PRICE, engagement_id=e.id),
        "can_manager_approve": svc.is_managed(db, e, actor.user) or actor.has_role("chief_auditor"),
        "me": actor.id,
    }


@router.get("/e/{engagement_id}/commercial")
def get_commercial(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _view(db, actor, engagement_for(db, actor, Action.VIEW_ENGAGEMENT_FEES, engagement_id))


@router.put("/e/{engagement_id}/commercial")
def put_commercial(engagement_id: str, body: CommercialIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = engagement_for(db, actor, Action.EDIT_ENGAGEMENT_COMMERCIAL, engagement_id)
    data = body.model_dump(exclude_unset=True)
    if body.milestones is not None:
        data["milestones"] = [m.model_dump() for m in body.milestones]
    svc.update_commercial(db, actor.user, e, data)
    return _view(db, actor, e)


@router.get("/e/{engagement_id}/change-orders")
def list_change_orders(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = engagement_for(db, actor, Action.RAISE_CHANGE_ORDER, engagement_id)
    prices = _fees(db, actor, e)
    return [svc.change_order_out(db, co, with_prices=prices) for co in svc.change_orders_for(db, e)]


@router.post("/e/{engagement_id}/change-orders")
def raise_change_order(engagement_id: str, body: ChangeOrderIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = engagement_for(db, actor, Action.RAISE_CHANGE_ORDER, engagement_id)
    prices = _fees(db, actor, e)
    co = svc.raise_change_order(db, actor.user, e, code=body.code.strip(), qty=body.qty, reason=body.reason, unit_price=body.unit_price, can_price=prices)
    return svc.change_order_out(db, co, with_prices=prices)


def _co(db: Session, co_id: str) -> ChangeOrder:
    co = db.get(ChangeOrder, co_id)
    if co is None or co.deleted_at is not None:
        raise NotFound()
    return co


@router.post("/change-orders/{co_id}/manager-approve")
def manager_approve(co_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    co = _co(db, co_id)
    e = engagement_for(db, actor, Action.RAISE_CHANGE_ORDER, co.engagement_id)
    svc.manager_approve(db, actor.user, co)
    return svc.change_order_out(db, co, with_prices=_fees(db, actor, e))


@router.post("/change-orders/{co_id}/price-decision")
def price_decision(co_id: str, body: DecisionIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    co = _co(db, co_id)
    engagement_for(db, actor, Action.APPROVE_CHANGE_ORDER_PRICE, co.engagement_id)
    svc.price_decision(db, actor.user, co, body.approve, body.note)
    return svc.change_order_out(db, co, with_prices=True)


# ---- the client's CAICO
def _client(db: Session, actor: Actor) -> str:
    if actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.APPROVE_CHANGE_ORDER, org_id=actor.organization.id)
    return actor.organization.id


@router.get("/change-orders")
def client_change_orders(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org_id = _client(db, actor)
    rows = db.scalars(select(ChangeOrder).where(ChangeOrder.organization_id == org_id, ChangeOrder.deleted_at.is_(None),
                                                ChangeOrder.status.in_(("awaiting_client", "approved", "rejected"))).order_by(ChangeOrder.created_at.desc()))
    out = []
    for co in rows:
        if co.status == "rejected" and co.client_approved_by is None:
            continue  # returned inside Futran; the client never saw it
        e = db.get(Engagement, co.engagement_id)
        out.append(svc.change_order_out(db, co, with_prices=True, for_client=True) | {"engagement_name": e.name if e else "", "audit_ref": e.audit_ref if e else None})
    return out


@router.post("/change-orders/{co_id}/decide")
def client_decide(co_id: str, body: DecisionIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org_id = _client(db, actor)
    co = _co(db, co_id)
    if co.organization_id != org_id:
        raise NotFound()
    if not actor.has_role("caico"):
        raise Forbidden()
    svc.client_decision(db, request.app.state.settings, actor.user, co, body.approve, body.note)
    return svc.change_order_out(db, co, with_prices=True, for_client=True)
