from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.engagements.models import Engagement
from app.findings import service as svc
from app.findings.models import Finding
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.policy.sod import assert_not_admin_judgment
from app.tenancy.models import Organization
from app.tenancy.people import current_engagement

router = APIRouter(tags=["findings"])


def _engagement(db: Session, actor: Actor, client_id: str, action: Action) -> Engagement:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=e.id)
    return e


def _finding(db: Session, actor: Actor, finding_id: str, action: Action) -> Finding:
    f = db.get(Finding, finding_id)
    if f is None or f.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=f.engagement_id)
    return f


@router.post("/clients/{client_id}/findings")
def create(client_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    e = _engagement(db, actor, client_id, Action.RECORD_FINDINGS)
    return svc.finding_out(db, svc.create_finding(db, actor.user, e, data))


@router.patch("/findings/{finding_id}")
def patch(finding_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    f = _finding(db, actor, finding_id, Action.RECORD_FINDINGS)
    return svc.finding_out(db, svc.update_finding(db, actor.user, f, data))
