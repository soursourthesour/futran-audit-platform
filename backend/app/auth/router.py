from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, build_actor, current_actor, current_session
from app.auth.models import AuthSession, MfaSecret
from app.auth.service import authenticate, confirmed_mfa, pending_mfa
from app.auth.sessions import COOKIE_NAME, create_session, revoke
from app.auth.totp import decrypt_secret, encrypt_secret, new_secret, provisioning_uri, verify_totp
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import Conflict, Unauthorized

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class CodeIn(BaseModel):
    code: str


def set_session_cookie(response: Response, raw: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        raw,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        max_age=settings.session_max_hours * 3600,
        path="/",
    )


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    settings: Settings = request.app.state.settings
    user = authenticate(db, body.email, body.password, request)
    enrolled = confirmed_mfa(db, user.id) is not None
    s, raw = create_session(db, user, settings, request, mfa_passed=not settings.mfa_required)
    audit.record(db, actor_id=user.id, action="auth.login", obj=user, request=request, summary="Signed in")
    set_session_cookie(response, raw, settings)
    return {"mfa_required": settings.mfa_required, "mfa_enrolled": enrolled, "csrf_token": s.csrf_token}


@router.get("/session")
def session_state(request: Request, db: Session = Depends(get_db)):
    """Pre-MFA view of the session, so the sign-in screens know what to show."""
    from app.auth.sessions import load_session

    settings: Settings = request.app.state.settings
    s = load_session(db, request.cookies.get(COOKIE_NAME), settings)
    if s is None:
        return {"authenticated": False, "test_mode": settings.test_mode}
    return {
        "authenticated": True,
        "mfa_pending": settings.mfa_required and not s.mfa_passed,
        "mfa_enrolled": confirmed_mfa(db, s.user_id) is not None,
        "csrf_token": s.csrf_token,
        "test_mode": settings.test_mode,
    }


@router.post("/mfa/enroll")
def mfa_enroll(request: Request, s: AuthSession = Depends(current_session), db: Session = Depends(get_db)):
    settings: Settings = request.app.state.settings
    if confirmed_mfa(db, s.user_id):
        raise Conflict("An authenticator app is already set up for this account. Ask an administrator to reset it.")
    actor = build_actor(db, s, request)
    secret = new_secret()
    db.add(MfaSecret(user_id=s.user_id, organization_id=s.organization_id, secret_encrypted=encrypt_secret(secret, settings.secret_key)))
    return {"otpauth_uri": provisioning_uri(actor.user.email, secret), "secret": secret}


@router.post("/mfa/verify")
def mfa_verify(body: CodeIn, request: Request, s: AuthSession = Depends(current_session), db: Session = Depends(get_db)):
    settings: Settings = request.app.state.settings
    rec = confirmed_mfa(db, s.user_id) or pending_mfa(db, s.user_id)
    if rec is None or not verify_totp(decrypt_secret(rec.secret_encrypted, settings.secret_key), body.code):
        actor = build_actor(db, s, request)
        audit.record(db, actor_id=actor.id, action="auth.mfa_failed", obj=actor.user, request=request)
        db.commit()
        raise Unauthorized("That code is not valid. Check the time on your phone and try the newest code.")
    if rec.confirmed_at is None:
        rec.confirmed_at = utcnow()
        actor = build_actor(db, s, request)
        actor.user.mfa_enabled = True
        audit.record(db, actor_id=actor.id, action="auth.mfa_enrolled", obj=actor.user, request=request)
    s.mfa_passed = True
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, s: AuthSession = Depends(current_session), db: Session = Depends(get_db)):
    revoke(db, s)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, actor: Actor = Depends(current_actor)):
    settings: Settings = request.app.state.settings
    u, o = actor.user, actor.organization
    return {
        "user": {"id": u.id, "name": u.name, "email": u.email, "job_title": u.job_title, "mfa_enabled": u.mfa_enabled},
        "organization": {"id": o.id, "name": o.name, "type": o.type, "client_ref": o.client_ref},
        "roles": [{"role": r.role, "scope_type": r.scope_type, "scope_id": r.scope_id} for r in actor.roles],
        "test_mode": settings.test_mode,
        "mfa_required": settings.mfa_required,
        "email_mode": settings.email_mode,
        "csrf_token": actor.session.csrf_token if actor.session else None,
    }
