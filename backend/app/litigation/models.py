"""Litigation tracker (spec §27.4, §27.7). Futran-side records: clients never see them directly."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin

STAGES = ("filed", "pleadings", "discovery", "stayed", "trial", "appeal", "decided", "settled", "dismissed")
STAGE_LABELS = {
    "filed": "Filed", "pleadings": "Pleadings", "discovery": "Discovery", "stayed": "Stayed", "trial": "Trial",
    "appeal": "Appeal", "decided": "Decided", "settled": "Settled", "dismissed": "Dismissed",
}


class Case(IdMixin, Base):
    """One court case or decision that shapes how an AI law is read."""

    __tablename__ = "litigation_cases"

    jurisdiction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
    geography: Mapped[str | None] = mapped_column(String(120))  # as shown, e.g. "United States · federal"
    area: Mapped[str] = mapped_column(String(160))  # law or area, e.g. "Hiring discrimination (ADEA, ADA)"
    name: Mapped[str] = mapped_column(String(300))  # X v. Y
    court: Mapped[str | None] = mapped_column(String(200))
    docket_ref: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    why_matters: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(12), index=True)
    stage_note: Mapped[str | None] = mapped_column(String(200))
    last_update_on: Mapped[date | None] = mapped_column(Date)
    regulation_ids: Mapped[list] = mapped_column(JSON, default=list)
    talking_points_futran: Mapped[str | None] = mapped_column(Text)
    talking_points_client: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{title, url}]
    source_ids: Mapped[list] = mapped_column(JSON, default=list)  # regulatory-master Source rows, when known
    timeline: Mapped[list] = mapped_column(JSON, default=list)  # [{on, stage, label}]
    match_rule: Mapped[dict] = mapped_column(JSON, default=dict)  # {types, sourcing, vendors, uses}
    version: Mapped[int] = mapped_column(Integer, default=1)
    origin: Mapped[str] = mapped_column(String(10), default="manual")  # manual | claude | seed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class CaseClientMatch(IdMixin, Base):
    """A client whose register holds AI like the AI in a case (matched by type, vendor and use)."""

    __tablename__ = "case_client_matches"
    __table_args__ = (UniqueConstraint("case_id", "organization_id", name="uq_case_client_match"),)

    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("litigation_cases.id"), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    ai_system_ids: Mapped[list] = mapped_column(JSON, default=list)  # register_systems ids
    match_reason: Mapped[str] = mapped_column(String(500))
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CaseFollow(IdMixin, Base):
    __tablename__ = "case_follows"
    __table_args__ = (UniqueConstraint("case_id", "user_id", name="uq_case_follow"),)

    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("litigation_cases.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
