"""Employee AI-use attestation (spec §9.5, schematic D13). organization_id is the client."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class AttestationCampaign(TimestampedTenantMixin, Base):
    __tablename__ = "attestation_campaigns"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    policy_version: Mapped[str] = mapped_column(String(40))
    launched_by: Mapped[str | None] = mapped_column(String(36))
    launched_at: Mapped[datetime] = mapped_column(DateTime)
    closes_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    department_ids: Mapped[list] = mapped_column(JSON, default=list)
    link_token: Mapped[str] = mapped_column(String(64), unique=True)  # one shared staff link, shown to the CAICO to circulate
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed


class Attestation(TimestampedTenantMixin, Base):
    """One employee's answers. Individual rows are seen only by the CAICO, DPO and assigned Futran auditors."""

    __tablename__ = "attestations"

    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("attestation_campaigns.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    respondent_name: Mapped[str] = mapped_column(String(120))
    respondent_email: Mapped[str | None] = mapped_column(String(254))
    department_id: Mapped[str] = mapped_column(String(36), ForeignKey("departments.id"))
    uses_ai: Mapped[bool] = mapped_column(Boolean)
    tools_declared: Mapped[list] = mapped_column(JSON, default=list)  # [{tool, account_type, name?}]
    purposes: Mapped[list] = mapped_column(JSON, default=list)
    data_entered: Mapped[list] = mapped_column(JSON, default=list)
    policy_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime)
