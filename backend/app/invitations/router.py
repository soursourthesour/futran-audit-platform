from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.router import set_session_cookie
from app.auth.sessions import create_session
from app.core.db import get_db
from app.invitations.service import accept_invitation, find_invitation, invitation_state
from app.tenancy.models import Organization, User

router = APIRouter(prefix="/invitations", tags=["invitations"])


class AcceptIn(BaseModel):
    password: str


@router.get("/accept/{token}")
def invitation_info(token: str, db: Session = Depends(get_db, scope="function")):
    inv = find_invitation(db, token)
    state = invitation_state(inv)
    if state["used"] or state["expired"]:
        return state
    user = db.get(User, inv.user_id)
    org = db.get(Organization, user.organization_id)
    from app.policy.roles import ROLE_LABELS
    from app.tenancy.service import roles_of

    roles = list(dict.fromkeys(ROLE_LABELS.get(r.role, r.role) for r in roles_of(db, user.id)))
    return {"email": user.email, "name": user.name, "job_title": user.job_title, "organization_name": org.name, "roles": roles, **state}


@router.post("/decline/{token}")
def decline(token: str, request: Request, db: Session = Depends(get_db, scope="function")):
    """"Not you?": the person who received the email cancels the invitation, and whoever sent it is told."""
    from app.invitations.service import decline_invitation

    decline_invitation(db, request.app.state.settings, token)
    return {"declined": True}


@router.post("/accept/{token}")
def accept(token: str, body: AcceptIn, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    settings = request.app.state.settings
    user = accept_invitation(db, settings, token, body.password)
    s, raw = create_session(db, user, settings, request, mfa_passed=not settings.mfa_required)
    set_session_cookie(response, raw, settings)
    return {"csrf_token": s.csrf_token, "mfa_required": settings.mfa_required}
