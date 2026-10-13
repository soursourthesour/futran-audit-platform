from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class OutboxMessage(TimestampedTenantMixin, Base):
    __tablename__ = "outbox_messages"

    to: Mapped[list] = mapped_column(JSON)
    cc: Mapped[list | None] = mapped_column(JSON)
    subject: Mapped[str] = mapped_column(String(300))
    body_html: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    template_key: Mapped[str] = mapped_column(String(80))
    related_type: Mapped[str | None] = mapped_column(String(60))
    related_id: Mapped[str | None] = mapped_column(String(36))
    attachments: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | sent | failed
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(String(500))
