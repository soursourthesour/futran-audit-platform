"""Commercial entities (spec §4.11 Order/OrderLine, B1, B2, B3) and the SM-13 handoff record.

Money is whole dollars and cents as floats rounded to 2 places (prices in the catalog are whole dollars). Fee and value
fields are never sent to Auditors: the routers check `view_engagement_fees` before any of them leaves the server.
The monitoring `Subscription` (F3) is extended in app.monitoring.models with additive, nullable columns.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin

ORDER_STATUSES = ("open", "active", "completed", "cancelled")
ENTITLEMENT_KEYS = ("ai_systems", "seats", "alert_packs", "litigation_briefings", "vault_gb", "retention_years", "legal_holds", "tracing_systems",
                    "agents_protected", "agent_actions_month", "approver_seats", "questionnaires_year", "advisor_hours", "trust_center", "api_access")
HARD_KEYS = ("api_access", "trust_center")  # feature on/off; every other key is a soft limit (user's default, R2-Q8)
CHANGE_ORDER_STATUSES = ("draft", "awaiting_futran_approval", "awaiting_client", "approved", "rejected")
ACTIVITIES = ("fieldwork", "report", "remediation_retest", "policy_drafting", "advisory", "incident_response", "litigation_support", "training", "other")
RETAINER_TYPES = ("incident_response", "fractional_officer", "compliance")


class Order(TimestampedTenantMixin, Base):
    """organization_id is the client."""

    __tablename__ = "orders"

    ref: Mapped[str] = mapped_column(String(12), unique=True)  # ORD-0001
    proposal_id: Mapped[str | None] = mapped_column(String(36), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(10), default="open")
    start_on: Mapped[date | None] = mapped_column(Date)
    end_on: Mapped[date | None] = mapped_column(Date)
    billing_contact: Mapped[str | None] = mapped_column(String(254))
    po_number: Mapped[str | None] = mapped_column(String(80))
    catalog_version: Mapped[int | None] = mapped_column(Integer)
    discount_recurring_pct: Mapped[float | None] = mapped_column(Float)
    discount_one_time_pct: Mapped[float | None] = mapped_column(Float)  # applies to every one-time line (proposal terms, rule P-3)


class OrderLine(TimestampedTenantMixin, Base):
    """One line of an order. Prices are frozen when the order is made and never change until renewal."""

    __tablename__ = "order_lines"

    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), index=True)
    catalog_code: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(String(300))
    deliverables_text: Mapped[str | None] = mapped_column(Text)
    qty: Mapped[float] = mapped_column(Float, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    periods_per_year: Mapped[int | None] = mapped_column(Integer)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    line_value: Mapped[float] = mapped_column(Float, default=0)  # year-1 value of the line
    start_on: Mapped[date | None] = mapped_column(Date)
    end_on: Mapped[date | None] = mapped_column(Date)
    engagement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(36), index=True)
    entitlement_key: Mapped[str | None] = mapped_column(String(30))
    included_quantities: Mapped[dict | None] = mapped_column(JSON)
    change_order_id: Mapped[str | None] = mapped_column(String(36))
    renewal_opportunity_id: Mapped[str | None] = mapped_column(String(36))


class Entitlement(TimestampedTenantMixin, Base):
    __tablename__ = "entitlements"

    subscription_id: Mapped[str] = mapped_column(String(36), ForeignKey("subscriptions.id"), index=True)
    key: Mapped[str] = mapped_column(String(30))
    limit: Mapped[float] = mapped_column(Float)
    source_order_line_id: Mapped[str | None] = mapped_column(String(36))
    alerted_90_at: Mapped[datetime | None] = mapped_column(DateTime)  # the 90% notice went out (once per entitlement)


class UsageRecord(TimestampedTenantMixin, Base):
    __tablename__ = "plan_usage_records"
    __table_args__ = (UniqueConstraint("organization_id", "key", "measured_on", name="uq_usage_org_key_day"),)

    key: Mapped[str] = mapped_column(String(30))
    measured_on: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[float] = mapped_column(Float)


class BillingExportRun(TimestampedTenantMixin, Base):
    """organization_id is the client for a per-client export, Futran's own org for an all-clients one."""

    __tablename__ = "billing_export_runs"

    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    client_id: Mapped[str | None] = mapped_column(String(36))  # null = every client
    run_by: Mapped[str | None] = mapped_column(String(36))
    run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    file_id: Mapped[str | None] = mapped_column(String(36))
    content: Mapped[str | None] = mapped_column(Text)  # the CSV as written (formula-safe)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="completed")


class EngagementCommercial(TimestampedTenantMixin, Base):
    __tablename__ = "engagement_commercials"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), unique=True)
    order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    fee_total: Mapped[float] = mapped_column(Float, default=0)
    milestones: Mapped[list] = mapped_column(JSON, default=list)  # [{label, trigger, pct, amount, status, billed_on}]


class ChangeOrder(TimestampedTenantMixin, Base):
    __tablename__ = "change_orders"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    ref: Mapped[str] = mapped_column(String(10))  # CO-001 within the engagement
    reason: Mapped[str] = mapped_column(Text)
    lines: Mapped[list] = mapped_column(JSON, default=list)  # [{code, description, qty, unit_price, list_price, value}]
    raised_by: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str | None] = mapped_column(String(20))  # add_system | add_jurisdiction | extra_documents | extra_readout | extra_vendors
    status: Mapped[str] = mapped_column(String(24), default="draft")  # draft = waiting for the Engagement Manager
    em_approved_by: Mapped[str | None] = mapped_column(String(36))
    em_approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    needs_price_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    futran_approved_by: Mapped[str | None] = mapped_column(String(36))
    futran_approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    client_approved_by: Mapped[str | None] = mapped_column(String(36))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_note: Mapped[str | None] = mapped_column(Text)
    scope_change_ref: Mapped[str | None] = mapped_column(String(80))  # system_addition:<id> | the scope record it changed
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)


class TimeEntry(TimestampedTenantMixin, Base):
    """organization_id is the client charged, or Futran's own org for internal time."""

    __tablename__ = "time_entries"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    hours_bank_id: Mapped[str | None] = mapped_column(String(36), index=True)
    retainer_id: Mapped[str | None] = mapped_column(String(36), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    hours: Mapped[float] = mapped_column(Float)
    activity: Mapped[str] = mapped_column(String(24))
    billable: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | submitted | approved | returned
    approved_by: Mapped[str | None] = mapped_column(String(36))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)


class HoursBank(TimestampedTenantMixin, Base):
    __tablename__ = "hours_banks"

    order_line_id: Mapped[str | None] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20), default="M-13")
    label: Mapped[str] = mapped_column(String(120), default="Advisor hours bank")
    hours_purchased: Mapped[float] = mapped_column(Float)
    expires_on: Mapped[date | None] = mapped_column(Date)
    alerted_80_at: Mapped[datetime | None] = mapped_column(DateTime)


class Retainer(TimestampedTenantMixin, Base):
    __tablename__ = "retainers"

    order_line_id: Mapped[str | None] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(20))  # incident_response | fractional_officer | compliance
    monthly_fee: Mapped[float] = mapped_column(Float, default=0)
    hourly_rate: Mapped[float | None] = mapped_column(Float)
    monthly_hours: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(10), default="standing")  # standing | activated | ended
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    activated_by: Mapped[str | None] = mapped_column(String(36))
    incident_engagement_id: Mapped[str | None] = mapped_column(String(36))
    officer_user_id: Mapped[str | None] = mapped_column(String(36))  # X-01: the Futran person holding the client role (rule I-3)


class StandardCost(IdMixin, Base):
    """Cost per hour by Futran role, entered by the Futran Admin (user's default for R2-Q9). Platform-wide."""

    __tablename__ = "standard_costs"

    role: Mapped[str] = mapped_column(String(40))
    cost_per_hour: Mapped[float] = mapped_column(Float)
    effective_from: Mapped[date] = mapped_column(Date)
    set_by: Mapped[str | None] = mapped_column(String(36))
    set_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Handoff(TimestampedTenantMixin, Base):
    """SM-13: what the won proposal created, for the Sales Officer and Chief Auditor to confirm. organization_id is the client."""

    __tablename__ = "handoffs"

    opportunity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    acceptance_id: Mapped[str | None] = mapped_column(String(36))
    order_id: Mapped[str | None] = mapped_column(String(36))
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{kind, label, details, status, next_owner, link, ref_id}]
    accepted_by: Mapped[dict | None] = mapped_column(JSON)  # {name, title, at, po_number}
    year1_value: Mapped[float] = mapped_column(Float, default=0)
    needs_separate_team: Mapped[list] = mapped_column(JSON, default=list)  # line codes under rule I-2 / I-3
    team: Mapped[dict] = mapped_column(JSON, default=dict)  # {account_owner_id, separate_team_user_ids, note}
    status: Mapped[str] = mapped_column(String(12), default="awaiting")  # awaiting | confirmed
    independence_confirmed_by: Mapped[str | None] = mapped_column(String(36))
    independence_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_by: Mapped[str | None] = mapped_column(String(36))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
