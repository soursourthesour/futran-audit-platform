"""Tracing and incident add-on (spec §27.3, §27.7; screens R7 and R8). organization_id is the client.

`AddonSubscription` is the client's request and, once the Executive Sponsor approves it, the active add-on.
`Incident` is the incident register; each regulator or provider notice it needs is one `IncidentDeadline` row,
created from the catalogue in app.tracing.deadlines. `ActionTrace` is one action an agent took (manual entry, CSV or
JSON import, or the GuardRail feed); `TraceImport` records each import or feed sync.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.appendonly import append_only
from app.core.clock import utcnow
from app.core.models import IdMixin, Base, TimestampedTenantMixin

ADDONS = ("tracing",)
PLANS = ("per_system", "tier_2_3", "enterprise")
SUBSCRIPTION_STATUSES = ("requested", "approved", "active", "declined", "cancelled")
SEVERITIES = ("low", "medium", "high", "serious")
# EU AI Act Art. 3(49): what makes an incident "serious"; "none" = not a serious incident
SERIOUS_KINDS = ("none", "death", "health", "critical_infrastructure", "fundamental_rights", "property_environment", "widespread_infringement")
INCIDENT_STATUSES = ("open", "contained", "closed")
DEADLINE_STATUSES = ("open", "done", "not_applicable", "withdrawn")
DECISIONS = ("allowed", "blocked", "escalated")
TRACE_SOURCES = ("manual", "csv", "json", "guardrail")


class AddonSubscription(TimestampedTenantMixin, Base):
    """A request for, and then the subscription to, the tracing add-on on chosen systems (§27.3 R8)."""

    __tablename__ = "addon_subscriptions"

    addon: Mapped[str] = mapped_column(String(20), default="tracing")
    ai_system_ids: Mapped[list] = mapped_column(JSON, default=list)  # register systems ticked in the request
    plan: Mapped[str] = mapped_column(String(12))
    trial: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_ends_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="requested", index=True)
    note: Mapped[str | None] = mapped_column(Text)  # note to Futran
    requested_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approver_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))  # the Executive Sponsor asked to approve
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_comment: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    opportunity_id: Mapped[str | None] = mapped_column(String(36))  # the Futran Sales opportunity the request opened


class Incident(TimestampedTenantMixin, Base):
    """One incident on a register system (§27.3, §27.7). Linked to the system's history log entry (§27.2)."""

    __tablename__ = "incidents"

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    code: Mapped[str] = mapped_column(String(12))  # INC-001 per client, never reused
    found_at: Mapped[datetime] = mapped_column(DateTime)  # when the client noticed it or was told; regulator clocks start here
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))
    serious_kind: Mapped[str] = mapped_column(String(24), default="none")
    risk_to_rights: Mapped[bool] = mapped_column(Boolean, default=False)  # EU AI Act Art. 26(5) / 79(1): use may present a risk
    cyber_incident: Mapped[bool] = mapped_column(Boolean, default=False)  # a cyber incident of a kind in CERT-In Annexure I
    ag_notice_received_on: Mapped[date | None] = mapped_column(Date)  # Colorado AG notice of violation, starts the 60-day cure period
    people_affected: Mapped[int | None] = mapped_column(Integer)
    cause: Mapped[str | None] = mapped_column(Text)
    containment: Mapped[str | None] = mapped_column(Text)
    fix: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")
    contained_on: Mapped[date | None] = mapped_column(Date)
    closed_on: Mapped[date | None] = mapped_column(Date)
    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    history_entry_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("history_entries.id"), index=True)
    trace_ids: Mapped[list] = mapped_column(JSON, default=list)  # actions the incident was raised from
    incident_lead_told_at: Mapped[datetime | None] = mapped_column(DateTime)


class IncidentDeadline(IdMixin, Base):
    """One notice an incident needs: to the AI provider, a market surveillance authority, CERT-In, or a cure period after a
    Colorado AG notice. Created and kept in step from the rule catalogue (app.tracing.deadlines)."""

    __tablename__ = "incident_deadlines"

    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    incident_id: Mapped[str] = mapped_column(String(36), ForeignKey("incidents.id"), index=True)
    rule_code: Mapped[str] = mapped_column(String(30))
    recipient: Mapped[str] = mapped_column(String(120))
    law: Mapped[str] = mapped_column(String(80))
    citation: Mapped[str] = mapped_column(String(160))
    quote: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(300))
    period_text: Mapped[str] = mapped_column(String(160))
    statutory: Mapped[bool] = mapped_column(Boolean, default=True)  # False: the law says "immediately" and the date is the platform's target
    binding: Mapped[bool] = mapped_column(Boolean, default=True)  # False: the duty is not yet in force on the day the incident was found
    binding_note: Mapped[str | None] = mapped_column(String(300))
    clock_start_at: Mapped[datetime] = mapped_column(DateTime)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(14), default="open", index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    done_by: Mapped[str | None] = mapped_column(String(36))
    reference: Mapped[str | None] = mapped_column(String(200))  # report or ticket number
    na_reason: Mapped[str | None] = mapped_column(Text)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TraceImport(IdMixin, Base):
    """One import of action traces (CSV or JSON file) or one GuardRail feed sync."""

    __tablename__ = "trace_imports"

    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    source: Mapped[str] = mapped_column(String(10))
    filename: Mapped[str | None] = mapped_column(String(255))
    added: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)  # already held (same event id)
    imported_by: Mapped[str | None] = mapped_column(String(36))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ActionTrace(IdMixin, Base):
    """One action an agent took or tried (§27.7). Append-only: traces are evidence and are never edited."""

    __tablename__ = "action_traces"

    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    session_id: Mapped[str | None] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(300))
    tool: Mapped[str | None] = mapped_column(String(120))
    data_touched: Mapped[str | None] = mapped_column(String(300))
    decision: Mapped[str] = mapped_column(String(10))
    policy_ref: Mapped[str | None] = mapped_column(String(120))
    approver: Mapped[str | None] = mapped_column(String(200))  # approver or note, as the source gives it
    agent_identity: Mapped[str | None] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(10), default="manual")
    external_id: Mapped[str | None] = mapped_column(String(120), index=True)  # the source's event id, to skip repeats
    import_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("trace_imports.id"))
    recorded_by: Mapped[str | None] = mapped_column(String(36))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# Evidence: never edited or deleted (§24.6, §27.7). Guards in the ORM and triggers in the database.
append_only(ActionTrace, "action trace")
