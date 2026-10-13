"""Question bank (spec §18.1). Reference data: versioned, editable by Admin without code changes."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin


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
