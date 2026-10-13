from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.clock import utcnow
from app.core.ids import new_id


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampedTenantMixin(IdMixin):
    """Columns every tenant-owned table carries (spec §9)."""

    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def column_snapshot(obj) -> dict:
    """JSON-able dict of an ORM object's column values (for the audit log)."""
    out = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.key, None)
        if isinstance(val, datetime):
            val = val.isoformat()
        elif hasattr(val, "isoformat"):
            val = val.isoformat()
        out[col.key] = val
    for secret in ("password_hash", "token_hash", "secret_encrypted"):
        if secret in out:
            out[secret] = "***"
    return out
