from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class Notification(TimestampedTenantMixin, Base):
    """An in-app notification for one user (spec §14). organization_id is the recipient's organization."""

    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    engagement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
