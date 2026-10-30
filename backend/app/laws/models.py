from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin


class MatrixVersion(IdMixin, Base):
    """One published state of the law matrix (an import, a manual edit, or accepted Claude proposals)."""

    __tablename__ = "matrix_versions"

    label: Mapped[str] = mapped_column(String(160))
    status_date: Mapped[date | None] = mapped_column(Date)
    source_filename: Mapped[str | None] = mapped_column(String(255))
    origin: Mapped[str] = mapped_column(String(20), default="import")  # import | manual | claude
    sources: Mapped[list | None] = mapped_column(JSON)
    warnings: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default="published")  # published | superseded
    published_by: Mapped[str | None] = mapped_column(String(36))
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Regulation(IdMixin, Base):
    """One law, regulation, executive action, pending bill or voluntary framework (spec §9.2)."""

    __tablename__ = "regulations"

    jurisdiction_id: Mapped[str] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
    matrix_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("matrix_versions.id"), index=True)
    last_seen_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("matrix_versions.id"))
    short_name: Mapped[str] = mapped_column(String(200))
    citation: Mapped[str | None] = mapped_column(String(300))
    category_text: Mapped[str | None] = mapped_column(String(120))
    feature: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str] = mapped_column(String(20))
    type_text: Mapped[str | None] = mapped_column(String(120))
    enforcer: Mapped[str | None] = mapped_column(String(300))
    trigger_text: Mapped[str | None] = mapped_column(Text)
    obligations_text: Mapped[str | None] = mapped_column(Text)
    developments_text: Mapped[str | None] = mapped_column(Text)
    most_affected: Mapped[str | None] = mapped_column(String(300))
    full_text: Mapped[str | None] = mapped_column(Text)
    effective_date_text: Mapped[str | None] = mapped_column(String(200))
    status_text: Mapped[str | None] = mapped_column(String(200))
    applies_to: Mapped[str] = mapped_column(String(10), default="deployer")  # deployer | developer | both
    verify_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    public_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    source_sheet: Mapped[str | None] = mapped_column(String(60))
    source_row_ref: Mapped[str | None] = mapped_column(String(80), index=True)
    import_key: Mapped[str | None] = mapped_column(String(200), index=True)  # stable workbook identity; kept through edits
    content_hash: Mapped[str | None] = mapped_column(String(64))  # hash of the workbook row this law last took
    origin: Mapped[str] = mapped_column(String(10), default="import")  # import | manual | claude
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("regulations.id"))
    retired_in_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("matrix_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    # regulatory master (spec §25.2): the approved LawVersion, and fields that do not change between versions
    current_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    binding: Mapped[bool | None] = mapped_column(Boolean)
    topics: Mapped[list | None] = mapped_column(JSON)
    region: Mapped[str | None] = mapped_column(String(20))  # us_federal | us_states | eu | india | uk | canada | other | framework
    reviewer_id: Mapped[str | None] = mapped_column(String(36))
    review_due_on: Mapped[date | None] = mapped_column(Date)
    refresh_every_days: Mapped[int | None] = mapped_column()
    watch: Mapped[bool | None] = mapped_column(Boolean)


class LawImportPreview(IdMixin, Base):
    """A parsed workbook awaiting Admin review (spec §10.1 rule 2)."""

    __tablename__ = "law_import_previews"

    payload: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("matrix_versions.id"))


class LawRefreshRun(IdMixin, Base):
    """One Admin-triggered Claude research run over a set of jurisdictions."""

    __tablename__ = "law_refresh_runs"

    jurisdiction_ids: Mapped[list] = mapped_column(JSON)
    requested_by: Mapped[str | None] = mapped_column(String(36))
    model: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default="running")  # running | completed | failed
    error: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class RegulationProposal(IdMixin, Base):
    """A change Claude proposes to the law matrix. Nothing changes until Admin accepts it."""

    __tablename__ = "regulation_proposals"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("law_refresh_runs.id"), index=True)
    jurisdiction_id: Mapped[str] = mapped_column(String(36), ForeignKey("jurisdictions.id"))
    regulation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("regulations.id"))
    change_type: Mapped[str] = mapped_column(String(10))  # add | update | retire
    proposed: Mapped[dict] = mapped_column(JSON)
    rationale: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | accepted | rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
