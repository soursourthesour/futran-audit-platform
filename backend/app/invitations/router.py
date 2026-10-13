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
def invitation_info(token: str, db: Session = Depends(get_db)):
    inv = find_invitation(db, token)
    state = invitation_state(inv)
    if state["used"] or state["expired"]:
        return state
    user = db.get(User, inv.user_id)
    org = db.get(Organization, user.organization_id)
    return {"email": user.email, "name": user.name, "organization_name": org.name, **state}


@router.post("/accept/{token}")
def accept(token: str, body: AcceptIn, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    user = accept_invitation(db, settings, token, body.password)
    s, raw = create_session(db, user, settings, request, mfa_passed=not settings.mfa_required)
    set_session_cookie(response, raw, settings)
    return {"csrf_token": s.csrf_token, "mfa_required": settings.mfa_required}
