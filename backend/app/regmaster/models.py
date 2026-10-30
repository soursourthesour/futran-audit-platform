"""Regulatory master (spec §25.2): versioned law content, the role catalogue, sources, client applicability,
intro letters and proposed changes.

`Regulation` (app.laws) stays the identity of a law. Everything that changes when a law is amended lives on a
`LawVersion`; `Regulation.current_version_id` points at the approved one. Requirement, ScopeTest, LawRoleMap and
CommitteeRule rows belong to one LawVersion, so an approved change copies them onto the next version and past
letters and audits keep pointing at the version they used.

ProposedChange.field_path grammar (shared with the refresh pipeline, WS-D):
  law.<field>               a LawVersion field (status, effective_on, scope_text, penalty_text, ...) or a Regulation
                            field (short_name, citation, type, binding, topics)
  requirement.<code>        new_value = full requirement dict (add or replace); null = remove
  role_map.<role_code>      new_value = {"level", "needed_by_stage", "requirement_codes"}; null = remove
  scope_test.<order>        new_value = {"question_text", "answer_type", "in_scope_rule", "prefill_from"}; null = remove
  committee.<type>          new_value = committee rule dict; null = remove
  new_law                   new_value = {"jurisdiction_code", "short_name", ..., "version": {...}}
  repeal                    new_value = {"status": "repealed", ...}
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin

STAGES = ["program_setup", "procurement", "development", "go_live", "ongoing", "yearly"]
VERSION_STATUSES = ["in_force", "in_force_phased", "enacted_not_in_force", "phased", "delayed", "guidance", "repealed"]
APPLIES_TO = ["developer", "deployer", "employer", "data_fiduciary", "provider"]
AI_TYPES = ["agent", "decision", "embedded", "genai", "all"]


class LawVersion(IdMixin, Base):
    """One approved (or draft) version of a law's content. Used by the law library (M1, M2), the applicability engine
    (M5), intro letters (law_versions_used), the refresh review queue (WS-D writes new versions on approval) and the
    register (WS-B reads required roles through LawRoleMap)."""

    __tablename__ = "law_versions"
    __table_args__ = (UniqueConstraint("regulation_id", "version_no", name="uq_law_version_no"),)

    regulation_id: Mapped[str] = mapped_column(String(36), ForeignKey("regulations.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="in_force")
    signed_on: Mapped[date | None] = mapped_column(Date)
    effective_on: Mapped[date | None] = mapped_column(Date)
    compliance_on: Mapped[date | None] = mapped_column(Date)
    effective_text: Mapped[str | None] = mapped_column(String(200))  # e.g. "Aug 2024 – Aug 2027" when phased
    scope_text: Mapped[str | None] = mapped_column(Text)
    applies_to: Mapped[list | None] = mapped_column(JSON)
    enforcer: Mapped[str | None] = mapped_column(String(300))
    private_right_of_action: Mapped[bool | None] = mapped_column(Boolean)
    penalty_text: Mapped[str | None] = mapped_column(Text)
    cure_period: Mapped[str | None] = mapped_column(String(200))
    exemptions_text: Mapped[str | None] = mapped_column(Text)
    removed_text: Mapped[str | None] = mapped_column(Text)
    litigation_text: Mapped[str | None] = mapped_column(Text)
    main_duty: Mapped[str | None] = mapped_column(String(300))  # one line for the intro letter's law table
    change_summary: Mapped[str | None] = mapped_column(Text)  # what this version changed (M2 version history)
    verify_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(36))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_ids: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))


class ScopeTest(IdMixin, Base):
    """A scope question asked by the applicability engine (M5) and edited on M1b/M2. `in_scope_rule` is
    {"equals": "yes"} | {"any": true} | {"in": [...]}; every rule marked `decisive` must pass for the law to apply."""

    __tablename__ = "scope_tests"

    law_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("law_versions.id"), index=True)
    order: Mapped[int] = mapped_column(Integer, default=1)
    question_text: Mapped[str] = mapped_column(String(500))
    answer_type: Mapped[str] = mapped_column(String(20), default="yes_no")  # yes_no | pick | text
    in_scope_rule: Mapped[dict | None] = mapped_column(JSON)
    decisive: Mapped[bool] = mapped_column(Boolean, default=True)
    prefill_from: Mapped[str | None] = mapped_column(String(40))  # client_geographies | decision_impact | built_or_bought | data_subjects
    note: Mapped[str | None] = mapped_column(String(500))


class RoleCatalog(IdMixin, Base):
    """The 21 governance roles (§24.1). Read by M4, the intro letter, the governance request (10a headline roles)
    and the client register (WS-B: GovernanceRoleAssignment.role_id)."""

    __tablename__ = "role_catalog"

    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))  # responsibility, shown in the intro letter
    level: Mapped[str] = mapped_column(String(10))  # company | system | agent
    default_stage: Mapped[str] = mapped_column(String(20))
    main_sources: Mapped[str | None] = mapped_column(String(300))
    extra_checks: Mapped[str | None] = mapped_column(String(40))  # oversight_confirmations | None
    headline_code: Mapped[str | None] = mapped_column(String(10))  # GovernanceCatalogItem code it feeds in 10a
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Source(IdMixin, Base):
    """An allowlisted source (§25.1 principle 2). The refresh pipeline (WS-D) only trusts `official` sources whose
    domain is listed; requirements cite one. `regulation_id` set = a law-specific page."""

    __tablename__ = "reg_sources"

    jurisdiction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
    regulation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("regulations.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(600))
    domain: Mapped[str | None] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="official")  # official | secondary
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))


class Requirement(IdMixin, Base):
    """A statutory requirement of one LawVersion (M2). Feeds the intro letter's rules by AI type, the register's
    requirements checklist (WS-B, RequirementStatus) and refresh impact (WS-D). Every row cites a source and quotes it."""

    __tablename__ = "requirements"

    law_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("law_versions.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    order: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(String(600))
    applies_to: Mapped[list | None] = mapped_column(JSON)
    needed_by_stage: Mapped[str | None] = mapped_column(String(20))
    evidence_text: Mapped[str | None] = mapped_column(String(400))
    role_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("role_catalog.id"))
    ai_types: Mapped[list | None] = mapped_column(JSON)
    citation: Mapped[str | None] = mapped_column(String(200))
    source_quote: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("reg_sources.id"))
    source_url: Mapped[str | None] = mapped_column(String(600))
    verify_flag: Mapped[bool] = mapped_column(Boolean, default=False)


class LawRoleMap(IdMixin, Base):
    """Which catalogue roles a LawVersion requires or recommends (M4 matrix). The applicability engine unions these
    over a client's in-scope laws; WS-B unions them over a register system's laws for the stage gate (§24.3)."""

    __tablename__ = "law_role_maps"
    __table_args__ = (UniqueConstraint("law_version_id", "role_id", name="uq_law_role"),)

    law_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("law_versions.id"), index=True)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("role_catalog.id"), index=True)
    level: Mapped[str] = mapped_column(String(12))  # required | recommended
    needed_by_stage: Mapped[str | None] = mapped_column(String(20))
    applies_to: Mapped[list | None] = mapped_column(JSON)  # e.g. ["developer"] when only developers must fill it
    requirement_ids: Mapped[list | None] = mapped_column(JSON)
    basis_text: Mapped[str | None] = mapped_column(String(300))  # "Art. 14, 26(2): deployer assigns oversight"
    verify_flag: Mapped[bool] = mapped_column(Boolean, default=False)


class CommitteeRule(IdMixin, Base):
    """A committee or program a law (or a framework, when `framework_code` is set) requires or recommends.
    Read by M4, the applicability engine and the intro letter's "Committee to form" section."""

    __tablename__ = "committee_rules"

    law_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("law_versions.id"), index=True)
    framework_code: Mapped[str | None] = mapped_column(String(30))
    committee_type: Mapped[str] = mapped_column(String(40))  # ai_governance_committee | risk_program | quality_management_system | sdf_setup | consequential_decision_rights
    level: Mapped[str] = mapped_column(String(12))  # required | recommended
    title: Mapped[str | None] = mapped_column(String(200))
    composition_text: Mapped[str | None] = mapped_column(Text)
    cadence: Mapped[str | None] = mapped_column(String(120))
    triggers_text: Mapped[str | None] = mapped_column(Text)
    condition_text: Mapped[str | None] = mapped_column(String(300))
    basis_text: Mapped[str | None] = mapped_column(String(300))
    items: Mapped[list | None] = mapped_column(JSON)


class ClientGeography(TimestampedTenantMixin, Base):
    """Where a client operates and on what basis (§25.2). Written by wizard step 2 and M5; read by the
    applicability engine."""

    __tablename__ = "client_geographies"
    __table_args__ = (UniqueConstraint("organization_id", "jurisdiction_id", "basis", name="uq_client_geo"),)

    jurisdiction_id: Mapped[str] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
    basis: Mapped[str] = mapped_column(String(12))  # office | employees | candidates | customers | data
    source: Mapped[str] = mapped_column(String(12), default="wizard")  # wizard | manual
    location_id: Mapped[str | None] = mapped_column(String(36))


class ClientLawApplicability(TimestampedTenantMixin, Base):
    """The applicability engine's answer for one client and one law (M5), with the reason. A manual override keeps
    its decision across re-runs. Read by the intro letter and WS-B to seed register laws."""

    __tablename__ = "client_law_applicability"
    __table_args__ = (UniqueConstraint("organization_id", "regulation_id", name="uq_client_law"),)

    regulation_id: Mapped[str] = mapped_column(String(36), ForeignKey("regulations.id"), index=True)
    law_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("law_versions.id"))
    in_scope: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_text: Mapped[str | None] = mapped_column(String(600))
    scope_answers: Mapped[dict | None] = mapped_column(JSON)
    override: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_by: Mapped[str | None] = mapped_column(String(36))  # null = the engine
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class IntroLetter(TimestampedTenantMixin, Base):
    """The intro letter to the client's Chief AI Compliance Officer (§25.5): draft -> approved -> sent. The PDF is a
    File; the letter is attached to the initiation package and shown on M5."""

    __tablename__ = "intro_letters"
    __table_args__ = (UniqueConstraint("organization_id", "version_no", name="uq_intro_letter_version"),)

    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"))
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | approved | sent
    body: Mapped[dict] = mapped_column(JSON)
    edited_text: Mapped[dict | None] = mapped_column(JSON)  # Chief Auditor's edits to the opening and closing text
    law_versions_used: Mapped[list | None] = mapped_column(JSON)
    changes: Mapped[list | None] = mapped_column(JSON)  # for version N+1: only what changed since vN
    file_id: Mapped[str | None] = mapped_column(String(36))
    approved_by: Mapped[str | None] = mapped_column(String(36))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_by: Mapped[str | None] = mapped_column(String(36))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("intro_letters.id"))


class ProposedChange(IdMixin, Base):
    """A change to the regulatory master that a person must approve (§25.1 principle 1). Written by Admin edits and
    bulk edits (M1a, M1b, M2, M4), Auditor suggestions, "Draft with Claude" (M1b) and the refresh pipeline (WS-D, M3);
    reviewed in M3. On approval `versioning.apply_change` writes the next LawVersion."""

    __tablename__ = "proposed_changes"

    refresh_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    origin: Mapped[str] = mapped_column(String(20), default="admin_edit")  # admin_edit | bulk_edit | auditor_suggestion | claude_draft | claude_refresh
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True)  # changes saved together (one form, one bulk edit)
    change_type: Mapped[str] = mapped_column(String(20))  # new_law | amendment | effective_date | new_rule | guidance | role_mapping | repeal | enforcement
    regulation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("regulations.id"), index=True)
    jurisdiction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jurisdictions.id"))
    base_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("law_versions.id"))
    field_path: Mapped[str] = mapped_column(String(120))
    old_value: Mapped[object | None] = mapped_column(JSON)
    new_value: Mapped[object | None] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(String(1000))
    reason: Mapped[str | None] = mapped_column(String(1000))
    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("reg_sources.id"))
    source_url: Mapped[str | None] = mapped_column(String(600))
    source_quote: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(8), default="high")  # high | medium | low
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | edited_approved | held | rejected | legal_review
    dedupe_key: Mapped[str | None] = mapped_column(String(200), index=True)
    proposed_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reviewer_id: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(String(1000))
    second_reviewer_id: Mapped[str | None] = mapped_column(String(36))
    second_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    applied_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("law_versions.id"))


class ChangeImpact(IdMixin, Base):
    """Which client, AI systems, roles and letters a ProposedChange touches (§25.3 step 5). Computed by
    `impact.compute_impacts`; shown in M3 (WS-D) and M5 ("Changes since letter vN")."""

    __tablename__ = "change_impacts"

    proposed_change_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposed_changes.id"), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    ai_system_ids: Mapped[list | None] = mapped_column(JSON)
    roles_affected: Mapped[list | None] = mapped_column(JSON)
    letter_update_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(String(600))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
