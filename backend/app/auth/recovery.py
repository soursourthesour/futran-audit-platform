"""MFA recovery codes (spec v0.3 screen 9a): ten single-use codes shown once at enrolment."""
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import MfaRecoveryCode
from app.core.clock import utcnow
from app.tenancy.models import User

COUNT = 10


def _hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def issue_codes(db: Session, user: User) -> list[str]:
    """Replace any earlier codes with ten new ones. Only hashes are stored."""
    for old in db.scalars(select(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None))):
        old.used_at = utcnow()
    codes = []
    for _ in range(COUNT):
        raw = secrets.token_hex(5)
        code = f"{raw[:5]}-{raw[5:]}"
        db.add(MfaRecoveryCode(user_id=user.id, organization_id=user.organization_id, code_hash=_hash(code)))
        codes.append(code)
    db.flush()
    return codes


def use_code(db: Session, user_id: str, code: str) -> bool:
    if not code or len(code.replace("-", "").strip()) != 10:
        return False
    row = db.scalar(select(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id, MfaRecoveryCode.code_hash == _hash(code), MfaRecoveryCode.used_at.is_(None)))
    if row is None:
        return False
    row.used_at = utcnow()
    return True
