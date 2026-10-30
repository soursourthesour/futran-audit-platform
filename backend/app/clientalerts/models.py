"""Automatic client alerts (spec §27.6, §27.7). Rules are Futran-wide; each send is for one client."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin

TRIGGERS = ("law_change", "new_law", "effective_date", "case", "tracing_addon")
APPROVALS = ("chief_auditor", "automatic", "sales_owner")


class AlertRule(IdMixin, Base):
    __tablename__ = "alert_rules"

    trigger: Mapped[str] = mapped_column(String(20), index=True)
    audience_rule: Mapped[str] = mapped_column(String(30))  # law_applies | geography | similar_ai | untraced_systems
    client_groups: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["AIComplianceTeam", "DeptHeads"]
    template_key: Mapped[str] = mapped_column(String(80), default="client_alert")
    template_id: Mapped[str | None] = mapped_column(String(36))  # an email template (E3/E4) when one is chosen
    email_label: Mapped[str] = mapped_column(String(160))
    approval: Mapped[str] = mapped_column(String(14), default="chief_auditor")
    days_before: Mapped[list] = mapped_column(JSON, default=list)  # effective_date only: [90, 30]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sent_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AlertSend(IdMixin, Base):
    __tablename__ = "alert_sends"
    __table_args__ = (UniqueConstraint("alert_rule_id", "organization_id", "change_ref", name="uq_alert_send_once"),)

    alert_rule_id: Mapped[str] = mapped_column(String(36), ForeignKey("alert_rules.id"), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    change_ref: Mapped[str] = mapped_column(String(120))  # change:<id> | case:<id>:v<n> | date:<law_version_id>:<days> | addon:<id>
    headline: Mapped[str] = mapped_column(String(300))  # what changed, one line
    subject: Mapped[str | None] = mapped_column(String(300))  # edited subject; null = generated
    intro: Mapped[str | None] = mapped_column(Text)
    affected_system_ids: Mapped[list] = mapped_column(JSON, default=list)
    todo_items: Mapped[list] = mapped_column(JSON, default=list)  # [{code, text, deadline, law}]
    deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(18), default="waiting_approval", index=True)  # waiting_approval | sent | held
    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))  # Sales owner for add-on alerts
    mail_send_id: Mapped[str | None] = mapped_column(String(36))  # MailSend (group email, E4/E5)
    outbox_message_id: Mapped[str | None] = mapped_column(String(36))  # direct email when the client group has no one in it
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_from: Mapped[str | None] = mapped_column(String(300))
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36))
