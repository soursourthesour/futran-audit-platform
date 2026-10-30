"""Claude refresh runs for laws and litigation (spec §25.2 RefreshRun, §25.3, §27.4).

ProposedChange (app.regmaster) holds what Claude proposes; `RefreshProposalMeta` keeps the pipeline's own
bookkeeping per proposal (litigation case, runs it was seen in, allowlist result, second review) so the shared
ProposedChange table stays as WS-A defined it. The older LawRefreshRun / RegulationProposal rows stay readable.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin

KINDS = ("law", "litigation")
CHECKS = {
    "law": ("new_laws", "amendments", "rules_guidance", "enforcement"),
    "litigation": ("new_cases", "case_updates"),
}


class RefreshRun(IdMixin, Base):
    __tablename__ = "refresh_runs"

    kind: Mapped[str] = mapped_column(String(12), default="law", index=True)  # law | litigation
    trigger: Mapped[str] = mapped_column(String(10), default="manual")  # manual | scheduled
    started_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    scope_mode: Mapped[str] = mapped_column(String(20), default="chosen")  # all | client_geographies | chosen
    jurisdiction_ids: Mapped[list] = mapped_column(JSON, default=list)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    source_set: Mapped[str] = mapped_column(String(12), default="official")  # official | with_secondary
    sources_read: Mapped[int] = mapped_column(Integer, default=0)
    records_compared: Mapped[int] = mapped_column(Integer, default=0)
    model_id: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued | running | completed | failed | capped
    error: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_cap_usd: Mapped[float | None] = mapped_column(Float)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    searches: Mapped[int] = mapped_column(Integer, default=0)
    responses: Mapped[list] = mapped_column(JSON, default=list)  # per jurisdiction: request summary, raw reply, outcome (§25.3 step 8)
    proposals_created: Mapped[int] = mapped_column(Integer, default=0)
    proposals_merged: Mapped[int] = mapped_column(Integer, default=0)
    alert_recipients: Mapped[str] = mapped_column(String(20), default="setting")  # setting | me
    alert_status: Mapped[str | None] = mapped_column(String(200))


class RefreshSetting(IdMixin, Base):
    """Run settings and schedule per kind (every 14 days once the Chief Auditor turns the schedule on in M3)."""

    __tablename__ = "refresh_settings"

    kind: Mapped[str] = mapped_column(String(12), unique=True)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    every_days: Mapped[int] = mapped_column(Integer, default=14)
    scope_mode: Mapped[str] = mapped_column(String(20), default="all")
    jurisdiction_ids: Mapped[list] = mapped_column(JSON, default=list)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    source_set: Mapped[str] = mapped_column(String(12), default="official")
    cost_cap_usd: Mapped[float] = mapped_column(Float, default=5.0)
    last_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class RefreshProposalMeta(Base):
    __tablename__ = "refresh_proposal_meta"

    proposed_change_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposed_changes.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12), default="law")
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("litigation_cases.id"), index=True)
    run_ids: Mapped[list] = mapped_column(JSON, default=list)  # every run that proposed it (duplicates merged)
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    off_allowlist: Mapped[bool] = mapped_column(Boolean, default=False)
    claude_confidence: Mapped[str | None] = mapped_column(String(8))  # what Claude said, before any downgrade
    needs_second_review: Mapped[bool] = mapped_column(Boolean, default=False)
    second_review_outcome: Mapped[str | None] = mapped_column(String(10))  # concur | object
    second_review_note: Mapped[str | None] = mapped_column(String(1000))
    assigned_reviewer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    edited_value: Mapped[object | None] = mapped_column(JSON)
    notify_clients: Mapped[bool] = mapped_column(Boolean, default=True)
    update_letters: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
