from datetime import datetime

from sqlalchemy import JSON, DateTime, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin


class AuditLog(IdMixin, Base):
    """Append-only record of every create, edit, approval, send and sensitive view (spec §6 rule 10)."""

    __tablename__ = "audit_log"

    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_name: Mapped[str | None] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(80), index=True)
    object_type: Mapped[str] = mapped_column(String(60), index=True)
    object_id: Mapped[str | None] = mapped_column(String(36), index=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    summary: Mapped[str | None] = mapped_column(String(500))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


@event.listens_for(AuditLog, "before_update")
def _no_update(*_):
    raise PermissionError("The audit log is append-only.")


@event.listens_for(AuditLog, "before_delete")
def _no_delete(*_):
    raise PermissionError("The audit log is append-only.")
