from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class FileObject(TimestampedTenantMixin, Base):
    """A stored file: an upload or a generated document. organization_id is the owning tenant."""

    __tablename__ = "files"

    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(400), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    scan_status: Mapped[str] = mapped_column(String(12), default="not_scanned")  # clean | not_scanned | infected
    uploaded_by: Mapped[str | None] = mapped_column(String(36))
    linked_type: Mapped[str | None] = mapped_column(String(40))  # evidence | governance_document | package_document | ...
    linked_id: Mapped[str | None] = mapped_column(String(36), index=True)
