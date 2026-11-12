"""Service template library (Release 2 B6, screen G-06): one template per engagement type, in versions. Futran's
reference data, not a client's: no organization_id. The Futran Admin maintains a version while it is a draft; the Chief
Auditor approves it before use; an approved version never changes (a change is a new version)."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin

STATUSES = ("draft", "awaiting_approval", "approved", "superseded")


class ServiceTemplate(IdMixin, Base):
    __tablename__ = "service_templates"

    engagement_type: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    content_owner: Mapped[str | None] = mapped_column(String(80))  # who supplies the content: FATF, FRD, Microsoft practice, FTLC, Sales Manager
    note: Mapped[str | None] = mapped_column(Text)  # e.g. "Waiting on content"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))


class ServiceTemplateVersion(IdMixin, Base):
    __tablename__ = "service_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_service_template_version"),)

    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("service_templates.id"), index=True)
    version: Mapped[str] = mapped_column(String(10))  # 0.1, 0.2, 1.0
    status: Mapped[str] = mapped_column(String(20), default="draft")
    sections: Mapped[list] = mapped_column(JSON, default=list)  # [{code, title, note}]
    checklists: Mapped[list] = mapped_column(JSON, default=list)  # [{section, code, text, evidence}]
    question_codes: Mapped[list] = mapped_column(JSON, default=list)  # question bank codes (v0.6.1 §18.1 engine), e.g. 9.2.01
    deliverables: Mapped[list] = mapped_column(JSON, default=list)  # [text]
    default_stages: Mapped[list] = mapped_column(JSON, default=list)  # [text]
    report_template: Mapped[str | None] = mapped_column(String(120))  # document template key or a description
    catalog_codes: Mapped[list] = mapped_column(JSON, default=list)  # master price list codes
    key_dates: Mapped[list] = mapped_column(JSON, default=list)  # [{label, date, source}]
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    editor_ids: Mapped[list | None] = mapped_column(JSON)  # everyone who started, edited or submitted it: none of them may approve it
    submitted_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_note: Mapped[str | None] = mapped_column(Text)
    returned_note: Mapped[str | None] = mapped_column(Text)
