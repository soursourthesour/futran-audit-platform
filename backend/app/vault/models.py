"""G-10 records (spec B10). organization_id is the client on every row."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

TIERS = (3, 7, 10)


class RetentionPolicy(TimestampedTenantMixin, Base):
    """The client's retention tier from a date. The newest row in force applies; no row means the platform default (7)."""

    __tablename__ = "retention_policies"

    years: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(Date)
    set_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(String(300))


class LegalHold(TimestampedTenantMixin, Base):
    """A legal hold blocks deletion of everything in its scope until it is released. scope: {engagement_ids, system_ids,
    from, to}; each part given narrows the hold, and an empty scope holds everything the client has."""

    __tablename__ = "legal_holds"
    __table_args__ = (UniqueConstraint("organization_id", "ref", name="uq_legal_hold_ref"),)

    ref: Mapped[str] = mapped_column(String(10))  # LH-001 within the client
    name: Mapped[str] = mapped_column(String(200))
    matter_ref: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    set_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    set_at: Mapped[datetime] = mapped_column(DateTime)
    released_at: Mapped[datetime | None] = mapped_column(DateTime)
    released_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    release_reason: Mapped[str | None] = mapped_column(Text)


class RetentionNotice(TimestampedTenantMixin, Base):
    """One item's deletion notice. The vault deletes an item no earlier than 90 days after its notice."""

    __tablename__ = "retention_notices"
    __table_args__ = (UniqueConstraint("item_type", "item_id", name="uq_retention_notice_item"),)

    item_type: Mapped[str] = mapped_column(String(20))  # file | bias_raw_data
    item_id: Mapped[str] = mapped_column(String(36))
    engagement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    due_on: Mapped[date] = mapped_column(Date)  # end of the retention period
    delete_on: Mapped[date] = mapped_column(Date)  # not before notice + 90 days
    notified_on: Mapped[date] = mapped_column(Date)
