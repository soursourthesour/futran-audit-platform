"""Benchmarking snapshots (spec §21 F15). One row per signed engagement, recomputed when its final report is signed.
organization_id is the client the snapshot describes; screens never show it to anyone outside Futran's Chief Auditor
view of that client, and peer figures are only shown for groups of at least five consenting clients."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class BenchmarkSnapshot(TimestampedTenantMixin, Base):
    __tablename__ = "benchmark_snapshots"

    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), index=True, unique=True)
    industry: Mapped[str | None] = mapped_column(String(80))
    size_band: Mapped[str | None] = mapped_column(String(40))
    consent: Mapped[bool] = mapped_column(Boolean, default=False)  # Organization.benchmark_consent when taken
    domain_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    overall_maturity: Mapped[float | None] = mapped_column(Float)
    overall_rating: Mapped[str | None] = mapped_column(String(10))
    finding_themes: Mapped[list] = mapped_column(JSON, default=list)  # theme codes (app/insights/themes.yaml)
    period_end: Mapped[date | None] = mapped_column(Date)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime)
