"""Annual review carry-forward (spec §21 F16). organization_id is the client."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class CarriedAnswer(TimestampedTenantMixin, Base):
    """One answer copied from the prior engagement into an annual review (Response.source = carried_forward). The client
    confirms it unchanged or updates it; the auditor sees what changed against the prior answer kept here."""

    __tablename__ = "carried_answers"
    __table_args__ = (UniqueConstraint("response_id", name="uq_carried_answer_response"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    response_id: Mapped[str] = mapped_column(String(36), ForeignKey("responses.id"))
    prior_response_id: Mapped[str] = mapped_column(String(36), ForeignKey("responses.id"))
    prior_value: Mapped[object | None] = mapped_column(JSON)
    prior_status: Mapped[str] = mapped_column(String(18))
    prior_detail: Mapped[str | None] = mapped_column(Text)
    prior_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | confirmed | updated
    decided_by: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
