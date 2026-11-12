"""Sales opportunities (spec §27.5, §27.7). organization_id is the client the opportunity is about."""
from datetime import datetime

from datetime import date

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    # Release 2 §4.2: automatic triggers from G-01 (R5), G-02 (R5) and G-05 (R6a, which added discovery_finding first)
    "renewal_due": "Renewal due", "change_order": "Change order", "entitlement_limit": "Plan limit reached", "discovery_finding": "Discovery finding",
}
TRIGGERS = tuple(dict.fromkeys((*TRIGGERS, "renewal_due", "change_order", "entitlement_limit", "discovery_finding")))
# Release 2 §4.2. "contacted" is the v0.6 stage some existing opportunities hold: still accepted and shown, no longer offered.
PIPELINE_STAGES = ("new", "qualified", "scoping", "proposal", "negotiation")
STAGES = (*PIPELINE_STAGES, "won", "lost", "on_hold", "contacted")
OPEN_STAGES = (*PIPELINE_STAGES, "on_hold", "contacted")
STAGE_LABELS = {"new": "New", "qualified": "Qualified", "scoping": "Scoping", "proposal": "Proposal", "negotiation": "Negotiation", "won": "Won", "lost": "Lost",
                "on_hold": "On hold", "contacted": "Contacted"}
# Weighted pipeline (SM-01): stage probability × value. Futran's working assumption; on hold and lost count for nothing.
STAGE_PROBABILITY = {"new": 0.1, "contacted": 0.1, "qualified": 0.25, "scoping": 0.4, "proposal": 0.6, "negotiation": 0.8, "won": 1.0, "lost": 0.0, "on_hold": 0.0}
LOST_REASONS = {"price": "Price", "timing": "Timing", "competitor": "Competitor", "no_budget": "No budget", "no_decision": "No decision", "other": "Other"}
SOURCES = {"outbound_call": "Outbound call", "email_campaign": "Email campaign", "linkedin": "LinkedIn", "inbound_web": "Inbound web", "referral_partner": "Referral partner",
           "event": "Event", "existing_client": "Existing client", "auto_trigger": "Automatic trigger"}
SEGMENTS = {"staffing_hr": "Staffing / HR", "enterprise_bfsi_health_ins": "Enterprise (BFSI, health, insurance)", "agents_copilot": "Agents and Copilot"}
# SM-03 "Trigger": the buying event, from the scoping questionnaire's Section A list
TRIGGER_EVENTS = {"ll144_due": "LL144 audit due", "new_state_law": "New state law", "lawsuit_worry": "Lawsuit worry", "customer_rfp": "Customer / RFP asked",
                  "agents_rollout": "Agents or Copilot rollout", "shadow_ai": "Shadow AI", "m_and_a": "M&A"}
PRODUCTS = {"audit": "Audit", "monitor": "Monitor", "ll144": "LL144", "agent_assure": "Agent Assure", "agentwarden": "AgentWarden", "copilot": "Copilot readiness",
            "eu_ai_act": "EU AI Act", "policy": "Policy drafting", "training": "Training", "other": "Other services"}
CONTACT_ROLES = {"economic_buyer": "Economic buyer", "champion": "Champion", "technical": "Technical", "legal": "Legal", "procurement": "Procurement"}
INDUSTRIES = ("Staffing & recruitment", "BFSI", "Healthcare", "Insurance", "Pharma & life sciences", "Property management", "Public sector", "Other")
SIZE_BANDS = ("Up to 250", "251–1,000", "1,000+")
STALE_DAYS = 14
SERVICE_KINDS = ("audit", "bias_audit", "readiness", "addon", "advisory", "training", "remediation", "other")
ACTIVITY_KINDS = ("call", "email", "meeting", "note", "task", "proposal", "outcome")
WORK_KINDS = ("call", "email", "meeting", "note", "task", "proposal", "outcome")  # what a person logs; the rest are the system's


class Opportunity(IdMixin, Base):
    __tablename__ = "opportunities"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(20), index=True)  # "manual" for logged ones, else the automatic trigger
    trigger_ref: Mapped[str | None] = mapped_column(String(80), index=True)  # case, law, change or subscription id
    service: Mapped[str] = mapped_column(String(200))
    service_kind: Mapped[str] = mapped_column(String(14), default="other")
    why_now: Mapped[str | None] = mapped_column(String(300))
    value: Mapped[int | None] = mapped_column(Integer)  # whole US dollars
    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    # String(10) on purpose: "negotiation" has 11 characters, which SQLite stores as is; widening the column would rebuild a
    # table other tables reference, which fails on existing data.
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
    # Release 2 §4.11 (all nullable: existing opportunities keep their values and read as before)
    name: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str | None] = mapped_column(String(20))  # SOURCES
    partner_id: Mapped[str | None] = mapped_column(String(36), index=True)  # G-11 partner, when referred
    segment: Mapped[str | None] = mapped_column(String(30))  # SEGMENTS
    trigger_event: Mapped[str | None] = mapped_column(String(20))  # TRIGGER_EVENTS
    products_of_interest: Mapped[list | None] = mapped_column(JSON)
    close_date: Mapped[date | None] = mapped_column(Date)
    next_step_due: Mapped[date | None] = mapped_column(Date)
    lost_reason: Mapped[str | None] = mapped_column(String(20))  # LOST_REASONS
    lost_note: Mapped[str | None] = mapped_column(String(500))
    bant: Mapped[dict | None] = mapped_column(JSON)  # {budget, authority, need, timeline}
    competitors: Mapped[list | None] = mapped_column(JSON)
    independence_flag: Mapped[bool | None] = mapped_column(Boolean)
    independence_reason: Mapped[str | None] = mapped_column(String(300))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # stale after STALE_DAYS without one

    @property
    def est_value(self) -> int | None:  # spec §4.11 name for the v0.6 value column
        return self.value


class OpportunityContact(IdMixin, Base):
    """People on the deal (spec §4.11). Futran's sales data: never visible to client users. On a win the handoff
    (R5) copies them to the client's contacts."""

    __tablename__ = "opportunity_contacts"

    opportunity_id: Mapped[str] = mapped_column(String(36), ForeignKey("opportunities.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    title: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254), index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    contact_role: Mapped[str | None] = mapped_column(String(20))  # CONTACT_ROLES
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class OpportunityActivity(IdMixin, Base):
    """Calls, emails, proposals, outcomes and decisions on one opportunity."""

    __tablename__ = "opportunity_activities"

    opportunity_id: Mapped[str] = mapped_column(String(36), ForeignKey("opportunities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # ACTIVITY_KINDS + stage | approval_requested | approved | declined
    summary: Mapped[str] = mapped_column(Text)
    by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Release 2 §4.3 rule 4 and §4.11 Activity
    outcome: Mapped[str | None] = mapped_column(String(500))
    next_step: Mapped[str | None] = mapped_column(String(300))
    due_on: Mapped[date | None] = mapped_column(Date)  # a task's due date
    done_at: Mapped[datetime | None] = mapped_column(DateTime)  # a task ticked off
    mail_thread_id: Mapped[str | None] = mapped_column(String(36), index=True)  # an email sent from the rep's mailbox: its replies thread back
    mail_send_id: Mapped[str | None] = mapped_column(String(36))
    to_addresses: Mapped[list | None] = mapped_column(JSON)


Activity = OpportunityActivity  # the spec §4.11 name


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
