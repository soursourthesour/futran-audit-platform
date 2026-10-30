"""Chief Auditor refresh alerts (spec §27.9, M6)."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin

SCOPES = ("law_refresh", "litigation_refresh")
KINDS = ("refresh_done", "review_reminder", "escalation")


class StaffAlert(IdMixin, Base):
    __tablename__ = "staff_alerts"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    scope: Mapped[str] = mapped_column(String(20), default="law_refresh")
    refresh_run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("refresh_runs.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    is_copy: Mapped[bool] = mapped_column(Boolean, default=False)  # sent as a copy (QA Reviewer, Admin)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    email_send_id: Mapped[str | None] = mapped_column(String(36))


class AlertSetting(IdMixin, Base):
    __tablename__ = "staff_alert_settings"

    scope: Mapped[str] = mapped_column(String(20), unique=True)
    recipients_rule: Mapped[str] = mapped_column(String(20), default="all_chief_auditors")  # all_chief_auditors | runner
    cc_roles: Mapped[list] = mapped_column(JSON, default=lambda: ["qa_reviewer"])
    when_rule: Mapped[str] = mapped_column(String(12), default="every")  # every | changes | high_impact
    channels: Mapped[list] = mapped_column(JSON, default=lambda: ["in_app", "email"])
    remind_after_days: Mapped[int | None] = mapped_column(Integer, default=3)
    escalate_after_days: Mapped[int | None] = mapped_column(Integer, default=7)
    escalate_to_roles: Mapped[list] = mapped_column(JSON, default=lambda: ["chief_auditor", "admin"])
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
