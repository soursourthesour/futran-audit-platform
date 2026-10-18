"""Screens 19–20: management responses (client) and the remediation tracker (both sides)."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement
from app.findings.models import Finding
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.policy.sod import assert_not_admin_judgment
from app.remediation import register  # noqa: F401  sign-off 6, report section, digest
from app.remediation import service as svc
from app.remediation.models import ManagementResponse, RemediationItem
from app.tenancy.models import Organization, User
from app.tenancy.people import current_engagement

router = APIRouter(tags=["remediation"])


def _engagement(db: Session, actor: Actor, client_id: str, action: Action, list_view: bool = False) -> Engagement:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=e.id, list_view=list_view)
    return e


def _visible(db: Session, actor: Actor, dept_id: str | None, owner_id: str | None = None) -> bool:
    if actor.is_futran:
        return True
    depts = departments_for(actor, Action.VIEW_FINDINGS_RESPONSES)
    return depts is None or (dept_id is not None and dept_id in depts) or (owner_id is not None and owner_id == actor.id)


@router.get("/clients/{client_id}/responses")
def list_responses(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Every approved finding with its response; the client sees the findings in its scope from the draft report on."""
    from app.signoffs.service import SIGNOFF_SPECS, _can_prepare, current, sign_off_out

    e = _engagement(db, actor, client_id, Action.VIEW_FINDINGS_RESPONSES, list_view=True)
    if not actor.is_futran and e.stage < 7:
        raise Forbidden("Findings are shared with the draft report.")
    rows = []
    for f in svc.approved_findings(db, e):
        dept = svc.finding_department(db, f)
        if not _visible(db, actor, dept):
            continue
        out = svc.response_out(db, f, svc.response_for(db, f))
        if actor.is_futran:
            out["can_review"] = out["id"] is not None and e.stage == 7 and _can(db, actor, Action.VERIFY_REMEDIATION, e)
        else:
            out["can_respond"] = _can(db, actor, Action.RESPOND_FINDINGS, e, dept)
        rows.append(out)
    so6 = current(db, e, 6)
    people = [{"id": u.id, "name": u.name} for u in db.query(User).filter(User.organization_id == e.client_id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name)] if not actor.is_futran else []
    unmet = svc.signoff6_unmet(db, e)
    return {
        "audit_ref": e.audit_ref, "client": db.get(Organization, e.client_id).name, "stage": e.stage, "responses": rows, "people": people,
        "answered": sum(r["id"] is not None for r in rows), "total": len(rows),
        "sign_off_6": sign_off_out(db, actor, so6) if so6 else None, "unmet": unmet,
        "can_submit": not unmet and (so6 is None or so6.status == "returned") and _can_prepare(actor, SIGNOFF_SPECS[6], None),
        "draft_report": _draft(db, e),
    }


def _draft(db: Session, e: Engagement) -> dict | None:
    from app.reports.service import latest

    r = latest(db, e, "v1.0", released=True)
    return {"pdf_file_id": r.pdf_file_id, "docx_file_id": r.docx_file_id, "released_at": r.released_to_client_at.isoformat()} if r else None


def _can(db: Session, actor: Actor, action: Action, e: Engagement, dept: str | None = None) -> bool:
    try:
        authorize(db, actor, action, engagement_id=e.id, department_id=dept)
        return True
    except Forbidden:
        return False


@router.put("/findings/{finding_id}/response")
def put_response(finding_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    f = db.get(Finding, finding_id)
    if f is None or f.deleted_at is not None:
        raise NotFound()
    if actor.is_futran:
        raise Forbidden("Management responses are written by the client.")
    authorize(db, actor, Action.RESPOND_FINDINGS, engagement_id=f.engagement_id, department_id=svc.finding_department(db, f))
    r = svc.respond(db, actor, f, data)
    return svc.response_out(db, f, r)


class AdequacyIn(BaseModel):
    adequate: bool | None = None
    note: str | None = None


@router.post("/responses/{response_id}/adequacy")
def adequacy(response_id: str, body: AdequacyIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    r = db.get(ManagementResponse, response_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.VERIFY_REMEDIATION, engagement_id=r.engagement_id)
    svc.adequacy_review(db, request.app.state.settings, actor.user, r, body.adequate, body.note)
    return svc.response_out(db, db.get(Finding, r.finding_id), r)


@router.get("/clients/{client_id}/remediation")
def list_items(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.VIEW_FINDINGS_RESPONSES, list_view=True)
    if not actor.is_futran and e.stage < 7:
        raise Forbidden("Remediation starts with the draft report.")
    rows = []
    for item in svc.items_for(db, e):
        if not _visible(db, actor, svc.item_department(db, item), item.owner_user_id):
            continue
        out = svc.item_out(db, item)
        out["can_act"] = svc.client_can_act(actor, db, item)
        out["can_verify"] = actor.is_futran and item.status == "awaiting_verification" and not item.verified_by and _can(db, actor, Action.VERIFY_REMEDIATION, e)
        out["can_close"] = actor.is_futran and item.status == "awaiting_verification" and bool(item.verified_by) and item.verified_by != actor.id and _can(db, actor, Action.CLOSE_REMEDIATION, e)
        out["can_reopen"] = actor.is_futran and item.status in ("awaiting_verification", "closed") and e.status != "completed" and (_can(db, actor, Action.VERIFY_REMEDIATION, e) or _can(db, actor, Action.CLOSE_REMEDIATION, e))
        rows.append(out)
    counts = {s: sum(r["status"] == s for r in rows) for s in svc.STATUS_LABEL}
    return {"audit_ref": e.audit_ref, "client": db.get(Organization, e.client_id).name, "stage": e.stage, "status": e.status, "items": rows, "counts": counts}


def _item(db: Session, actor: Actor, item_id: str, action: Action) -> RemediationItem:
    item = db.get(RemediationItem, item_id)
    if item is None or item.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=item.engagement_id, list_view=not actor.is_futran)
    return item


class NoteIn(BaseModel):
    note: str | None = None


@router.post("/remediation/{item_id}/start")
def start(item_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    item = _item(db, actor, item_id, Action.VIEW_FINDINGS_RESPONSES)
    return svc.item_out(db, svc.start(db, actor, item))


@router.post("/remediation/{item_id}/done")
def done(item_id: str, body: NoteIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    item = _item(db, actor, item_id, Action.VIEW_FINDINGS_RESPONSES)
    return svc.item_out(db, svc.mark_done(db, request.app.state.settings, actor, item, body.note))


@router.post("/remediation/{item_id}/verify")
def verify(item_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    item = _item(db, actor, item_id, Action.VERIFY_REMEDIATION)
    return svc.item_out(db, svc.verify(db, actor.user, item, body.note))


@router.post("/remediation/{item_id}/close")
def close(item_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    item = _item(db, actor, item_id, Action.CLOSE_REMEDIATION)
    return svc.item_out(db, svc.close(db, actor.user, item))


@router.post("/remediation/{item_id}/reopen")
def reopen(item_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    if not actor.is_futran:
        raise Forbidden("Futran reopens remediation items.")
    item = db.get(RemediationItem, item_id)
    if item is None or item.deleted_at is not None:
        raise NotFound()
    try:
        authorize(db, actor, Action.VERIFY_REMEDIATION, engagement_id=item.engagement_id)
    except Forbidden:
        authorize(db, actor, Action.CLOSE_REMEDIATION, engagement_id=item.engagement_id)
    return svc.item_out(db, svc.reopen(db, actor.user, item, body.note))
