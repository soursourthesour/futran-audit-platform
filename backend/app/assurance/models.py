"""Agent Assure records and AgentWarden licence sync (Release 2 B9, screen G-09). Agent Assure and AgentWarden stay
separate products: the platform records their results and licences against each agent in the client's register.
organization_id is the client throughout, except on `AssuranceCheckItem`, which is Futran's reference list."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin

OUTCOMES = ("pass", "conditional", "fail")
CHECK_RESULTS = ("pass", "conditional", "fail", "not_run")
SEVERITIES = ("low", "medium", "high", "critical")
DEPLOYMENTS = ("saas", "vpc")
CHECK_POSITIONS = 15


class AssuranceCheckItem(IdMixin, Base):
    """One of the 15 points of the Agent Assure pre-deploy check. The text is blank until FATF supplies the Agent Assure
    methodology (user's default for R2-Q7); the Futran Admin or Chief Auditor edits it. Runs keep the text they used."""

    __tablename__ = "assurance_check_items"

    position: Mapped[int] = mapped_column(Integer, unique=True)  # 1-15
    text: Mapped[str | None] = mapped_column(String(400))
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AssuranceRun(TimestampedTenantMixin, Base):
    """An Agent Assure record for one agent and release (spec B9 `AssuranceRun`; ai_system_id is the register system)."""

    __tablename__ = "assurance_runs"

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    release_ref: Mapped[str] = mapped_column(String(60))
    model_ref: Mapped[str | None] = mapped_column(String(200))  # model and version tested; defaults to the register's at the time
    eval_set_version: Mapped[str | None] = mapped_column(String(40))
    eval_set_size: Mapped[int | None] = mapped_column(Integer)
    eval_set_owner: Mapped[str | None] = mapped_column(String(160))
    checks: Mapped[list] = mapped_column(JSON, default=list)  # [{position, item, result, note, due}]
    redteam: Mapped[list] = mapped_column(JSON, default=list)  # [{scenario, outcome, severity}]
    outcome: Mapped[str] = mapped_column(String(12))  # pass | conditional | fail
    letter_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    signed_by: Mapped[str | None] = mapped_column(String(160))
    signed_on: Mapped[date | None] = mapped_column(Date)
    next_due_trigger: Mapped[str | None] = mapped_column(String(36), ForeignKey("reassessment_triggers.id"))  # the trigger that asks for re-certification
    next_due_reason: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WardenLicenceSnapshot(TimestampedTenantMixin, Base):
    """AgentWarden licence status of one agent, from a sync (CSV until the AgentWarden API exists)."""

    __tablename__ = "warden_licence_snapshots"
    __table_args__ = (UniqueConstraint("organization_id", "register_system_id", "sync_id", name="uq_warden_snapshot"),)

    register_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("register_systems.id"), index=True)
    sync_id: Mapped[str] = mapped_column(String(36), index=True)  # one sync = one file
    agent_label: Mapped[str] = mapped_column(String(160))  # as AgentWarden named it
    autonomy: Mapped[str | None] = mapped_column(String(30))
    actions_month: Mapped[int] = mapped_column(Integer, default=0)
    actions_included: Mapped[int | None] = mapped_column(Integer)
    approvers: Mapped[int] = mapped_column(Integer, default=0)
    deployment: Mapped[str | None] = mapped_column(String(10))  # saas | vpc
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
