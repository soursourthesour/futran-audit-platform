"""Management responses and remediation items (spec §9.6). organization_id is the client."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

RESPONSES = {"agree": "Agree", "partially_agree": "Partially agree", "disagree": "Disagree"}
ITEM_STATUSES = ("open", "in_progress", "awaiting_verification", "closed", "reopened")


class ManagementResponse(TimestampedTenantMixin, Base):
    """The client's answer to one approved finding. Futran reviews it for adequacy before sign-off 6."""

    __tablename__ = "management_responses"
    __table_args__ = (UniqueConstraint("finding_id", name="uq_response_finding"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    finding_id: Mapped[str] = mapped_column(String(36), ForeignKey("findings.id"))
    response: Mapped[str] = mapped_column(String(16))  # agree | partially_agree | disagree
    planned_action: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="answered")  # answered | adequate | inadequate
    responded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime)
    adequate: Mapped[bool | None] = mapped_column(Boolean)
    adequacy_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)


class RemediationItem(TimestampedTenantMixin, Base):
    """One action to track to closure: from a management response or from a governance commitment."""

    __tablename__ = "remediation_items"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    finding_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("findings.id"), index=True)
    response_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("management_responses.id"), unique=True)
    commitment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("commitments.id"), unique=True)
    action: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    owner_name: Mapped[str | None] = mapped_column(String(160))  # commitments name an owner who may have no account
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(24), default="open")
    done_note: Mapped[str | None] = mapped_column(Text)
    marked_done_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    marked_done_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verification_note: Mapped[str | None] = mapped_column(Text)
    closed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    reopen_note: Mapped[str | None] = mapped_column(Text)
