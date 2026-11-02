"""Screen 31, Continuous monitoring (spec §21 F3): the client's dashboard (tenant from the session), Futran's view on the
client page, and the plan the Futran Admin sets. Every endpoint calls `authorize`."""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor, get_settings_dep
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Forbidden, NotFound
from app.monitoring import service as mon
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization

router = APIRouter(tags=["monitoring"])


class PlanIn(BaseModel):
    plan: str
    next_review_on: date | None = None
    note: str | None = None


def _may(db: Session, actor: Actor, action: Action, org_id: str) -> bool:
    try:
        authorize(db, actor, action, org_id=org_id)
        return True
    except (Forbidden, NotFound):
        return False


def _client_org(db: Session, actor: Actor, action: Action) -> Organization:
    if actor.is_futran:
        raise Forbidden("This screen is for the client's own people. Futran reads it from the client page.")
    authorize(db, actor, action, org_id=actor.organization.id)
    return actor.organization


@router.get("/monitoring")
def dashboard(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client_org(db, actor, Action.VIEW_MONITORING)
    return mon.dashboard(db, org) | {"can_act": _may(db, actor, Action.ACT_ON_MONITORING, org.id), "can_set_plan": False}


@router.post("/monitoring/run")
def run_now(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client_org(db, actor, Action.ACT_ON_MONITORING)
    if not mon.is_monitored(org):
        raise Conflict("Checks run for clients on the Monitor plan. Ask your Futran contact about it.")
    r = mon.run(db, settings, org, "manual", f"manual:{utcnow():%Y%m%d%H%M%S%f}", actor=actor.user)
    if r is None:
        raise Conflict("A run has just started. Refresh in a moment.")
    return {"id": r.id, "counts": r.counts}


@router.post("/monitoring/results/{result_id}/act")
def act(result_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client_org(db, actor, Action.ACT_ON_MONITORING)
    try:
        return mon.act(db, settings, actor.user, org, result_id)
    except ValueError as exc:
        raise Conflict(str(exc)) from exc


def _futran_client(db: Session, actor: Actor, client_id: str, action: Action) -> Organization:
    if not actor.is_futran:
        raise NotFound()
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, action, org_id=org.id)
    return org


@router.get("/clients/{client_id}/monitoring")
def futran_dashboard(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _futran_client(db, actor, client_id, Action.VIEW_MONITORING)
    return mon.dashboard(db, org) | {"can_act": False, "can_set_plan": _may(db, actor, Action.MANAGE_SUBSCRIPTION, org.id)}


@router.put("/clients/{client_id}/subscription")
def set_plan(client_id: str, body: PlanIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _futran_client(db, actor, client_id, Action.MANAGE_SUBSCRIPTION)
    mon.set_plan(db, actor.user, org, body.plan, next_review_on=body.next_review_on, note=body.note)
    return mon.dashboard(db, org) | {"can_act": False, "can_set_plan": True}
