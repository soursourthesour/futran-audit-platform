"""Platform-wide reference data (not tenant-owned): jurisdictions and memberships."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin


class Jurisdiction(IdMixin, Base):
    __tablename__ = "jurisdictions"

    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    level: Mapped[str] = mapped_column(String(20))  # supranational | country | state | city
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
    iso_code: Mapped[str | None] = mapped_column(String(10))
    aliases: Mapped[list | None] = mapped_column(JSON)
    has_laws: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_notes: Mapped[dict | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36))


class JurisdictionMembership(IdMixin, Base):
    """A country's membership of a supranational group (e.g. Germany in the EU)."""

    __tablename__ = "jurisdiction_memberships"
    __table_args__ = (UniqueConstraint("member_id", "group_id", name="uq_membership"),)

    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("jurisdictions.id"), index=True)


class Framework(IdMixin, Base):
    __tablename__ = "frameworks"

    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(200))


class FrameworkControl(IdMixin, Base):
    __tablename__ = "framework_controls"
    __table_args__ = (UniqueConstraint("framework_id", "code", name="uq_framework_control"),)

    framework_id: Mapped[str] = mapped_column(String(36), ForeignKey("frameworks.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300))


class GovernanceCatalogItem(IdMixin, Base):
    """Governance documents, data-security documents and roles requested in screen 10a (spec §10.5)."""

    __tablename__ = "governance_catalog"

    kind: Mapped[str] = mapped_column(String(20))  # document | security_document | role
    code: Mapped[str] = mapped_column(String(10), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000))
    control_refs: Mapped[list] = mapped_column(JSON, default=list)
    conditional: Mapped[str | None] = mapped_column(String(30))
    optional: Mapped[bool] = mapped_column(Boolean, default=False)
    committee: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(default=0)


class DocumentCatalogItem(IdMixin, Base):
    """Pre-audit document request list (Template v1.0 Appendix A; spec §18.5)."""

    __tablename__ = "document_catalog"

    category: Mapped[int] = mapped_column()
    category_title: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(10), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(String(500))
    per_system: Mapped[bool] = mapped_column(Boolean, default=False)
    condition: Mapped[str | None] = mapped_column(String(20))
    template_section: Mapped[str | None] = mapped_column(String(10))
    order: Mapped[int] = mapped_column(default=0)


class DocumentTemplate(IdMixin, Base):
    """Versioned Markdown + Jinja templates for generated documents and emails (spec §9.3, §14)."""

    __tablename__ = "document_templates"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_template_version"),)

    key: Mapped[str] = mapped_column(String(60), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(default=1)
    body: Mapped[str] = mapped_column(String)
    package_item: Mapped[int | None] = mapped_column()
    requires_action: Mapped[str | None] = mapped_column(String(20))
    format: Mapped[str] = mapped_column(String(10), default="md")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))


class RiskMethodology(IdMixin, Base):
    __tablename__ = "risk_methodologies"

    version: Mapped[str] = mapped_column(String(10), unique=True)
    effective_date: Mapped[str | None] = mapped_column(String(10))
    factor_weights: Mapped[dict] = mapped_column(JSON)
    domain_weights_by_build_type: Mapped[dict] = mapped_column(JSON)
    config: Mapped[dict] = mapped_column(JSON)
    bands: Mapped[list] = mapped_column(JSON)
    knockout_rules: Mapped[list] = mapped_column(JSON)
