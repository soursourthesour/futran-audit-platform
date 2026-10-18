from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, build_actor, current_actor, current_session
from app.auth.models import AuthSession, MfaSecret
from app.auth.service import LOCKED, MFA_FAILURES, TooManyAttempts, authenticate, confirmed_mfa, pending_mfa, recent_mfa_failures
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
    portal: str | None = None  # staff | client (spec v0.3 screens 1 and 9b)


class TermsIn(BaseModel):
    accepted: bool = False


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
    from app.tenancy.models import Organization

    side = "staff" if db.get(Organization, user.organization_id).type == "futran" else "client"
    if body.portal in ("staff", "client") and body.portal != side:
        audit.record(db, actor_id=user.id, action="auth.wrong_portal", obj=user, request=request, summary=f"Tried the {body.portal} sign-in")
        db.commit()
        raise Unauthorized("This is the Futran staff sign-in. Client users sign in on the client sign-in page." if side == "client"
                           else "This is the client sign-in. Futran staff use the staff sign-in page.")
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
    uri = provisioning_uri(actor.user.email, secret)
    return {"otpauth_uri": uri, "secret": secret, "qr_svg": _qr_svg(uri)}


def _qr_svg(data: str) -> str:
    import io

    import segno

    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=5, border=2, xmldecl=False, svgns=True, dark="#16233A")
    return buf.getvalue().decode()


@router.post("/mfa/verify")
def mfa_verify(body: CodeIn, request: Request, response: Response, s: AuthSession = Depends(current_session), db: Session = Depends(get_db)):
    settings: Settings = request.app.state.settings
    actor = build_actor(db, s, request)
    if recent_mfa_failures(db, actor.id) >= MFA_FAILURES:
        revoke(db, s)
        db.commit()
        raise TooManyAttempts(LOCKED)
    from app.auth.recovery import issue_codes, use_code

    if use_code(db, s.user_id, body.code):
        s.mfa_passed = True
        audit.record(db, actor_id=actor.id, action="auth.recovery_code_used", obj=actor.user, request=request, summary="Signed in with a recovery code")
        return {"ok": True}
    rec = confirmed_mfa(db, s.user_id) or pending_mfa(db, s.user_id)
    step = None
    if rec is not None:
        step = verify_totp(decrypt_secret(rec.secret_encrypted, settings.secret_key), body.code, rec.last_used_step)
    if step is None:
        audit.record(db, actor_id=actor.id, action="auth.mfa_failed", obj=actor.user, request=request)
        db.flush()
        if recent_mfa_failures(db, actor.id) >= MFA_FAILURES:
            revoke(db, s)
            response.delete_cookie(COOKIE_NAME, path="/")
            db.commit()
            raise TooManyAttempts(LOCKED)
        db.commit()
        raise Unauthorized("That code is not valid. Check the time on your phone and try the newest code.")
    rec.last_used_step = step
    s.mfa_passed = True
    if rec.confirmed_at is None:
        rec.confirmed_at = utcnow()
        actor.user.mfa_enabled = True
        audit.record(db, actor_id=actor.id, action="auth.mfa_enrolled", obj=actor.user, request=request)
        return {"ok": True, "recovery_codes": issue_codes(db, actor.user)}
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
        "terms_required": terms_required(actor),
    }


def terms_required(actor: Actor) -> bool:
    return not actor.is_futran and actor.user.terms_accepted_at is None


@router.post("/terms")
def accept_terms(body: TermsIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Screen 9a, last step: the client user accepts the terms and that their actions are recorded in the audit log."""
    from app.core.errors import Invalid

    if not body.accepted:
        raise Invalid(errors=[{"field": "accepted", "message": "Tick the box to accept the terms."}])
    if actor.user.terms_accepted_at is None:
        actor.user.terms_accepted_at = utcnow()
        audit.record(db, actor_id=actor.id, action="auth.terms_accepted", obj=actor.user, request=request, summary="Accepted the terms of use and audit-log notice")
    return {"ok": True}
