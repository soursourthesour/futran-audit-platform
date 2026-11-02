"""Bias test runs and GenAI guardrail test runs (spec §21 F11). organization_id is the client."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class BiasTestRun(TimestampedTenantMixin, Base):
    """One calculation on one applicant data file. The results are kept; the raw file is deleted at the end of the
    engagement retention period unless the client chose to keep it."""

    __tablename__ = "bias_test_runs"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    ai_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_systems.id"), index=True)
    dataset_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))  # null once the raw rows are deleted
    dataset_filename: Mapped[str | None] = mapped_column(String(255))
    dataset_sha256: Mapped[str | None] = mapped_column(String(64))
    data_source: Mapped[str | None] = mapped_column(Text)  # source and explanation of the data, for the public summary (§ 5-303)
    method: Mapped[str] = mapped_column(String(14))  # selection_rate | scoring_rate
    categories: Mapped[list] = mapped_column(JSON, default=list)  # sex, race, intersectional
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)  # threshold, small_share, exclude_small
    unknown_count: Mapped[int | None] = mapped_column(Integer)
    excluded_categories: Mapped[list] = mapped_column(JSON, default=list)
    lowest_impact_ratio: Mapped[float | None] = mapped_column()
    run_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    run_at: Mapped[datetime | None] = mapped_column(DateTime)
    library_version: Mapped[str] = mapped_column(String(80))
    keep_raw_data: Mapped[bool | None] = mapped_column(Boolean)  # the client opted to keep the raw rows
    raw_delete_on: Mapped[date | None] = mapped_column(Date)
    raw_deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    public_summary_at: Mapped[datetime | None] = mapped_column(DateTime)  # "Use in public summary"
    public_summary_by: Mapped[str | None] = mapped_column(String(36))
    bias_test_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("bias_tests.id"))  # "Record as bias test"
    finding_ids: Mapped[list] = mapped_column(JSON, default=list)  # draft findings raised from this run


class GuardrailTestRun(TimestampedTenantMixin, Base):
    """A run of Futran's prompt set against a client's GenAI system (Phase 4). Only the in-process fake runs unless
    GUARDRAIL_TESTS_LIVE=true and the client's written permission is recorded. Results are suggestions for §8.1.05 and
    checklist 8.4 until an auditor accepts them."""

    __tablename__ = "guardrail_test_runs"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    ai_system_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_systems.id"), index=True)
    prompt_set_version: Mapped[str] = mapped_column(String(20))
    adapter: Mapped[str] = mapped_column(String(10), default="fake")  # fake | live
    endpoint_label: Mapped[str | None] = mapped_column(String(300))
    permission_note: Mapped[str | None] = mapped_column(Text)
    permission_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    results: Mapped[list] = mapped_column(JSON, default=list)  # [{id, category, passed, reason, excerpt}]
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="suggested")  # suggested | accepted | rejected
    run_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    run_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)
