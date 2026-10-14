"""AI governance structure request (spec §9.4, §10.5, screen 10a). organization_id is the client."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class GovernanceRequest(TimestampedTenantMixin, Base):
    __tablename__ = "governance_requests"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    requested_by: Mapped[str | None] = mapped_column(String(36))
    due_date: Mapped[date | None] = mapped_column(Date)
    items_selected: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | submitted | accepted
    submitted_by: Mapped[str | None] = mapped_column(String(36))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    accuracy_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    extra_fields: Mapped[dict | None] = mapped_column(JSON)  # template §4.1–4.2 engagement-level answers


class GovernanceItem(TimestampedTenantMixin, Base):
    """One requested document or role. Spec §9.4's GovernanceDocumentItem and GovernanceRoleItem share this table;
    `kind` says which, and the role-only fields stay empty for documents."""

    __tablename__ = "governance_items"

    request_id: Mapped[str] = mapped_column(String(36), ForeignKey("governance_requests.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    catalog_code: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(20))  # document | security_document | role
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000))
    control_refs: Mapped[list] = mapped_column(JSON, default=list)
    committee: Mapped[bool] = mapped_column(Boolean, default=False)
    optional: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="unanswered")  # unanswered | in_place | planned | not_applicable
    file_ids: Mapped[list] = mapped_column(JSON, default=list)
    names: Mapped[list] = mapped_column(JSON, default=list)  # [{name, title}]
    chair: Mapped[str | None] = mapped_column(String(120))
    member_count: Mapped[int | None] = mapped_column(Integer)
    meeting_frequency: Mapped[str | None] = mapped_column(String(40))
    terms_of_reference_file_id: Mapped[str | None] = mapped_column(String(36))
    target_date: Mapped[date | None] = mapped_column(Date)
    interim_owner: Mapped[str | None] = mapped_column(String(120))
    planned_members: Mapped[str | None] = mapped_column(Text)
    na_reason: Mapped[str | None] = mapped_column(Text)
    answered_by: Mapped[str | None] = mapped_column(String(36))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)


class Commitment(TimestampedTenantMixin, Base):
    """A client promise to create a document or constitute a role by a date. Tracked like a remediation item."""

    __tablename__ = "commitments"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    source: Mapped[str] = mapped_column(String(24))  # governance_document | governance_role
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    description: Mapped[str] = mapped_column(String(300))
    target_date: Mapped[date] = mapped_column(Date)
    owner: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="open")  # open | in_progress | awaiting_verification | closed | reopened
