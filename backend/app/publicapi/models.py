"""Public API clients, access tokens and webhooks (spec §21 F17). organization_id is always the client organization.

Secrets are never stored readable: an API client's secret and every access token are kept as SHA-256 hashes (they are
long random values, so a fast hash is enough) and shown once. A webhook signing secret must be used again to sign each
delivery, so it is kept encrypted with the platform token key (app.mail.tokens) and shown once.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin

SCOPES = {
    "inventory:read": "Read the AI system register, departments and AI tools",
    "inventory:write": "Add and edit AI systems in the register",
    "usecases:write": "Submit new AI use cases for review",
    "attestation:read": "Read attestation progress (counts only)",
    "findings:read": "Read findings shared with you and the comments shared on them",
    "remediation:read": "Read remediation status",
    "updates:read": "Read regulatory updates published to you",
    "agent_logs:write": "Send AI agent decision logs (tracing add-on)",
}
EVENTS = {
    "signoff.completed": "A sign-off is completed",
    "remediation.overdue": "A remediation item passes its due date",
    "regulatory_update.published": "A regulatory update is published to you",
}
DELIVERY_STATUSES = ("pending", "retrying", "delivered", "failed", "blocked")


class ApiClient(TimestampedTenantMixin, Base):
    __tablename__ = "api_clients"
    __table_args__ = (UniqueConstraint("client_id", name="uq_api_clients_client_id"),)

    name: Mapped[str] = mapped_column(String(120))
    client_id: Mapped[str] = mapped_column(String(40))
    secret_hash: Mapped[str] = mapped_column(String(64))
    secret_hint: Mapped[str] = mapped_column(String(8))  # last four characters, to tell secrets apart
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | revoked
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))  # the Client Admin who answers for it; API writes are recorded as theirs
    secret_rotated_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_by: Mapped[str | None] = mapped_column(String(36))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class ApiToken(IdMixin, Base):
    __tablename__ = "api_tokens"

    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    api_client_id: Mapped[str] = mapped_column(String(36), ForeignKey("api_clients.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class Webhook(TimestampedTenantMixin, Base):
    __tablename__ = "webhooks"

    url: Mapped[str] = mapped_column(String(500))
    events: Mapped[list] = mapped_column(JSON, default=list)
    secret_encrypted: Mapped[str] = mapped_column(Text)
    secret_ref: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | paused
    description: Mapped[str | None] = mapped_column(String(200))
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime)


class WebhookDelivery(IdMixin, Base):
    """One event for one webhook, with each attempt's outcome. `event_key` makes an event go to a hook only once."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("webhook_id", "event_key", name="uq_webhook_deliveries_event"),)

    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    webhook_id: Mapped[str] = mapped_column(String(36), ForeignKey("webhooks.id"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    event_key: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(500))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

