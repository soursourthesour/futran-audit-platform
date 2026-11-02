"""Policy builder (spec §21 F7). PolicyTemplate is Futran's library (not tenant-owned); PolicyDocument and
PolicyAcknowledgment belong to the client (organization_id is the client)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin

POLICY_STATUSES = ("draft", "awaiting_approval", "published", "retired")


class PolicyTemplate(IdMixin, Base):
    """One version of a Futran template, recorded the first time it is loaded. A document keeps the version it was built from."""

    __tablename__ = "policy_templates"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_policy_template_version"),)

    code: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(String(500))
    catalog_codes: Mapped[list] = mapped_column(JSON, default=list)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    body: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PolicyDocument(TimestampedTenantMixin, Base):
    __tablename__ = "policy_documents"

    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("policy_templates.id"))
    template_code: Mapped[str] = mapped_column(String(40), index=True)
    template_version: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(200))
    commitment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("commitments.id"), index=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    blocks: Mapped[list] = mapped_column(JSON, default=list)  # headings, paragraphs and lists only
    edited: Mapped[bool] = mapped_column(Boolean, default=False)  # the text was changed by hand since it was last generated
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("policy_documents.id"))
    submitted_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    return_note: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_months: Mapped[int | None] = mapped_column(Integer)
    review_due: Mapped[date | None] = mapped_column(Date)
    published_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime)
    # "Request Futran review" (S1) and the independence rule (§21 F7, §21.1)
    futran_review_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    futran_review_note: Mapped[str | None] = mapped_column(Text)
    futran_opportunity_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("opportunities.id"))
    authored_by_futran_team: Mapped[list] = mapped_column(JSON, default=list)  # Futran user ids who wrote or tailored it
    futran_team_recorded_by: Mapped[str | None] = mapped_column(String(36))
    futran_team_recorded_at: Mapped[datetime | None] = mapped_column(DateTime)


class PolicyAcknowledgment(TimestampedTenantMixin, Base):
    """One employee's acknowledgment of one published policy version, through their personal link."""

    __tablename__ = "policy_acknowledgments"
    __table_args__ = (UniqueConstraint("policy_id", "email", name="uq_policy_ack_email"),)

    policy_id: Mapped[str] = mapped_column(String(36), ForeignKey("policy_documents.id"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    name: Mapped[str | None] = mapped_column(String(160))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"))
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(8), default="link")
    recipient_id: Mapped[str | None] = mapped_column(String(36))
