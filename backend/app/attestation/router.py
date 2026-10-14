from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.attestation import service as att
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.core.ratelimit import limiter
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.tenancy.models import Organization
from app.tenancy.people import current_engagement

router = APIRouter(tags=["attestation"])


class LaunchIn(BaseModel):
    department_ids: list[str]
    closes_at: datetime
    policy_version: str = "1.0"


def _engagement(db: Session, actor: Actor, client_id: str, action: Action, list_view: bool = False) -> Engagement:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=e.id, list_view=list_view)
    return e


@router.post("/clients/{client_id}/attestation/campaigns")
def launch(client_id: str, body: LaunchIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.LAUNCH_ATTESTATION)
    c = att.launch(db, actor.user, e, body.department_ids, body.closes_at, body.policy_version)
    return {"id": c.id, "status": "open", "link": f"/attest/{c.link_token}", "closes_at": c.closes_at.isoformat()}


@router.get("/clients/{client_id}/attestation")
def get_tracker(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.VIEW_ATTESTATION_AGGREGATES, list_view=True)
    c = att.current_campaign(db, e)
    if c is None:
        raise NotFound("No attestation campaign has been launched yet.")
    try:
        authorize(db, actor, Action.VIEW_INDIVIDUAL_ATTESTATIONS, engagement_id=e.id)
        individuals = True
    except (Forbidden, NotFound):
        individuals = False
    scope = None if actor.is_futran or individuals else departments_for(actor, Action.VIEW_ATTESTATION_AGGREGATES)
    return att.tracker(db, actor, c, dept_scope=scope, individuals=individuals)


@router.post("/clients/{client_id}/attestation/close")
def close(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.LAUNCH_ATTESTATION)
    c = att.current_campaign(db, e)
    if c is None:
        raise NotFound()
    att.close(db, actor.user, c)
    from app.engagements.gates import advance_if_ready

    if e.stage == 3:
        advance_if_ready(db, actor.user, e)
    return {"status": "closed"}


# ---- public, no sign-in (schematic D13): one shared link for all staff in scope
@router.get("/public/attest/{token}")
def public_get(token: str, db: Session = Depends(get_db)):
    return att.public_view(db, att.by_token(db, token))


@router.post("/public/attest/{token}")
def public_post(token: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    limiter(request, "attest", 30).check(request.client.host if request.client else "unknown")
    att.submit(db, token, payload, request)
    return {"received": True}
