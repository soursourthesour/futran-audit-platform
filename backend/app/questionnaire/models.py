"""Question bank (spec §18.1). Reference data: versioned, editable by Admin without code changes."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin


class TemplateVersion(IdMixin, Base):
    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_template_name_version"),)

    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(10))
    addenda: Mapped[list] = mapped_column(JSON, default=list)
    effective_date: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Question(IdMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("template_version_id", "code", name="uq_question_code"),)

    template_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("template_versions.id"), index=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    section: Mapped[str] = mapped_column(String(8))  # "3", "5", "V", "OS"
    sub_section: Mapped[str] = mapped_column(String(8))  # "3.1", "5.1a", "V"
    section_title: Mapped[str] = mapped_column(String(160))
    section_note: Mapped[str | None] = mapped_column(Text)  # template INTERN NOTE — Futran only
    scope: Mapped[str] = mapped_column(String(12))  # engagement | system
    label: Mapped[str] = mapped_column(String(300))
    help_text: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(16))
    options: Mapped[list | None] = mapped_column(JSON)
    detail_label: Mapped[str | None] = mapped_column(String(120))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    default_respondent: Mapped[str] = mapped_column(String(10), default="client")  # client | auditor
    applicability_rule: Mapped[dict | None] = mapped_column(JSON)
    section_rule: Mapped[dict | None] = mapped_column(JSON)
    finding_rule: Mapped[dict | None] = mapped_column(JSON)
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=False)
    scoring_map: Mapped[str | None] = mapped_column(String(30))  # risk factor key
    build_types: Mapped[list | None] = mapped_column(JSON)  # None = all
    light: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)


class ChecklistItem(IdMixin, Base):
    __tablename__ = "checklist_items"
    __table_args__ = (UniqueConstraint("template_version_id", "code", name="uq_checklist_code"),)

    template_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("template_versions.id"), index=True)
    section: Mapped[str] = mapped_column(String(8))
    section_title: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(String(400))
    scope: Mapped[str] = mapped_column(String(12))
    maturity_domain: Mapped[str] = mapped_column(String(20))
    applicability_rule: Mapped[dict | None] = mapped_column(JSON)
    build_types: Mapped[list | None] = mapped_column(JSON)
    pending_review: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)


RESPONSE_STATUSES = ("answered", "na", "not_yet_in_place", "unanswered")


class Response(TimestampedTenantMixin, Base):
    """An answer to a question for the engagement (ai_system_id None) or one AI system (spec §18.1).

    `value`/`status` is the answer of record. The client's own pre-fill is kept in the `client_*` columns: the client
    only ever sees those, so an auditor's correction or verification never shows on the client side.
    """

    __tablename__ = "responses"
    __table_args__ = (UniqueConstraint("engagement_id", "ai_system_id", "question_id", name="uq_responses_target_question"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    ai_system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_systems.id"), index=True)
    question_id: Mapped[str] = mapped_column(String(36), ForeignKey("questions.id"), index=True)
    value: Mapped[object | None] = mapped_column(JSON)
    detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(18), default="unanswered")
    na_reason: Mapped[str | None] = mapped_column(Text)
    source_person_name: Mapped[str | None] = mapped_column(String(160))
    source_person_title: Mapped[str | None] = mapped_column(String(160))
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    answered_by: Mapped[str | None] = mapped_column(String(36))
    answered_side: Mapped[str | None] = mapped_column(String(7))  # client | futran
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_by: Mapped[str | None] = mapped_column(String(36))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    client_value: Mapped[object | None] = mapped_column(JSON)
    client_detail: Mapped[str | None] = mapped_column(Text)
    client_status: Mapped[str | None] = mapped_column(String(18))
    client_na_reason: Mapped[str | None] = mapped_column(Text)
    client_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    client_answered_by: Mapped[str | None] = mapped_column(String(36))
    client_answered_at: Mapped[datetime | None] = mapped_column(DateTime)


class ResponseVersion(TimestampedTenantMixin, Base):
    """Append-only history of every save of a response."""

    __tablename__ = "response_versions"

    response_id: Mapped[str] = mapped_column(String(36), ForeignKey("responses.id"), index=True)
    side: Mapped[str] = mapped_column(String(7))
    value: Mapped[object | None] = mapped_column(JSON)
    detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(18))
    na_reason: Mapped[str | None] = mapped_column(Text)
    source_person_name: Mapped[str | None] = mapped_column(String(160))
    source_person_title: Mapped[str | None] = mapped_column(String(160))
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class ChecklistResult(TimestampedTenantMixin, Base):
    __tablename__ = "checklist_results"
    __table_args__ = (UniqueConstraint("engagement_id", "ai_system_id", "checklist_item_id", name="uq_checklist_results_target_item"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    ai_system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_systems.id"), index=True)
    checklist_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("checklist_items.id"), index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    auditor_note: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[str | None] = mapped_column(String(36))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
