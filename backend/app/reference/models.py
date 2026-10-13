"""Platform-wide reference data (not tenant-owned): jurisdictions and memberships."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin


class Jurisdiction(IdMixin, Base):
    __tablename__ = "jurisdictions"

    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    level: Mapped[str] = mapped_column(String(20))  # supranational | country | state | city
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
    iso_code: Mapped[str | None] = mapped_column(String(10))
    aliases: Mapped[list | None] = mapped_column(JSON)
    has_laws: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_notes: Mapped[dict | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36))


class JurisdictionMembership(IdMixin, Base):
    """A country's membership of a supranational group (e.g. Germany in the EU)."""

    __tablename__ = "jurisdiction_memberships"
    __table_args__ = (UniqueConstraint("member_id", "group_id", name="uq_membership"),)

    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
