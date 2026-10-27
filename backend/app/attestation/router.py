from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attestation import service as att
from app.auth.deps import Actor, current_actor, get_settings_dep
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.core.ratelimit import client_ip, limiter
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.tenancy.models import Department, Organization
from app.tenancy.people import current_engagement

router = APIRouter(tags=["attestation"])


class IdsIn(BaseModel):
    ids: list[str] = []


class RemoveIn(IdsIn):
    reason: str = ""


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
    out = att.tracker(db, actor, c, dept_scope=scope, individuals=individuals)
    out["permissions"] = {"send": _may(db, actor, Action.SEND_ATTESTATION, e.id), "manage": _may(db, actor, Action.MANAGE_ATTESTATION_ANSWERS, e.id)}
    return out


def _may(db: Session, actor: Actor, action: Action, engagement_id: str) -> bool:
    try:
        authorize(db, actor, action, engagement_id=engagement_id)
        return True
    except (Forbidden, NotFound):
        return False


def _campaign(db: Session, e: Engagement):
    c = att.current_campaign(db, e)
    if c is None:
        raise NotFound("No attestation campaign has been launched yet.")
    return c


# ---- in-app line items (Client Admin and CAICO send; every client user completes their own)
@router.post("/clients/{client_id}/attestation/send")
def send(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    e = _engagement(db, actor, client_id, Action.SEND_ATTESTATION)
    return att.send_in_app(db, settings, actor.user, _campaign(db, e))


@router.get("/clients/{client_id}/attestation/in-app")
def in_app(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """For the Client Admin, who sends the line items but does not see answers: the campaign and counts only."""
    e = _engagement(db, actor, client_id, Action.SEND_ATTESTATION)
    c = att.current_campaign(db, e)
    if c is None:
        return {"campaign": None}
    return {"campaign": {"status": "open" if att.is_open(c) else "closed", "closes_at": c.closes_at.isoformat(), "launched_at": c.launched_at.isoformat(), "policy_version": c.policy_version},
            **att.in_app_status(db, c, names=False)}


def _own_engagement(db: Session, actor: Actor) -> Engagement | None:
    authorize(db, actor, Action.COMPLETE_OWN_ATTESTATION, org_id=actor.organization.id)
    e = current_engagement(db, actor.organization)
    if e is not None:
        authorize(db, actor, Action.COMPLETE_OWN_ATTESTATION, engagement_id=e.id)
    return e


@router.get("/me/attestation")
def my_attestation(actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    return att.my_attestation(db, settings, actor.user, _own_engagement(db, actor))


@router.post("/me/attestation")
def submit_my_attestation(payload: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    a = att.submit_own(db, settings, actor.user, _own_engagement(db, actor), payload)
    return {"received": True, "submitted_at": a.submitted_at.isoformat()}


# ---- individual answers
@router.get("/clients/{client_id}/attestation/answers/{answer_id}")
def get_answer(client_id: str, answer_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.VIEW_INDIVIDUAL_ATTESTATIONS)
    c = _campaign(db, e)
    r = att.answer(db, c, answer_id)
    from app.audit_log import service as audit

    audit.record(db, actor_id=actor.id, action="attestation.view_individual", obj=r, summary="Viewed one attestation answer in full")
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == c.organization_id))}
    return att.individual_row(r, depts, att._user_names(db, {r.reviewed_by, r.edited_by}))


@router.patch("/clients/{client_id}/attestation/answers/{answer_id}")
def patch_answer(client_id: str, answer_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.MANAGE_ATTESTATION_ANSWERS)
    c = _campaign(db, e)
    r = att.edit(db, actor.user, c, att.answer(db, c, answer_id), data)
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == c.organization_id))}
    return att.individual_row(r, depts, att._user_names(db, {r.reviewed_by, r.edited_by}))


@router.post("/clients/{client_id}/attestation/answers/review")
def review_answers(client_id: str, body: IdsIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.MANAGE_ATTESTATION_ANSWERS)
    return {"reviewed": att.mark_reviewed(db, actor.user, _campaign(db, e), body.ids)}


@router.post("/clients/{client_id}/attestation/answers/remove")
def remove_answers(client_id: str, body: RemoveIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.MANAGE_ATTESTATION_ANSWERS)
    return {"removed": att.remove(db, actor.user, _campaign(db, e), body.ids, body.reason)}


@router.post("/clients/{client_id}/attestation/answers/export")
def export_answers(client_id: str, body: IdsIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.VIEW_INDIVIDUAL_ATTESTATIONS)
    csv = att.export_csv(db, actor.user, _campaign(db, e), body.ids)
    return Response(csv, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="attestation_answers.csv"'})


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
    limiter(request, "attest", 30).check(f"{token}:{client_ip(request)}")
    att.submit(db, token, payload, request)
    return {"received": True}
