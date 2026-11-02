"""Pre-deployment AI impact assessment and reassessment triggers (spec §21 F8, screen 28). organization_id is the client.

The spec's `ai_system_id` is the client's register row (`RegisterSystem`): an approved project becomes a register system
in stage `proposed`, or is linked to one that already exists. A `ReassessmentTrigger` belongs to a register system and,
while that system is in a current engagement, reopens the affected sections of its assessment.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, TimestampedTenantMixin

STATUSES = ("draft", "in_review", "decided", "withdrawn")
DECISIONS = ("approved", "approved_with_conditions", "rejected")
RECOMMENDATIONS = ("approve", "approve_with_conditions", "reject")
REVIEW_STEPS = ("department", "dpo")
DEPTHS = ("baseline", "light", "full")
CONDITION_STATUSES = ("open", "met", "closed")

TRIGGER_TYPES = ("version_change", "new_data_category", "new_jurisdiction", "new_population", "vendor_change", "failed_monitor_check",
                 "regulatory_update", "twelve_months")
# spec: manual / monitor / regulatory_update / schedule; register_edit = detected from a change to the register record
TRIGGER_SOURCES = ("manual", "monitor", "regulatory_update", "schedule", "register_edit")
TRIGGER_STATUSES = ("open", "in_progress", "resolved", "dismissed")
OPEN_TRIGGER = ("open", "in_progress")


class ImpactAssessment(TimestampedTenantMixin, Base):
    """A new AI project assessed before it is bought or deployed (F8 intake → tier → laws → reviewers → decision)."""

    __tablename__ = "impact_assessments"

    reference: Mapped[str] = mapped_column(String(12))  # IA-001, per client, never reused
    project_name: Mapped[str] = mapped_column(String(160))
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"), index=True)
    # purpose, tool_or_vendor, sourcing, system_type, planned_go_live, jurisdiction_ids, data_categories, data_subjects,
    # decision_impact, public_facing, user_count
    intake: Mapped[dict] = mapped_column(JSON, default=dict)
    proposed_tier: Mapped[int | None] = mapped_column(Integer)
    tier_reason: Mapped[str | None] = mapped_column(String(300))
    assessment_depth: Mapped[str | None] = mapped_column(String(10))
    depth_sections: Mapped[list] = mapped_column(JSON, default=list)
    matched_regulations: Mapped[list] = mapped_column(JSON, default=list)  # [{regulation_id, name, matched, reason}]
    status: Mapped[str] = mapped_column(String(12), default="draft", index=True)
    submitted_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision: Mapped[str | None] = mapped_column(String(26))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    register_system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    opinion_opportunity_id: Mapped[str | None] = mapped_column(String(36))
    opinion_requested_by: Mapped[str | None] = mapped_column(String(36))
    opinion_requested_at: Mapped[datetime | None] = mapped_column(DateTime)


class ImpactReview(TimestampedTenantMixin, Base):
    """One reviewer's recommendation: the Department Compliance Lead, then the Data Protection Officer."""

    __tablename__ = "impact_reviews"

    impact_assessment_id: Mapped[str] = mapped_column(String(36), ForeignKey("impact_assessments.id"), index=True)
    step: Mapped[str] = mapped_column(String(12))
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    recommendation: Mapped[str] = mapped_column(String(26))
    comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ImpactCondition(TimestampedTenantMixin, Base):
    """A condition of an approval, tracked like a commitment: owner, due date, met, confirmed closed."""

    __tablename__ = "impact_conditions"

    impact_assessment_id: Mapped[str] = mapped_column(String(36), ForeignKey("impact_assessments.id"), index=True)
    text: Mapped[str] = mapped_column(String(600))
    owner_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="open")
    met_note: Mapped[str | None] = mapped_column(Text)
    met_by: Mapped[str | None] = mapped_column(String(36))
    met_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_by: Mapped[str | None] = mapped_column(String(36))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ReassessmentTrigger(TimestampedTenantMixin, Base):
    """Something that makes a register system's assessment out of date (F8). Raised through `app.impact.triggers.raise_trigger`."""

    __tablename__ = "reassessment_triggers"

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    type: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str | None] = mapped_column(String(120), index=True)  # update id, check code, change log batch, due date
    detail: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    reopened: Mapped[list] = mapped_column(JSON, default=list)  # [{engagement_id, ai_system_id, reference, sections, answers_reopened}]
    resolved_by: Mapped[str | None] = mapped_column(String(36))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution_note: Mapped[str | None] = mapped_column(Text)
