"""Website API keys for the public library API (/api/public/v1/library). A key belongs to Futran, not to a client
organization: it opens the published law library and AI litigation tracker, read-only, to Futran's own website.

The key is a long random value, so it is kept as a SHA-256 hash only and shown once, in the response that creates it.
`key_prefix` (the first 12 characters) tells keys apart in the admin screen and in logs.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin

DEFAULT_RATE_LIMIT = 120  # requests a minute, per key


class WebsiteApiKey(IdMixin, Base):
    __tablename__ = "website_api_keys"

    name: Mapped[str] = mapped_column(String(120))
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    allowed_origins: Mapped[list] = mapped_column(JSON, default=list)  # browser origins allowed by CORS; empty = server-side calls only
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=DEFAULT_RATE_LIMIT)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | revoked
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_by: Mapped[str | None] = mapped_column(String(36))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
