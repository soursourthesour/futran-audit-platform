"""Platform certification and trust (spec §21 F19): Futran's SOC 2 readiness register. organization_id is Futran's own
organization. Controls are grouped by the AICPA trust services criteria (2017, revised points of focus 2022)."""
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

CRITERIA = {"security": "Security (common criteria)", "availability": "Availability", "confidentiality": "Confidentiality",
            "processing_integrity": "Processing integrity", "privacy": "Privacy"}
STATUSES = {"not_started": "Not started", "in_progress": "In progress", "implemented": "Implemented", "tested": "Tested by an auditor", "not_applicable": "Not applicable"}


class SocControl(TimestampedTenantMixin, Base):
    __tablename__ = "soc_controls"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_soc_controls_org_code"),)

    code: Mapped[str] = mapped_column(String(12))
    criterion: Mapped[str] = mapped_column(String(24), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="not_started")
    evidence_link: Mapped[str | None] = mapped_column(String(500))
    last_reviewed_on: Mapped[date | None] = mapped_column(Date)
    review_months: Mapped[int] = mapped_column(Integer, default=12)
    notes: Mapped[str | None] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0)
