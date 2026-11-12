"""G-08 EU AI Act conformity: one record per register system (spec B8). organization_id is the client.

The record holds the system's EU exposure, role and classification with its reasoning, the legal sign-off (who and
when, by the Legal/Compliance Reviewer only), and the obligations checklist, Annex IV tracker and FRIA as JSON keyed
by the data file's keys (`seeds/eu_ai_act.yaml`). Applicable articles and the deadline are computed, never stored."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

SIGNOFF_STATUSES = ("draft", "awaiting_signoff", "signed_off", "returned")
OBLIGATION_STATUSES = ("not_started", "not_met", "partly_met", "met", "not_applicable")
SECTION_STATUSES = ("not_started", "in_progress", "done")


class EuAiActRecord(TimestampedTenantMixin, Base):
    __tablename__ = "euaiact_records"
    __table_args__ = (UniqueConstraint("register_system_id", name="uq_euaiact_record_system"),)

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)  # where it was last worked
    exposure_basis: Mapped[str | None] = mapped_column(String(300))  # "EU customers", "EU staff", ...
    role: Mapped[str | None] = mapped_column(String(24))  # provider | deployer | importer | distributor | product_manufacturer
    also_deployer: Mapped[bool] = mapped_column(Boolean, default=False)  # a provider that also uses it
    classification: Mapped[str | None] = mapped_column(String(24))  # prohibited | high_risk_annex_iii | high_risk_annex_i | transparency | minimal | gpai
    annex_iii_area: Mapped[str | None] = mapped_column(String(40))
    public_service: Mapped[bool] = mapped_column(Boolean, default=False)  # a public body or provider of public services (Art. 27(1))
    reasoning: Mapped[str | None] = mapped_column(Text)
    legal_review_flag: Mapped[bool] = mapped_column(Boolean, default=True)
    classified_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    classified_at: Mapped[datetime | None] = mapped_column(DateTime)
    signoff_status: Mapped[str] = mapped_column(String(20), default="draft")
    sent_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    signed_off_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime)
    signoff_note: Mapped[str | None] = mapped_column(Text)
    signed_snapshot: Mapped[dict | None] = mapped_column(JSON)  # role and classification as signed
    obligations: Mapped[dict | None] = mapped_column(JSON)  # {key: {status, note, evidence_ids, by, at}}
    annex_iv: Mapped[dict | None] = mapped_column(JSON)  # {section: {status, note, by, at}}
    fria: Mapped[dict | None] = mapped_column(JSON)  # {"answers": {key: text}, "status": not_started|in_progress|done, "by", "at"}
