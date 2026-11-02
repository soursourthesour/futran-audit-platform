"""AI literacy training (spec §21 F12). TrainingModule is Futran's content, one row per version; the rest belongs to the
client (organization_id is the client)."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin


class TrainingModule(IdMixin, Base):
    __tablename__ = "training_modules"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_training_module_version"),)

    code: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(200))
    minutes: Mapped[int] = mapped_column(Integer)
    audience: Mapped[str | None] = mapped_column(String(200))
    pass_mark: Mapped[int] = mapped_column(Integer, default=80)
    content: Mapped[dict] = mapped_column(JSON)  # the whole module as loaded, with its answer key
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TrainingProgram(TimestampedTenantMixin, Base):
    """The client's completion target: a percentage by a date. One per client."""

    __tablename__ = "training_programs"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_training_program_org"),)

    target_pct: Mapped[int] = mapped_column(Integer, default=80)
    target_date: Mapped[date | None] = mapped_column(Date)
    evidence_file_ids: Mapped[list] = mapped_column(JSON, default=list)  # completion records saved for the literacy owner role


class TrainingCampaign(TimestampedTenantMixin, Base):
    """One "Assign modules" action for one module: who it went to, the due date and the email send that carried the links."""

    __tablename__ = "training_campaigns"

    module_id: Mapped[str] = mapped_column(String(36), ForeignKey("training_modules.id"))
    module_code: Mapped[str] = mapped_column(String(40), index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    audience: Mapped[dict] = mapped_column(JSON, default=dict)  # {kind: departments | role | groups, ids?, role?, label}
    assigned_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    send_id: Mapped[str | None] = mapped_column(String(36))


class TrainingAssignment(TimestampedTenantMixin, Base):
    """One person and one module. People without a login are known by email (from the directory)."""

    __tablename__ = "training_assignments"

    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("training_campaigns.id"), index=True)
    module_id: Mapped[str] = mapped_column(String(36), ForeignKey("training_modules.id"))
    module_code: Mapped[str] = mapped_column(String(40), index=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    name: Mapped[str | None] = mapped_column(String(160))
    person_id: Mapped[str | None] = mapped_column(String(36))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"), index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="assigned")  # assigned | in_progress | completed
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    score: Mapped[int | None] = mapped_column(Integer)  # best passing score, or the last attempt's while not passed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)  # this attempt's first answer to each question
    certificate_no: Mapped[str | None] = mapped_column(String(24), unique=True)
