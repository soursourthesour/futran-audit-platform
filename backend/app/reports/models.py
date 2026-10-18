"""The audit report (template §12–13, spec §18.7–18.8). organization_id is the client."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

VERSIONS = {"v0.1": "Draft", "v0.2": "Lead review", "v1.0": "Client", "v1.1": "Final"}
FUTRAN_DECLARATIONS = {"lead_auditor": "Lead Auditor", "engagement_manager": "Engagement Manager", "quality_reviewer": "Quality Reviewer"}
CLIENT_DECLARATIONS = {"client_acknowledgement": "Client acknowledgement", "client_remediation_commitment": "Client remediation commitment"}
PRIORITIES = ("critical", "high", "medium", "low")


class ReportNarrative(TimestampedTenantMixin, Base):
    """The Lead Auditor's text for the executive summary (§12.1). One per engagement, edited until the report is final."""

    __tablename__ = "report_narratives"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), unique=True)
    most_significant_finding_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("findings.id"))
    most_significant_text: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[str | None] = mapped_column(Text)
    immediate_actions: Mapped[str | None] = mapped_column(Text)
    narrative: Mapped[str | None] = mapped_column(Text)  # overall assessment narrative (§11)


class Report(TimestampedTenantMixin, Base):
    """One generated version of the report. The body is frozen when generated; files are made from it."""

    __tablename__ = "reports"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    version: Mapped[str] = mapped_column(String(5))  # v0.1 | v0.2 | v1.0 | v1.1
    type: Mapped[str] = mapped_column(String(20), default="audit_report")
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | released | final
    body_md: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))  # what was reported, without version label or signatures
    docx_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    pdf_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    based_on_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("reports.id"))  # v1.0: the signed v0.2
    signed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime)
    correction_reason: Mapped[str | None] = mapped_column(Text)
    released_to_client_at: Mapped[datetime | None] = mapped_column(DateTime)
    released_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))


class Declaration(TimestampedTenantMixin, Base):
    """A declaration on one report version (§18.8), signed by typing a name, with the hash of what was declared."""

    __tablename__ = "declarations"
    __table_args__ = (UniqueConstraint("report_id", "kind", name="uq_declaration_kind"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("reports.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    typed_name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(160))
    text: Mapped[str] = mapped_column(Text)
    text_version: Mapped[str | None] = mapped_column(String(20))
    signed_at: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    document_sha256: Mapped[str] = mapped_column(String(64))
    commitment: Mapped[str | None] = mapped_column(String(10))  # plan | disputes (remediation commitment)
    disputed_finding_refs: Mapped[list] = mapped_column(JSON, default=list)


class RoadmapItem(TimestampedTenantMixin, Base):
    """§12.2 remediation roadmap. Refs R-01 and up, never reused."""

    __tablename__ = "roadmap_items"
    __table_args__ = (UniqueConstraint("engagement_id", "ref", name="uq_roadmap_ref"),)

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    ref: Mapped[str] = mapped_column(String(6))
    action: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(160))
    priority: Mapped[str] = mapped_column(String(10))
    target_date: Mapped[date | None] = mapped_column(Date)
    how_futran_can_help: Mapped[str | None] = mapped_column(Text)
    finding_ids: Mapped[list] = mapped_column(JSON, default=list)


class PublicSummary(TimestampedTenantMixin, Base):
    """The published bias audit summary (NYC LL144 and laws flagged public_summary). Impact ratios are entered by hand."""

    __tablename__ = "public_summaries"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), unique=True)
    ai_system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_systems.id"))
    tool_name: Mapped[str | None] = mapped_column(String(200))
    audit_date: Mapped[date | None] = mapped_column(Date)
    distribution_date: Mapped[date | None] = mapped_column(Date)
    data_source: Mapped[str | None] = mapped_column(Text)
    unknown_category_count: Mapped[int | None] = mapped_column(Integer)
    impact_ratios: Mapped[list] = mapped_column(JSON, default=list)  # [{category, group, selection_rate, impact_ratio}]
    evidence_file_ids: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
