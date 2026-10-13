from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

SIGN_OFF_TITLES = {
    1: "Engagement letter and scope",
    2: "Department inventory",
    3: "Data categories for Tier 2–3 use cases",
    4: "Management representation",
    5: "Final risk tiers and findings",
    6: "Management responses and remediation plan",
    7: "Final report",
    8: "Public summary",
}


class SignOff(TimestampedTenantMixin, Base):
    """One of the eight sign-offs (spec §8). organization_id is the client."""

    __tablename__ = "sign_offs"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    scope_ref: Mapped[str | None] = mapped_column(String(36))  # e.g. department_id for sign-off 2
    preparer_id: Mapped[str | None] = mapped_column(String(36))
    reviewer_id: Mapped[str | None] = mapped_column(String(36))
    approver_ids: Mapped[list | None] = mapped_column(JSON)
    required_approver_roles: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | in_review | approved | returned
    comment: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    document_version_id: Mapped[str | None] = mapped_column(String(36))  # PackageDocument or generated document
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sign_offs.id"))
    correction_reason: Mapped[str | None] = mapped_column(Text)


class Signature(TimestampedTenantMixin, Base):
    """A click-to-sign record (schematic D8): the typed name, when, from where, and the hash of what was signed."""

    __tablename__ = "signatures"

    sign_off_id: Mapped[str] = mapped_column(String(36), ForeignKey("sign_offs.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(30))
    typed_name: Mapped[str] = mapped_column(String(120))
    signed_at: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    document_sha256: Mapped[str | None] = mapped_column(String(64))
