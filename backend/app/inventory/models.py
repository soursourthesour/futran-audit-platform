"""AI inventory: tools, use cases, usage and named users (spec §9.5, §11; schematic D13). organization_id is the client."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class AITool(TimestampedTenantMixin, Base):
    """One tool as used under one kind of account (ChatGPT on personal free accounts is a different row from ChatGPT Enterprise)."""

    __tablename__ = "ai_tools"

    vendor: Mapped[str] = mapped_column(String(120))
    product: Mapped[str] = mapped_column(String(120))
    plan: Mapped[str | None] = mapped_column(String(80))
    account_type: Mapped[str] = mapped_column(String(16), default="unknown")  # enterprise | team | personal_paid | personal_free | unknown
    sso: Mapped[bool | None] = mapped_column(Boolean)
    training_on_inputs: Mapped[str] = mapped_column(String(8), default="unknown")  # yes | no | unknown
    retention_terms: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(String(16), default="unreviewed")  # unreviewed | approved | not_approved
    source: Mapped[str] = mapped_column(String(12), default="manual")  # manual | attestation
    declared_count: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(8), default="tool", server_default="tool")  # tool | agent (acts for the user, not only answers)


class UseCase(TimestampedTenantMixin, Base):
    __tablename__ = "use_cases"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    department_id: Mapped[str] = mapped_column(String(36), ForeignKey("departments.id"), index=True)
    purpose: Mapped[str | None] = mapped_column(Text)
    tool_ids: Mapped[list] = mapped_column(JSON, default=list)
    data_categories: Mapped[list] = mapped_column(JSON, default=list)  # pii | phi | client | confidential | none
    decision_impact: Mapped[str | None] = mapped_column(String(14))  # none | informs | consequential
    proposed_tier: Mapped[int | None] = mapped_column(Integer)
    final_tier: Mapped[int | None] = mapped_column(Integer)
    final_tier_rationale: Mapped[str | None] = mapped_column(Text)
    final_tier_set_by: Mapped[str | None] = mapped_column(String(36))
    final_tier_set_at: Mapped[datetime | None] = mapped_column(DateTime)
    aedt_determination: Mapped[str | None] = mapped_column(String(14))  # in_scope | out_of_scope | undetermined
    owner_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(14), default="draft")  # draft | submitted | dept_approved | returned
    returned_comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_by: Mapped[str | None] = mapped_column(String(36))
    editor_ids: Mapped[list] = mapped_column(JSON, default=list)  # everyone who edited it: none of them may approve it
    created_from_attestation_id: Mapped[str | None] = mapped_column(String(36))


class UsageRecord(TimestampedTenantMixin, Base):
    __tablename__ = "usage_records"

    use_case_id: Mapped[str] = mapped_column(String(36), ForeignKey("use_cases.id"), index=True)
    role_name: Mapped[str] = mapped_column(String(120))
    headcount: Mapped[int | None] = mapped_column(Integer)
    frequency: Mapped[str | None] = mapped_column(String(20))


class NamedUser(TimestampedTenantMixin, Base):
    """A named person who uses a Tier 2–3 use case. Linked to the use case directly (spec ties it to UsageRecord)."""

    __tablename__ = "named_users"

    use_case_id: Mapped[str] = mapped_column(String(36), ForeignKey("use_cases.id"), index=True)
    person_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    role_name: Mapped[str | None] = mapped_column(String(120))
    oversight_role: Mapped[str | None] = mapped_column(String(200))
    training_complete: Mapped[bool | None] = mapped_column(Boolean)
    policy_acknowledged: Mapped[bool | None] = mapped_column(Boolean)
    oversight_role_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    unable_reason: Mapped[str | None] = mapped_column(Text)  # Department Lead: this person cannot confirm (§8a)
    unable_marked_by: Mapped[str | None] = mapped_column(String(36))


class NamedUserLink(TimestampedTenantMixin, Base):
    """A personal, no-login confirmation link (D13). Only the token's hash is stored."""

    __tablename__ = "named_user_links"

    named_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("named_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    training_complete: Mapped[bool | None] = mapped_column(Boolean)
    policy_acknowledged: Mapped[bool | None] = mapped_column(Boolean)
    oversight_role_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    unable_reason: Mapped[str | None] = mapped_column(Text)


class InventorySnapshot(TimestampedTenantMixin, Base):
    """The client's inventory and pre-fill answers, frozen when sign-off 4 is approved (spec §7 stage 4)."""

    __tablename__ = "inventory_snapshots"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    locked_at: Mapped[datetime] = mapped_column(DateTime)
    sign_off_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sign_offs.id"))
    payload: Mapped[dict] = mapped_column(JSON)


class SnapshotAddendum(TimestampedTenantMixin, Base):
    """Something that arrived after the lock (a late named-user confirmation). Appended, never merged into the snapshot."""

    __tablename__ = "snapshot_addenda"

    snapshot_id: Mapped[str] = mapped_column(String(36), ForeignKey("inventory_snapshots.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
