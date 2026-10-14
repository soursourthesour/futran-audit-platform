"""Stored risk scores (spec §19.5). Every recalculation that changes the result is a new row, kept with the methodology
version so old reports stay reproducible."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class SystemRiskScore(TimestampedTenantMixin, Base):
    __tablename__ = "system_risk_scores"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    ai_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_systems.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    methodology_version: Mapped[str] = mapped_column(String(10))
    factor_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    eu_classification: Mapped[str | None] = mapped_column(String(20))
    inherent: Mapped[float | None] = mapped_column(Float)
    domain_inputs: Mapped[dict] = mapped_column(JSON, default=dict)  # per domain: pct confirmed, open High/Critical findings
    domain_scores_proposed: Mapped[dict] = mapped_column(JSON, default=dict)
    domain_scores_final: Mapped[dict] = mapped_column(JSON, default=dict)  # set by the auditor
    domain_rationales: Mapped[dict] = mapped_column(JSON, default=dict)
    maturity: Mapped[float | None] = mapped_column(Float)
    residual: Mapped[float | None] = mapped_column(Float)
    knockouts_triggered: Mapped[list] = mapped_column(JSON, default=list)
    computed_rating: Mapped[str | None] = mapped_column(String(10))
    override_rating: Mapped[str | None] = mapped_column(String(10))
    override_rationale: Mapped[str | None] = mapped_column(Text)
    override_by: Mapped[str | None] = mapped_column(String(36))
    final_rating: Mapped[str | None] = mapped_column(String(10))
    scored_by: Mapped[str | None] = mapped_column(String(36))
    approved_by: Mapped[str | None] = mapped_column(String(36))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)


class EngagementScorecard(TimestampedTenantMixin, Base):
    __tablename__ = "engagement_scorecards"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True, unique=True)
    domain_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    overall_maturity: Mapped[float | None] = mapped_column(Float)
    overall_rating: Mapped[str | None] = mapped_column(String(10))
    narrative: Mapped[str | None] = mapped_column(Text)
