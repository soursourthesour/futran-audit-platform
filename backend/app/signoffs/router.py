from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.signoffs.models import SignOff
from app.signoffs.service import sign, sign_off_out

router = APIRouter(prefix="/signoffs", tags=["sign-offs"])


class SignIn(BaseModel):
    typed_name: str


def _load(db: Session, actor: Actor, so_id: str) -> SignOff:
    so = db.get(SignOff, so_id)
    if so is None or so.deleted_at:
        raise NotFound()
    authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=so.engagement_id)
    return so


@router.get("/{so_id}")
def get_sign_off(so_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return sign_off_out(db, actor, _load(db, actor, so_id))


@router.post("/{so_id}/sign")
def post_sign(so_id: str, body: SignIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    so = _load(db, actor, so_id)
    sign(db, request.app.state.settings, actor, so, body.typed_name, request)
    return sign_off_out(db, actor, so)


# ---- client review (stage 4): sign-offs 2–4
from app.signoffs import client_review  # noqa: E402,F401  registers preconditions and the snapshot lock
from app.signoffs.service import correct, current, return_signoff, submit_signoff  # noqa: E402


class SubmitIn(BaseModel):
    scope_ref: str | None = None


class CommentIn(BaseModel):
    comment: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


def _client_engagement(db: Session, actor: Actor, client_id: str):
    from app.tenancy.models import Organization
    from app.tenancy.people import current_engagement

    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=e.id)
    return org, e


client_router = APIRouter(tags=["sign-offs"])


@client_router.post("/clients/{client_id}/signoffs/{number}/submit")
def submit(client_id: str, number: int, body: SubmitIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org, e = _client_engagement(db, actor, client_id)
    statement = client_review.representation_text(db, e) if number == 4 else None
    so = submit_signoff(db, request.app.state.settings, actor, e, number, body.scope_ref, statement=statement)
    return sign_off_out(db, actor, so)


@router.post("/{so_id}/return")
def post_return(so_id: str, body: CommentIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    so = _load(db, actor, so_id)
    return sign_off_out(db, actor, return_signoff(db, request.app.state.settings, actor, so, body.comment))


@router.post("/{so_id}/correct")
def post_correct(so_id: str, body: ReasonIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    so = _load(db, actor, so_id)
    return sign_off_out(db, actor, correct(db, request.app.state.settings, actor, so, body.reason))


@client_router.get("/clients/{client_id}/review")
def review(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Screen 15: the client's inventory review — sign-off 2 per department, 3, 4 and the snapshot."""
    from app.inventory.snapshot import current_snapshot
    from app.signoffs.service import SIGNOFF_SPECS, _can_prepare

    org, e = _client_engagement(db, actor, client_id)

    def block(number: int, scope=None, unmet=None):
        so = current(db, e, number, scope)
        return {"sign_off": sign_off_out(db, actor, so) if so else None, "unmet": unmet if unmet is not None else [],
                "can_submit": (so is None or so.status == "returned") and _can_prepare(actor, SIGNOFF_SPECS[number], scope) and not (unmet or []),
                "can_correct": so is not None and so.status == "approved" and _can_prepare(actor, SIGNOFF_SPECS[number], scope)}

    depts = [{"id": d.id, "name": d.name, **block(2, d.id, client_review.department_unmet(db, e, d.id))} for d in client_review.in_scope_departments(db, e)]
    snap = current_snapshot(db, e)
    return {
        "client": org.name, "audit_ref": e.audit_ref, "stage": e.stage,
        "departments": depts, "signoff3": block(3, None, client_review.signoff3_unmet(db, e)), "signoff4": block(4, None, client_review.signoff4_unmet(db, e)),
        "representation": client_review.representation_text(db, e),
        "snapshot": {"version": snap.version, "locked_at": snap.locked_at.isoformat(), "use_cases": len(snap.payload.get("use_cases", []))} if snap else None,
    }
