"""Threaded comments with internal or shared visibility (spec §21 F18). organization_id is the client.

A comment sits on one audit object (`object_type`, `object_id`): a question response, an evidence request, a document
request, a finding or a remediation item. A reply points at the thread's first comment (`parent_id`) and always has the
thread's visibility. `internal` comments are seen by Futran only; `shared` ones by Futran and by the client people who can
see the object. Comments are never deleted: the author may withdraw one, which hides its text and is logged.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

OBJECT_TYPES = ("response", "evidence_request", "document_request", "finding", "remediation")
VISIBILITIES = ("internal", "shared")


class Comment(TimestampedTenantMixin, Base):
    __tablename__ = "comments"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(20), index=True)
    object_id: Mapped[str] = mapped_column(String(36), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("comments.id"), index=True)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    author_side: Mapped[str] = mapped_column(String(7))  # futran | client
    visibility: Mapped[str] = mapped_column(String(8), index=True)
    body: Mapped[str] = mapped_column(Text)
    mention_ids: Mapped[list] = mapped_column(JSON, default=list)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)
    withdrawn_by: Mapped[str | None] = mapped_column(String(36))
    withdrawn_reason: Mapped[str | None] = mapped_column(Text)
