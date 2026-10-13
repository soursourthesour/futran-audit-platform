from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.audit_log.models import AuditLog
from app.auth.models import MfaSecret
from app.auth.passwords import verify_password
from app.core.clock import utcnow
from app.core.errors import AppError, Unauthorized
from app.tenancy.models import User

LOCKOUT_FAILURES = 10
LOCKOUT_WINDOW = timedelta(minutes=15)
BAD_LOGIN = "Email or password is incorrect."


class TooManyAttempts(AppError):
    status_code = 429


def find_login_user(db: Session, email: str) -> User | None:
    return db.scalar(
        select(User).where(func.lower(User.email) == email.strip().lower(), User.deleted_at.is_(None))
    )


def recent_failures(db: Session, user: User) -> int:
    since = utcnow() - LOCKOUT_WINDOW
    return db.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.object_id == user.id, AuditLog.action == "auth.login_failed", AuditLog.at >= since
        )
    ) or 0


def authenticate(db: Session, email: str, password: str, request=None) -> User:
    user = find_login_user(db, email)
    if user is None:
        raise Unauthorized(BAD_LOGIN)
    if recent_failures(db, user) >= LOCKOUT_FAILURES:
        raise TooManyAttempts("Too many unsuccessful attempts. Try again in 15 minutes or ask an administrator to reset your password.")
    if user.status != "active" or not verify_password(user.password_hash, password):
        audit.record(db, actor_id=user.id, action="auth.login_failed", obj=user, request=request, summary="Unsuccessful sign-in")
        db.commit()
        raise Unauthorized(BAD_LOGIN)
    return user


def confirmed_mfa(db: Session, user_id: str) -> MfaSecret | None:
    return db.scalar(
        select(MfaSecret).where(MfaSecret.user_id == user_id, MfaSecret.confirmed_at.is_not(None)).order_by(MfaSecret.created_at.desc())
    )


def pending_mfa(db: Session, user_id: str) -> MfaSecret | None:
    return db.scalar(
        select(MfaSecret).where(MfaSecret.user_id == user_id, MfaSecret.confirmed_at.is_(None)).order_by(MfaSecret.created_at.desc())
    )
