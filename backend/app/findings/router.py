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
def create(client_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    assert_not_admin_judgment(actor)
    e = _engagement(db, actor, client_id, Action.RECORD_FINDINGS)
    return svc.finding_out(db, svc.create_finding(db, actor.user, e, data))


@router.patch("/findings/{finding_id}")
def patch(finding_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    assert_not_admin_judgment(actor)
    f = _finding(db, actor, finding_id, Action.RECORD_FINDINGS)
    return svc.finding_out(db, svc.update_finding(db, actor.user, f, data))


from pydantic import BaseModel  # noqa: E402
from fastapi import Request  # noqa: E402


class CommentIn(BaseModel):
    comment: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


@router.post("/findings/{finding_id}/submit")
def submit(finding_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    assert_not_admin_judgment(actor)
    f = _finding(db, actor, finding_id, Action.RECORD_FINDINGS)
    return svc.finding_out(db, svc.submit(db, request.app.state.settings, actor.user, f))


@router.post("/findings/{finding_id}/approve")
def approve(finding_id: str, body: CommentIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    assert_not_admin_judgment(actor)
    f = _finding(db, actor, finding_id, Action.APPROVE_FINDINGS)
    return svc.finding_out(db, svc.approve(db, actor.user, f, body.comment))


@router.post("/findings/{finding_id}/return")
def return_finding(finding_id: str, body: CommentIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    assert_not_admin_judgment(actor)
    f = _finding(db, actor, finding_id, Action.APPROVE_FINDINGS)
    return svc.finding_out(db, svc.return_(db, request.app.state.settings, actor.user, f, body.comment))


@router.post("/findings/{finding_id}/dismiss")
def dismiss(finding_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    assert_not_admin_judgment(actor)
    f = _finding(db, actor, finding_id, Action.RECORD_FINDINGS)
    svc.dismiss(db, actor.user, f, body.reason)
    return {"dismissed": True}


CLIENT_STAGE = 7  # findings reach the client with the draft report (stage 6 → 7)


@router.get("/clients/{client_id}/findings")
def list_findings(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Futran sees every finding. The client sees approved findings only, from the draft report on (spec §6 rule 5)."""
    from app.core.errors import Forbidden
    from app.inventory.fieldwork import control_options
    from app.signoffs.service import current

    e = _engagement(db, actor, client_id, Action.VIEW_FINDINGS_RESPONSES if not actor.is_futran else Action.VIEW_ENGAGEMENT)
    if not actor.is_futran:
        if e.stage < CLIENT_STAGE:
            raise Forbidden("Findings are shared with the draft report.")
        rows = [f for f in svc.findings_for(db, e) if f.status == "approved"]
        return {"findings": [svc.finding_out(db, f, viewer_is_futran=False) for f in rows]}
    rows = svc.findings_for(db, e)
    so5 = current(db, e, 5)
    from app.signoffs.service import sign_off_out

    return {"findings": [svc.finding_out(db, f) for f in rows], "stage": e.stage, "audit_ref": e.audit_ref, "client": db.get(Organization, client_id).name,
            "control_options": control_options(db, e), "sign_off_5": sign_off_out(db, actor, so5) if so5 else None,
            "approved": sum(f.status == "approved" for f in rows), "total": len(rows),
            "can_approve_as": [r for r in ("chief_auditor", "qa_reviewer") if actor.id in {u.id for u in svc.team_role_holders(db, e, r)}], "me": actor.id}
