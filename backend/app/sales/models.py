"""Sales opportunities (spec §27.5, §27.7). organization_id is the client the opportunity is about."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin

TRIGGERS = ("unlock_request", "recommended_addon", "law_change", "new_law", "effective_date", "case", "manual", "policy_review", "regulatory_update", "impact_assessment",
            "renewal_audit", "discovery_finding")
TRIGGER_LABELS = {
    "unlock_request": "Unlock request", "recommended_addon": "Recommended add-on", "law_change": "Law change",
    "new_law": "New law", "effective_date": "Effective date", "case": "Litigation", "manual": "Added by hand",
    "policy_review": "Policy review request",  # wave 3 WS-I: "Request Futran review" in the policy builder
    "regulatory_update": "Regulatory update", "impact_assessment": "Impact assessment",  # wave 3 WS-H (§21 F4, F8)
    "renewal_audit": "Renewal audit",  # 11-03 F8: the periodic opportunity scan
    "discovery_finding": "Discovery finding",  # Release 2 R6a: G-05 manual discovery import (B5)
}
STAGES = ("new", "contacted", "proposal", "won", "lost")
SERVICE_KINDS = ("audit", "bias_audit", "readiness", "addon", "advisory", "training", "remediation", "other")
ACTIVITY_KINDS = ("call", "email", "meeting", "note", "proposal", "outcome")


class Opportunity(IdMixin, Base):
    __tablename__ = "opportunities"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(20), index=True)
    trigger_ref: Mapped[str | None] = mapped_column(String(80), index=True)  # case, law, change or subscription id
    service: Mapped[str] = mapped_column(String(200))
    service_kind: Mapped[str] = mapped_column(String(14), default="other")
    why_now: Mapped[str | None] = mapped_column(String(300))
    value: Mapped[int | None] = mapped_column(Integer)  # whole US dollars
    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    stage: Mapped[str] = mapped_column(String(10), default="new", index=True)
    next_step: Mapped[str | None] = mapped_column(String(300))
    system_ids: Mapped[list] = mapped_column(JSON, default=list)  # register systems the trigger touches
    system_types: Mapped[list] = mapped_column(JSON, default=list)  # what Sales sees instead of the systems themselves
    addon_status: Mapped[str | None] = mapped_column(String(12))  # recommended | requested | active | declined | cancelled
    needs_ca_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    ca_decision: Mapped[str | None] = mapped_column(String(10))  # approved | declined
    ca_approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    ca_approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    ca_note: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OpportunityActivity(IdMixin, Base):
    """Calls, emails, proposals, outcomes and decisions on one opportunity."""

    __tablename__ = "opportunity_activities"

    opportunity_id: Mapped[str] = mapped_column(String(36), ForeignKey("opportunities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # ACTIVITY_KINDS + stage | approval_requested | approved | declined
    summary: Mapped[str] = mapped_column(Text)
    by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OpportunityScanSetting(IdMixin, Base):
    """The Futran Admin's "Look for new opportunities every N days" (11-03 F8). One row for the platform; no row, or
    every_days null, means off (the default on upgrade)."""

    __tablename__ = "opportunity_scan_settings"

    key: Mapped[str] = mapped_column(String(20), unique=True, default="platform")
    every_days: Mapped[int | None] = mapped_column(Integer)  # 1-365; null = off
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime)  # when it was last switched on: the first scan looks back no further
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OpportunityScanRun(IdMixin, Base):
    """One opportunity scan. The unique run_key is the claim: a second scheduler that finds today's scheduled key taken
    runs nothing."""

    __tablename__ = "opportunity_scan_runs"
    __table_args__ = (UniqueConstraint("run_key", name="uq_opportunity_scan_run_key"),)

    run_key: Mapped[str] = mapped_column(String(80))  # scheduled:<date> | manual:<id>
    trigger: Mapped[str] = mapped_column(String(10))  # scheduled | manual
    since: Mapped[datetime] = mapped_column(DateTime)  # changes after this count as new
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running | completed | failed
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    found: Mapped[list] = mapped_column(JSON, default=list)  # ids of the opportunities this run opened
    errors: Mapped[list] = mapped_column(JSON, default=list)  # [{"client", "error"}] for clients that failed
    started_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
