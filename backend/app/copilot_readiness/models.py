"""G-07 Microsoft 365 Copilot readiness workspace (spec B7). organization_id is the client; one workspace per
`copilot_readiness` engagement."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

PHASES = ("pilot", "deploy", "operate")
IMPORT_KINDS = ("licence_usage", "purview_oversharing", "sharepoint_permissions")
SHARING = ("everyone", "everyone_except_external", "org", "anyone_link", "specific", "external", "unknown")
RISKS = ("high", "medium", "low")
ACTIONS = ("restrict_discovery", "fix_permissions", "apply_label", "archive", "accept")
SITE_STATUSES = ("open", "in_progress", "done")
CONTROL_STATUSES = ("open", "done", "not_applicable")


class CopilotWorkspace(TimestampedTenantMixin, Base):
    __tablename__ = "copilot_workspaces"
    __table_args__ = (UniqueConstraint("engagement_id", name="uq_copilot_workspace_engagement"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    phase: Mapped[str] = mapped_column(String(10), default="pilot")
    licences: Mapped[int | None] = mapped_column(Integer)
    active_users: Mapped[int | None] = mapped_column(Integer)  # active in the 28 days before the report date
    usage_as_of: Mapped[date | None] = mapped_column(Date)
    by_department: Mapped[list | None] = mapped_column(JSON)  # [{"department", "licences", "active"}]
    register_system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("register_systems.id"))
    report_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    report_at: Mapped[datetime | None] = mapped_column(DateTime)


class CopilotImport(TimestampedTenantMixin, Base):
    """One uploaded admin export, kept as evidence (the file and its SHA-256)."""

    __tablename__ = "copilot_imports"

    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("copilot_workspaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("files.id"))
    sha256: Mapped[str] = mapped_column(String(64))
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_used: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict | None] = mapped_column(JSON)


class CopilotSite(TimestampedTenantMixin, Base):
    """A SharePoint or OneDrive site from the Purview or SharePoint Advanced Management reports. A re-import updates the
    measures and keeps the action, owner and status."""

    __tablename__ = "copilot_sites"

    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("copilot_workspaces.id"), index=True)
    site_key: Mapped[str] = mapped_column(String(400), index=True)
    name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(600))
    site_owner: Mapped[str | None] = mapped_column(String(200))
    label_coverage: Mapped[float | None] = mapped_column(Float)  # percent of items with a sensitivity label
    sharing: Mapped[str] = mapped_column(String(30), default="unknown")
    sensitive_items: Mapped[int | None] = mapped_column(Integer)
    last_activity: Mapped[date | None] = mapped_column(Date)
    risk_override: Mapped[str | None] = mapped_column(String(10))
    action: Mapped[str | None] = mapped_column(String(30))
    action_owner: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(12), default="open")
    note: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list | None] = mapped_column(JSON)  # import kinds that reported it


class CopilotWave(TimestampedTenantMixin, Base):
    """A rollout wave: who, when, and the sites and controls that must be ready before it goes."""

    __tablename__ = "copilot_waves"

    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("copilot_workspaces.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(120))
    groups: Mapped[str | None] = mapped_column(String(400))
    user_count: Mapped[int | None] = mapped_column(Integer)
    planned_on: Mapped[date | None] = mapped_column(Date)
    gate_site_ids: Mapped[list | None] = mapped_column(JSON)
    gate_control_keys: Mapped[list | None] = mapped_column(JSON)
    hold_note: Mapped[str | None] = mapped_column(String(400))  # a manual hold, whatever the checks say


class CopilotControl(TimestampedTenantMixin, Base):
    __tablename__ = "copilot_controls"
    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_copilot_control_key"),)

    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("copilot_workspaces.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(300))
    phase: Mapped[str] = mapped_column(String(10), default="pilot")
    position: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="open")
    note: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list | None] = mapped_column(JSON)
    checked_by: Mapped[str | None] = mapped_column(String(36))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)
