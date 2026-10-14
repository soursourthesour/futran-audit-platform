"""Pre-audit document request register (spec §18.5, template §2 and Appendix A)."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class DocumentRequest(TimestampedTenantMixin, Base):
    __tablename__ = "document_requests"
    __table_args__ = (
        UniqueConstraint("engagement_id", "catalog_item_id", "ai_system_id", name="uq_document_requests_item_system"),
        Index("uq_document_requests_engagement_item", "engagement_id", "catalog_item_id", unique=True, sqlite_where=text("ai_system_id IS NULL"), postgresql_where=text("ai_system_id IS NULL")),
    )

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    catalog_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("document_catalog.id"), index=True)
    ai_system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_systems.id"), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    due_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(14), default="pending")  # pending | received | not_available
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_by: Mapped[str | None] = mapped_column(String(36))
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    not_available_note: Mapped[str | None] = mapped_column(Text)
    finding_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("findings.id"))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime)
    escalated_chase_id: Mapped[str | None] = mapped_column(String(36))  # the chase the Lead Auditor was last told about


class DocumentChase(TimestampedTenantMixin, Base):
    __tablename__ = "document_chases"

    document_request_id: Mapped[str] = mapped_column(String(36), ForeignKey("document_requests.id"), index=True)
    chased_at: Mapped[datetime] = mapped_column(DateTime)
    chased_by: Mapped[str | None] = mapped_column(String(36))
    note: Mapped[str | None] = mapped_column(Text)
