"""Regulatory change alerts (spec §21 F4, screen 26).

`RegulatoryUpdate` holds what the law library does not: enforcement actions, guidance, pending bills, court rulings and
dated events entered by Futran's Legal Reviewer (the spec's "FRD analyst") and published only after a second reviewer.
Approved law-library changes (`ProposedChange`) appear beside them read-only. A change to a law's facts goes to M3 as a
`ProposedChange`, so the law library stays the single source; client emails go through the A1 approval queue.

`RegulatoryAlert` is one published update matched to one client: which register systems it touches and why.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin

CHANGE_TYPES = ("new_law", "amendment", "effective_date", "enforcement_action", "guidance", "court_ruling", "pending_bill")
STATUSES = ("draft", "awaiting_review", "published", "withdrawn")
FEATURES = ("consequential_decisions_admt", "employment_hiring", "privacy_profiling", "health_insurance", "chatbots_minors", "synthetic_content",
            "frontier_safety", "biometrics_pricing", "government_other")  # spec §10.2


class RegulatoryUpdate(IdMixin, Base):
    __tablename__ = "regulatory_updates"

    reference: Mapped[str] = mapped_column(String(12), index=True)  # RU-001
    change_type: Mapped[str] = mapped_column(String(20))
    jurisdiction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
    regulation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("regulations.id"), index=True)
    law_name: Mapped[str | None] = mapped_column(String(200))  # as shown; for a bill or rule the library does not hold
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    todo_text: Mapped[str | None] = mapped_column(Text)  # what a client should do, one item per line
    effective_on: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(600))
    source_name: Mapped[str | None] = mapped_column(String(200))
    source_quote: Mapped[str | None] = mapped_column(Text)
    affected_features: Mapped[list] = mapped_column(JSON, default=list)
    watch: Mapped[bool] = mapped_column(Boolean, default=False)  # watch item: no client action, not matched to clients
    verify_note: Mapped[str | None] = mapped_column(String(600))  # what is not yet confirmed
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    submitted_by: Mapped[str | None] = mapped_column(String(36))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(String(1000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    withdrawn_by: Mapped[str | None] = mapped_column(String(36))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)
    withdrawn_reason: Mapped[str | None] = mapped_column(String(1000))
    proposed_change_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("proposed_changes.id"))


class RegulatoryAlert(TimestampedTenantMixin, Base):
    __tablename__ = "regulatory_alerts"
    __table_args__ = (UniqueConstraint("update_id", "organization_id", name="uq_regulatory_alert_update_org"),)

    update_id: Mapped[str] = mapped_column(String(36), ForeignKey("regulatory_updates.id"), index=True)
    affected_system_ids: Mapped[list] = mapped_column(JSON, default=list)
    match_reason: Mapped[str | None] = mapped_column(String(600))
    alert_send_id: Mapped[str | None] = mapped_column(String(36))  # A1 AlertSend
    opportunity_id: Mapped[str | None] = mapped_column(String(36))  # S1 Opportunity
    digested_at: Mapped[datetime | None] = mapped_column(DateTime)


class UpdateDigestSetting(TimestampedTenantMixin, Base):
    """The weekly digest to a client's Chief AI Compliance Officers. Off until the Chief Auditor turns it on."""

    __tablename__ = "update_digest_settings"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_update_digest_setting_org"),)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class UpdateDigestRun(IdMixin, Base):
    """One weekly digest for one client. The unique key is the claim: a second scheduler run for the same week finds it
    taken and sends nothing."""

    __tablename__ = "update_digest_runs"
    __table_args__ = (UniqueConstraint("organization_id", "week_start", name="uq_update_digest_week"),)

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="sending")  # sending | sent | nothing_new | no_recipients
    update_ids: Mapped[list] = mapped_column(JSON, default=list)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    outbox_message_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
