"""The client's AI system register and governance roles (spec §24, §27.2). organization_id is the client.

Named `RegisterSystem` (not `AISystem`, which is the engagement-scoped audit system) and `GovernanceRoleAssignment`
(not `RoleAssignment`, which holds platform permission roles); see the v0.6 plan's name-collision rulings.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.appendonly import append_only
from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin

TYPES = ("agent", "vendor_app", "embedded_feature", "foundation_model_api", "in_house_model", "genai_chat_tool")
SOURCING = ("vendor", "in_house", "contractor", "shadow")
STAGES = ("proposed", "in_development", "ready_for_go_live", "live", "retired")
AUTONOMY = ("suggest_only", "acts_with_approval", "autonomous")
DECISION_IMPACT = ("none", "informs", "consequential")
TRAINS_ON_DATA = ("yes", "no", "unknown")
CONSENT_BASIS = ("consent", "notice_only", "other_lawful_basis", "not_obtained", "na")
ROLE_STATUSES = ("assigned", "external", "no_such_person", "pending_committee", "not_applicable")
TESTER_TYPES = ("independent", "internal", "vendor")
HISTORY_TYPES = ("incident", "bias_test", "deployment_test", "impact_assessment", "notice_consent", "model_change", "approval", "training", "vendor_audit", "monitoring_review")
REQUIREMENT_STATUSES = ("met", "partly_met", "not_met", "not_applicable")
COMMITTEE_ROLES = ("chair", "secretary", "legal", "technical", "business", "external_advisor_non_voting")


class RegisterSystem(TimestampedTenantMixin, Base):
    """One AI app, agent, vendor tool, embedded feature or model the client uses (§24.5, §24.6)."""

    __tablename__ = "register_systems"

    reference: Mapped[str] = mapped_column(String(12))  # AIS-001, per client, never reused
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(24))
    sourcing: Mapped[str] = mapped_column(String(12))
    stage: Mapped[str] = mapped_column(String(20), default="proposed")
    purpose: Mapped[str | None] = mapped_column(Text)
    users_scope: Mapped[str | None] = mapped_column(String(10))  # role | named
    users_description: Mapped[str | None] = mapped_column(String(300))
    user_count: Mapped[int | None] = mapped_column(Integer)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    vendor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("vendors.id"))
    ai_provider: Mapped[str | None] = mapped_column(String(30))
    model_name: Mapped[str | None] = mapped_column(String(160))
    model_version: Mapped[str | None] = mapped_column(String(80))
    algorithm_type: Mapped[str | None] = mapped_column(String(30))
    hosting: Mapped[str | None] = mapped_column(String(30))
    vendor_trains_on_data: Mapped[str | None] = mapped_column(String(8))
    vendor_documents: Mapped[list] = mapped_column(JSON, default=list)
    autonomy: Mapped[str | None] = mapped_column(String(20))
    guardrail_policy_ref: Mapped[str | None] = mapped_column(String(120))
    agentassure_status: Mapped[str | None] = mapped_column(String(30))
    decision_impact: Mapped[str | None] = mapped_column(String(14))
    risk_tier: Mapped[int | None] = mapped_column(Integer)
    risk_tier_reason: Mapped[str | None] = mapped_column(String(300))
    company_wide: Mapped[bool] = mapped_column(Boolean, default=False)
    bias_next_due: Mapped[date | None] = mapped_column(Date)  # before the first test; afterwards the latest test sets it
    origin: Mapped[str] = mapped_column(String(14), default="manual")  # manual | csv | inventory | duplicate
    dedupe_key: Mapped[str | None] = mapped_column(String(260), index=True)  # vendor|product, for "Import from inventory"
    source_refs: Mapped[list] = mapped_column(JSON, default=list)  # ["tool:<id>", "use_case:<id>"]
    history_answers: Mapped[dict] = mapped_column(JSON, default=dict)  # the first-entry history questions (§27.2)
    live_since: Mapped[date | None] = mapped_column(Date)
    go_live_requested_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    go_live_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    go_live_approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    go_live_approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    retired_reason: Mapped[str | None] = mapped_column(Text)


class RegisterSystemLaw(TimestampedTenantMixin, Base):
    """A law that applies to a register system. Removing one needs the AI Compliance Officer (§24.3)."""

    __tablename__ = "register_system_laws"

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    regulation_id: Mapped[str] = mapped_column(String(36), ForeignKey("regulations.id"), index=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")  # suggested | manual
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | removal_pending | removed
    added_by: Mapped[str | None] = mapped_column(String(36))
    removal_requested_by: Mapped[str | None] = mapped_column(String(36))
    removal_reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(36))  # for removals


class RegisterSystemData(TimestampedTenantMixin, Base):
    """Data and consent for one register system (one row per system)."""

    __tablename__ = "register_system_data"
    __table_args__ = (UniqueConstraint("register_system_id", name="uq_register_system_data_system"),)

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    data_categories: Mapped[list] = mapped_column(JSON, default=list)
    data_subjects: Mapped[list] = mapped_column(JSON, default=list)
    consent_basis: Mapped[str | None] = mapped_column(String(20))
    consent_ref: Mapped[str | None] = mapped_column(String(300))
    consent_evidence_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    retention_period: Mapped[str | None] = mapped_column(String(80))
    cross_border: Mapped[str | None] = mapped_column(String(20))


class RegisterSystemAction(TimestampedTenantMixin, Base):
    """One action or tool an agent may use."""

    __tablename__ = "register_system_actions"

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    action_code: Mapped[str] = mapped_column(String(40))  # a checklist code, or "other"
    description: Mapped[str | None] = mapped_column(String(300))


class BiasTest(TimestampedTenantMixin, Base):
    __tablename__ = "bias_tests"

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    tested_on: Mapped[date] = mapped_column(Date)
    next_due: Mapped[date | None] = mapped_column(Date)
    tester_type: Mapped[str] = mapped_column(String(12))
    tester_name: Mapped[str | None] = mapped_column(String(200))
    method: Mapped[str | None] = mapped_column(String(300))
    groups_tested: Mapped[str | None] = mapped_column(String(300))
    result: Mapped[str] = mapped_column(String(12))  # passed | flagged | inconclusive
    result_text: Mapped[str | None] = mapped_column(Text)
    unknown_share: Mapped[float | None] = mapped_column(Float)  # 0–100, percent of records with unknown sex or race
    report_evidence_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    history_entry_id: Mapped[str | None] = mapped_column(String(36))


class GovernanceRoleAssignment(TimestampedTenantMixin, Base):
    """One governance role on one system, or company-wide when register_system_id is null (§24.2)."""

    __tablename__ = "governance_role_assignments"

    register_system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    role_id: Mapped[str] = mapped_column(String(36), index=True)  # RoleCatalog id (regulatory master)
    status: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    extra_user_ids: Mapped[list] = mapped_column(JSON, default=list)  # "add as a second person"
    external_party: Mapped[str | None] = mapped_column(String(200))
    external_contact: Mapped[str | None] = mapped_column(String(254))
    backup_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    target_date: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date | None] = mapped_column(Date)
    training_completed: Mapped[bool | None] = mapped_column(Boolean)
    has_authority_to_override: Mapped[bool | None] = mapped_column(Boolean)
    override: Mapped[bool] = mapped_column(Boolean, default=False)  # a system's own value replacing the company-wide one
    override_reason: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)


class GovernanceCommittee(TimestampedTenantMixin, Base):
    __tablename__ = "governance_committees"

    status: Mapped[str] = mapped_column(String(10), default="not_formed")  # not_formed | formed
    target_date: Mapped[date | None] = mapped_column(Date)
    formed_on: Mapped[date | None] = mapped_column(Date)
    charter_evidence_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    charter_note: Mapped[str | None] = mapped_column(String(300))
    meeting_cadence: Mapped[str | None] = mapped_column(String(20))
    approval_scope: Mapped[str | None] = mapped_column(String(40))
    recorded_by: Mapped[str | None] = mapped_column(String(36))


class CommitteeMember(TimestampedTenantMixin, Base):
    __tablename__ = "committee_members"

    committee_id: Mapped[str] = mapped_column(String(36), ForeignKey("governance_committees.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    external_party: Mapped[str | None] = mapped_column(String(200))
    committee_role: Mapped[str] = mapped_column(String(30))
    covers_role_id: Mapped[str | None] = mapped_column(String(36))


class ChangeLog(IdMixin, Base):
    """Field-level register history: old, new and why (§24.6). Every write also goes to the audit log."""

    __tablename__ = "change_log"

    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    register_system_id: Mapped[str | None] = mapped_column(String(36), index=True)  # the system the change belongs to, for its history
    field: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    batch_id: Mapped[str | None] = mapped_column(String(36))  # one bulk edit
    user_id: Mapped[str | None] = mapped_column(String(36))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class HistoryEntry(TimestampedTenantMixin, Base):
    """One event in a system's history log (§27.2)."""

    __tablename__ = "history_entries"

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    occurred_on: Mapped[date] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(10))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    requirement_ids: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    recorded_by: Mapped[str | None] = mapped_column(String(36))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class NoIncidentStatement(TimestampedTenantMixin, Base):
    """The system owner's "no incidents known" statement (§27.2). Kept with name and time; the auditor can test it."""

    __tablename__ = "no_incident_statements"

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    period_from: Mapped[date | None] = mapped_column(Date)
    statement: Mapped[str] = mapped_column(Text)
    signed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    signed_by_name: Mapped[str | None] = mapped_column(String(160))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime)


class RequirementStatus(TimestampedTenantMixin, Base):
    __tablename__ = "requirement_statuses"
    __table_args__ = (UniqueConstraint("register_system_id", "requirement_id", name="uq_requirement_status_system_req"),)

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(String(36), index=True)  # Requirement id (regulatory master)
    status: Mapped[str] = mapped_column(String(16), default="not_met")
    note: Mapped[str | None] = mapped_column(Text)
    history_entry_ids: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    checked_by: Mapped[str | None] = mapped_column(String(36))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)


# Evidence: never edited or deleted (§24.6, §27.7). Guards in the ORM and triggers in the database.
append_only(ChangeLog, "register change log")
