"""Findings (spec §9.6, §18.6). Task 23 creates auto-drafted findings; the findings workflow extends this model."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

SEVERITIES = ("critical", "high", "medium", "low", "observation")


class Finding(TimestampedTenantMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("engagement_id", "ref", name="uq_findings_engagement_ref"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    ref: Mapped[str] = mapped_column(String(10))  # F-001 per engagement, never reused
    ai_system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_systems.id"), index=True)
    use_case_ids: Mapped[list] = mapped_column(JSON, default=list)
    template_section: Mapped[str | None] = mapped_column(String(8))
    source_question_ids: Mapped[list] = mapped_column(JSON, default=list)  # question codes
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(12))
    control_refs: Mapped[list] = mapped_column(JSON, default=list)
    recommended_remediation: Mapped[str | None] = mapped_column(Text)
    proposed_owner: Mapped[str | None] = mapped_column(String(160))
    author_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft | submitted | approved | returned
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    null_compliance_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    not_yet_in_place: Mapped[bool] = mapped_column(Boolean, default=False)
    origin: Mapped[str] = mapped_column(String(14), default="manual")  # manual | auto_response | document_request
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)  # an auditor accepted an auto draft
    confirmed_by: Mapped[str | None] = mapped_column(String(36))
    review_role: Mapped[str | None] = mapped_column(String(14))  # chief_auditor | qa_reviewer (when the author is the Chief Auditor)
    review_comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_by: Mapped[str | None] = mapped_column(String(36))
    editor_ids: Mapped[list] = mapped_column(JSON, default=list)


class DraftFindingLink(TimestampedTenantMixin, Base):
    """Ties an auto-drafted finding to the answer that raised it. A dismissed draft keeps its reason, and the same answer
    does not raise it again."""

    __tablename__ = "draft_finding_links"

    response_id: Mapped[str] = mapped_column(String(36), ForeignKey("responses.id"), index=True)
    finding_id: Mapped[str] = mapped_column(String(36), ForeignKey("findings.id"), index=True)
    rule_title: Mapped[str] = mapped_column(String(300))
    dismissed_reason: Mapped[str | None] = mapped_column(Text)
    dismissed_by: Mapped[str | None] = mapped_column(String(36))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime)
