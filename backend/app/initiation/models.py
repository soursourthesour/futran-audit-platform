from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class InitiationPackage(TimestampedTenantMixin, Base):
    """The seven documents sent to the client at approval (spec §9.3, §12). organization_id is the client."""

    __tablename__ = "initiation_packages"
    __table_args__ = (UniqueConstraint("engagement_id", "version", name="uq_package_version"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(14), default="draft")  # draft | sent | superseded
    client_message: Mapped[str | None] = mapped_column(Text)
    prepared_by: Mapped[str | None] = mapped_column(String(36))
    approved_by: Mapped[str | None] = mapped_column(String(36))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_checklist: Mapped[dict | None] = mapped_column(JSON)


class PackageDocument(TimestampedTenantMixin, Base):
    __tablename__ = "package_documents"

    package_id: Mapped[str] = mapped_column(String(36), ForeignKey("initiation_packages.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    item: Mapped[int] = mapped_column(Integer)  # 1–7, spec §12
    template_key: Mapped[str] = mapped_column(String(40))
    template_version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    format: Mapped[str] = mapped_column(String(8), default="md")  # md | csv
    requires_action: Mapped[str] = mapped_column(String(10))  # sign | nominate | upload | review | read | answer
    body_md: Mapped[str] = mapped_column(Text)
    merge_values: Mapped[dict | None] = mapped_column(JSON)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    docx_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    pdf_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    csv_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[str | None] = mapped_column(String(36))


class NoticeRelease(TimestampedTenantMixin, Base):
    """One version of the employee AI audit and data notice (package item 5) as the CAICO sent it to staff.

    The text is kept as sent, so each acknowledgement points at the exact wording the person read."""

    __tablename__ = "notice_releases"
    __table_args__ = (UniqueConstraint("engagement_id", "version", name="uq_notice_release_version"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("package_documents.id"))
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    body_md: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    sent_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)


class NoticeAcknowledgement(TimestampedTenantMixin, Base):
    """A client user's record that they read and understood one version of the notice."""

    __tablename__ = "notice_acknowledgements"
    __table_args__ = (UniqueConstraint("release_id", "user_id", name="uq_notice_ack_user"),)

    release_id: Mapped[str] = mapped_column(String(36), ForeignKey("notice_releases.id"), index=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime)
