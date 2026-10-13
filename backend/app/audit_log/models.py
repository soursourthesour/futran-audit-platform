from datetime import datetime

from sqlalchemy import DDL, JSON, DateTime, String, event
from sqlalchemy.orm import Session
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


@event.listens_for(Session, "do_orm_execute")
def _no_bulk_changes(state):
    if state.is_update or state.is_delete:
        table = getattr(state.statement, "table", None)
        if table is not None and getattr(table, "name", None) == AuditLog.__tablename__:
            raise PermissionError("The audit log is append-only.")


# Database-level guard, for anything that bypasses the ORM.
SQLITE_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END",
]
POSTGRES_TRIGGERS = [
    "CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'audit log is append-only'; END; $$ LANGUAGE plpgsql",
    "DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log",
    "CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()",
]
for _sql in SQLITE_TRIGGERS:
    event.listen(AuditLog.__table__, "after_create", DDL(_sql).execute_if(dialect="sqlite"))
for _sql in POSTGRES_TRIGGERS:
    event.listen(AuditLog.__table__, "after_create", DDL(_sql).execute_if(dialect="postgresql"))
