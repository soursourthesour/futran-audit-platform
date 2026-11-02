"""Continuous monitoring (spec §21 F3): the client's plan, the checks and their results.

`MonitorCheck` rows mirror the in-code registry (app.monitoring.registry) so results can point at a check by id.
`MonitorRun` is one run for one organisation; its (organization_id, run_key) is unique, which is how two schedulers that
overlap claim a run once. Monitoring never changes a signed report: it only writes these tables, notifications and the
follow-up records the client chooses to start.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TimestampedTenantMixin

PLANS = ("audit_only", "monitor", "monitor_plus")
MONITOR_PLANS = ("monitor", "monitor_plus")
STATUSES = ("healthy", "attention", "failed", "not_started")
SEVERITIES = ("high", "medium", "low")
APPLIES_TO = ("org", "system", "vendor", "tool", "commitment", "department", "policy")


class Subscription(TimestampedTenantMixin, Base):
    """The client's plan. `Organization.subscription_plan` carries the current plan for quick checks; this row keeps the
    dates and who set it. organization_id is the client."""

    __tablename__ = "subscriptions"

    plan: Mapped[str] = mapped_column(String(16))  # audit_only | monitor | monitor_plus
    start_on: Mapped[date | None] = mapped_column(Date)
    end_on: Mapped[date | None] = mapped_column(Date)
    next_review_on: Mapped[date | None] = mapped_column(Date)  # next Futran annual review, when Futran has agreed one
    set_by: Mapped[str | None] = mapped_column(String(36))
    note: Mapped[str | None] = mapped_column(String(300))


class MonitorCheck(IdMixin, Base):
    """One registered check. Platform-wide (not tenant data)."""

    __tablename__ = "monitor_checks"

    code: Mapped[str] = mapped_column(String(60), unique=True)
    description: Mapped[str] = mapped_column(String(200))
    frequency: Mapped[str] = mapped_column(String(20))
    rule: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(8))
    applies_to: Mapped[str] = mapped_column(String(12))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MonitorRun(TimestampedTenantMixin, Base):
    __tablename__ = "monitor_runs"
    __table_args__ = (UniqueConstraint("organization_id", "run_key", name="uq_monitor_run_key"),)

    run_key: Mapped[str] = mapped_column(String(80))  # monthly:2026-11 | sync:<connector run id> | manual:<id>
    trigger: Mapped[str] = mapped_column(String(10))  # monthly | sync | manual
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running | completed | failed
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    started_by: Mapped[str | None] = mapped_column(String(36))


class MonitorResult(TimestampedTenantMixin, Base):
    __tablename__ = "monitor_results"
    __table_args__ = (Index("ix_monitor_results_org_check_object", "organization_id", "check_id", "object_id"),)

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("monitor_runs.id"), index=True)
    check_id: Mapped[str] = mapped_column(String(36), ForeignKey("monitor_checks.id"), index=True)
    object_id: Mapped[str | None] = mapped_column(String(36))
    object_label: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12))  # healthy | attention | failed | not_started
    detail: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(String(30))  # start_reassessment | review | open | send_reminder | request_report
    action_link: Mapped[str | None] = mapped_column(String(300))
    register_system_id: Mapped[str | None] = mapped_column(String(36))
    run_at: Mapped[datetime] = mapped_column(DateTime)
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    action_taken: Mapped[str | None] = mapped_column(String(30))  # what the client started from this result
    action_taken_at: Mapped[datetime | None] = mapped_column(DateTime)
    action_taken_by: Mapped[str | None] = mapped_column(String(36))
