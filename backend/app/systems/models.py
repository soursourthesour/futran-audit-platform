"""AI systems in scope and the client's AI vendor register (spec §19.1, template §1.3 and §9.1)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

BUILT_BY = ("in_house", "vendor", "open_source_customized", "hybrid")
DEPTHS = ("full", "light")
STATUSES = ("not_started", "client_prefill", "in_review", "scored", "locked")
RISK_LEVELS = ("H", "M", "L")


class Vendor(TimestampedTenantMixin, Base):
    """An AI vendor of the client. organization_id is the client."""

    __tablename__ = "vendors"

    legal_name: Mapped[str] = mapped_column(String(200))
    capability: Mapped[str | None] = mapped_column(String(300))
    personal_data_processed: Mapped[bool | None] = mapped_column(Boolean)
    baa_dpa_signed: Mapped[bool | None] = mapped_column(Boolean)
    last_risk_review: Mapped[date | None] = mapped_column(Date)
    risk_level: Mapped[str | None] = mapped_column(String(1))  # H | M | L


class AISystem(TimestampedTenantMixin, Base):
    """A system audited under template §3–9. organization_id is the client."""

    __tablename__ = "ai_systems"
    __table_args__ = (UniqueConstraint("engagement_id", "reference_id", name="uq_ai_systems_engagement_ref"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    reference_id: Mapped[str] = mapped_column(String(10))  # SYS-001, numbered per engagement, never reused
    version: Mapped[str | None] = mapped_column(String(40))
    owner_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    technical_owner_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"))
    built_by: Mapped[str | None] = mapped_column(String(24))  # in_house | vendor | open_source_customized | hybrid; unset for systems listed at initiation
    vendor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("vendors.id"))
    tool_ids: Mapped[list] = mapped_column(JSON, default=list)
    use_case_ids: Mapped[list] = mapped_column(JSON, default=list)
    assessment_depth: Mapped[str] = mapped_column(String(5), default="full")
    status: Mapped[str] = mapped_column(String(14), default="not_started")
    completion_pct: Mapped[int] = mapped_column(Integer, default=0)
    methodology_version: Mapped[str | None] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(10), default="auditor")  # wizard | auditor


class SystemAdditionRequest(TimestampedTenantMixin, Base):
    """Adding a system after initiation needs an Engagement Manager's approval (template §1.3)."""

    __tablename__ = "system_addition_requests"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | approved | rejected
    decided_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_comment: Mapped[str | None] = mapped_column(Text)
    system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_systems.id"))
