"""G-03 Time and hours (`/staff/time`): every Futran person's weekly timesheet, approvals, hours banks and retainers,
standard cost per hour (Futran Admin) and margin by engagement (Chief Auditor, Sales Manager)."""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.commercial import timesheet as svc
from app.commercial.access import futran_only, may
from app.commercial.models import Retainer
from app.core.db import get_db
from app.core.errors import NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(tags=["time and hours"])


class WeekIn(BaseModel):
    rows: list[dict] = Field(default_factory=list, max_length=60)


class DecideIn(BaseModel):
    user_id: str
    approve: bool
    note: str | None = Field(default=None, max_length=1000)


class ActivateIn(BaseModel):
    reason: str = Field(max_length=2000)


class CostIn(BaseModel):
    role: str = Field(max_length=40)
    cost_per_hour: float
    effective_from: date


def _check(db: Session, actor: Actor, action: Action) -> None:
    futran_only(actor)
    authorize(db, actor, action)


def _fees_for(db: Session, actor: Actor):
    cache: dict[str, bool] = {}

    def fees(org_id: str) -> bool:
        if org_id not in cache:
            cache[org_id] = may(db, actor, Action.VIEW_ENGAGEMENT_FEES, org_id=org_id)
        return cache[org_id]

    return fees


def _week(db: Session, actor: Actor, view: dict) -> dict:
    return view | {"can_approve": may(db, actor, Action.APPROVE_TIME), "can_view_margins": may(db, actor, Action.VIEW_MARGINS),
                   "can_manage_costs": may(db, actor, Action.MANAGE_STANDARD_COST), "can_manage_retainers": may(db, actor, Action.MANAGE_RETAINERS),
                   "can_approve_incidents": may(db, actor, Action.APPROVE_ENGAGEMENT)}


@router.get("/staff/time/{week}")
def get_week(week: date, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _check(db, actor, Action.LOG_TIME)
    return _week(db, actor, svc.week_view(db, actor.user, week, fees_for=_fees_for(db, actor)))


@router.put("/staff/time/{week}")
def put_week(week: date, body: WeekIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _check(db, actor, Action.LOG_TIME)
    return _week(db, actor, svc.save_week(db, actor.user, week, body.rows, fees_for=_fees_for(db, actor)))


@router.post("/staff/time/{week}/submit")
def submit_week(week: date, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _check(db, actor, Action.LOG_TIME)
    return _week(db, actor, svc.submit_week(db, actor.user, week, fees_for=_fees_for(db, actor)))


@router.get("/staff/time-approvals")
def approvals(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    futran_only(actor)
    authorize(db, actor, Action.APPROVE_TIME, list_view=True)
    return svc.approvals(db, actor.user)


@router.post("/staff/time/{week}/decide")
def decide_week(week: date, body: DecideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    futran_only(actor)
    authorize(db, actor, Action.APPROVE_TIME, list_view=True)
    return {"decided": svc.decide_week(db, actor.user, body.user_id, week, body.approve, body.note)}


@router.get("/staff/hours-banks")
def banks(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _check(db, actor, Action.VIEW_HOURS_BANKS)
    return _banks(db, actor)


def _banks(db: Session, actor: Actor) -> dict:
    """Everyone with fee rights at every client (sales roles, Admin, Chief Auditor) sees every bank; others see the banks of
    clients they are assigned to, without rates."""
    from app.commercial.access import holds_all

    clients = None if holds_all(actor, Action.VIEW_ENGAGEMENT_FEES) else svc.assigned_clients(db, actor.user)
    return svc.banks_view(db, clients=clients, fees_for=_fees_for(db, actor))


@router.post("/staff/retainers/{retainer_id}/activate")
def activate(retainer_id: str, body: ActivateIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    futran_only(actor)
    r = db.get(Retainer, retainer_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    if may(db, actor, Action.MANAGE_RETAINERS):
        authorize(db, actor, Action.MANAGE_RETAINERS)
    else:
        authorize(db, actor, Action.MANAGE_RETAINERS, org_id=r.organization_id)
    svc.activate_retainer(db, actor.user, r, body.reason)
    return _banks(db, actor)


@router.post("/staff/retainers/{retainer_id}/approve-incident")
def approve_incident(retainer_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    futran_only(actor)
    r = db.get(Retainer, retainer_id)
    if r is None or r.deleted_at is not None or not r.incident_engagement_id:
        raise NotFound()
    authorize(db, actor, Action.APPROVE_ENGAGEMENT, engagement_id=r.incident_engagement_id)
    svc.approve_incident(db, actor.user, r)
    return _banks(db, actor)


@router.get("/staff/margins")
def margins(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _check(db, actor, Action.VIEW_MARGINS)
    return svc.margins(db)


@router.get("/staff/standard-costs")
def costs(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    futran_only(actor)
    if not (may(db, actor, Action.MANAGE_STANDARD_COST) or may(db, actor, Action.VIEW_MARGINS)):
        authorize(db, actor, Action.MANAGE_STANDARD_COST)
    return [{"role": c.role, "cost_per_hour": c.cost_per_hour, "effective_from": c.effective_from.isoformat()} for c in svc.standard_costs(db)]


@router.post("/staff/standard-costs")
def set_cost(body: CostIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _check(db, actor, Action.MANAGE_STANDARD_COST)
    svc.set_standard_cost(db, actor.user, body.role, body.cost_per_hour, body.effective_from)
    return [{"role": c.role, "cost_per_hour": c.cost_per_hour, "effective_from": c.effective_from.isoformat()} for c in svc.standard_costs(db)]
