from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.audit_log.models import AuditLog
from app.auth.models import LoginAttempt, MfaSecret
from app.auth.passwords import hash_password, verify_password
from app.core.clock import utcnow
from app.core.errors import AppError, Unauthorized
from app.tenancy.models import User
from app.core.ratelimit import client_ip_or_none

LOCKOUT_FAILURES = 10
LOCKOUT_WINDOW = timedelta(minutes=15)
MFA_FAILURES = 5
BAD_LOGIN = "Email or password is incorrect."
LOCKED = "Too many unsuccessful attempts. Try again in 15 minutes or ask an administrator to reset your password."
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


class TooManyAttempts(AppError):
    status_code = 429


def find_login_user(db: Session, email: str) -> User | None:
    return db.scalar(
        select(User).where(func.lower(User.email) == email.strip().lower(), User.deleted_at.is_(None))
    )


def _ip(request) -> str | None:
    return client_ip_or_none(request) if request is not None else None


def recent_login_failures(db: Session, email: str, ip: str | None) -> int:
    since = utcnow() - LOCKOUT_WINDOW
    stmt = select(func.count()).select_from(LoginAttempt).where(LoginAttempt.email == email, LoginAttempt.at >= since)
    stmt = stmt.where(LoginAttempt.ip == ip) if ip else stmt.where(LoginAttempt.ip.is_(None))
    return db.scalar(stmt) or 0


def authenticate(db: Session, email: str, password: str, request=None) -> User:
    """Same work and the same answers whether or not the email has an account."""
    email = email.strip().lower()
    ip = _ip(request)
    if recent_login_failures(db, email, ip) >= LOCKOUT_FAILURES:
        raise TooManyAttempts(LOCKED)
    user = find_login_user(db, email)
    usable = user is not None and user.status == "active" and bool(user.password_hash)
    ok = verify_password(user.password_hash if usable else _DUMMY_HASH, password) and usable
    if not ok:
        db.add(LoginAttempt(email=email, ip=ip))
        if user is not None:
            audit.record(db, actor_id=user.id, action="auth.login_failed", obj=user, request=request, summary="Unsuccessful sign-in")
        db.commit()
        raise Unauthorized(BAD_LOGIN)
    return user


def recent_mfa_failures(db: Session, user_id: str) -> int:
    since = utcnow() - LOCKOUT_WINDOW
    return db.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.object_id == user_id, AuditLog.action == "auth.mfa_failed", AuditLog.at >= since
        )
    ) or 0


def confirmed_mfa(db: Session, user_id: str) -> MfaSecret | None:
    return db.scalar(
        select(MfaSecret).where(MfaSecret.user_id == user_id, MfaSecret.confirmed_at.is_not(None)).order_by(MfaSecret.created_at.desc())
    )


def pending_mfa(db: Session, user_id: str) -> MfaSecret | None:
    return db.scalar(
        select(MfaSecret).where(MfaSecret.user_id == user_id, MfaSecret.confirmed_at.is_(None)).order_by(MfaSecret.created_at.desc())
    )
