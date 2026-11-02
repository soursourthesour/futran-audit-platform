"""Integrations and automated AI discovery (spec §21 F2). organization_id is the client throughout.

Privacy: a `DiscoveredTool` is one AI product × one source × one department, with a count of people. Browsing data
(CASB and proxy logs) is aggregated while the file is read and never stored per person. Names of the people behind an
SSO assignment, an OAuth grant, a licence or a card transaction are kept in `DiscoveredToolUser`, which only Futran
auditors on the engagement may read, and only for tools used in a Tier 2 or Tier 3 use case (named-user checks).
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

OAUTH_TYPES = ("entra_id", "microsoft_365", "google_workspace")
CREDENTIAL_TYPES = ("okta",)
UPLOAD_TYPES = ("expense_csv", "casb_csv")
TYPES = ("okta", "entra_id", "google_workspace", "microsoft_365", "expense_csv", "casb_csv")
SIGNALS = ("sso_app", "oauth_grant", "licence", "expense", "traffic")
TOOL_STATUSES = ("new", "confirmed", "mapped", "dismissed")


class Connector(TimestampedTenantMixin, Base):
    __tablename__ = "connectors"
    __table_args__ = (UniqueConstraint("organization_id", "type", name="uq_connector_org_type"),)

    type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="not_connected")  # not_connected | consent_requested | connected | error | disconnected
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    authorized_by: Mapped[str | None] = mapped_column(String(36))
    authorized_by_name: Mapped[str | None] = mapped_column(String(160))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime)
    tenant_id: Mapped[str | None] = mapped_column(String(255), index=True)  # Entra tenant, Google domain or Okta org domain
    verified_domains: Mapped[list] = mapped_column(JSON, default=list)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(String(500))
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_ref: Mapped[str | None] = mapped_column(String(40))
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64))


class ConnectorRun(TimestampedTenantMixin, Base):
    """One sync or upload. Every run is logged, including failed ones."""

    __tablename__ = "connector_runs"

    connector_id: Mapped[str] = mapped_column(String(36), ForeignKey("connectors.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # sync | upload
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running | completed | failed
    started_by: Mapped[str | None] = mapped_column(String(36))
    filename: Mapped[str | None] = mapped_column(String(255))
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_matched: Mapped[int] = mapped_column(Integer, default=0)
    tools_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500))


class DiscoveredTool(TimestampedTenantMixin, Base):
    __tablename__ = "discovered_tools"
    __table_args__ = (UniqueConstraint("connector_id", "vendor_key", "signal", "department_key", name="uq_discovered_tool"),)

    connector_id: Mapped[str] = mapped_column(String(36), ForeignKey("connectors.id"), index=True)
    vendor_key: Mapped[str] = mapped_column(String(60))
    vendor: Mapped[str] = mapped_column(String(120))
    product: Mapped[str] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(120))
    signal: Mapped[str] = mapped_column(String(12))  # sso_app | oauth_grant | licence | expense | traffic
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"), index=True)
    department_name: Mapped[str | None] = mapped_column(String(120))  # as the source named it
    department_key: Mapped[str] = mapped_column(String(160))  # department id, or "name:<lowercased name>", or "unknown"
    user_count: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(String(300))  # e.g. "6 paid subscriptions", "calendar, drive"
    first_seen: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime)
    matched_tool_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_tools.id"))
    status: Mapped[str] = mapped_column(String(12), default="new")  # new | confirmed | mapped | dismissed
    dismiss_reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class DiscoveredToolUser(TimestampedTenantMixin, Base):
    """A person behind a discovered tool. Never from browsing data. Read only by assigned Futran auditors for Tier 2–3
    named-user checks (app.connectors.service.people_for_auditor)."""

    __tablename__ = "discovered_tool_users"

    discovered_tool_id: Mapped[str] = mapped_column(String(36), ForeignKey("discovered_tools.id"), index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    name: Mapped[str | None] = mapped_column(String(160))
