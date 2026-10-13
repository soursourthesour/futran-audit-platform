import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AuthSession
from app.core.clock import utcnow
from app.core.config import Settings
from app.tenancy.models import User

COOKIE_NAME = "fap_session"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session(db: Session, user: User, settings: Settings, request=None, mfa_passed: bool = False) -> tuple[AuthSession, str]:
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    s = AuthSession(
        user_id=user.id,
        organization_id=user.organization_id,
        token_hash=hash_token(raw),
        csrf_token=secrets.token_urlsafe(24),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_max_hours),
        mfa_passed=mfa_passed,
        ip=(request.client.host if request is not None and request.client else None),
        user_agent=((request.headers.get("user-agent") or "")[:300] if request is not None else None),
    )
    db.add(s)
    db.flush()
    return s, raw


def load_session(db: Session, raw: str | None, settings: Settings, touch: bool = True) -> AuthSession | None:
    if not raw:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(raw)))
    if s is None or s.revoked_at is not None:
        return None
    now = utcnow()
    if now >= s.expires_at or now - s.last_seen_at > timedelta(minutes=settings.session_idle_min):
        s.revoked_at = now
        return None
    if touch:
        s.last_seen_at = now
    return s


def revoke(db: Session, s: AuthSession) -> None:
    s.revoked_at = utcnow()
