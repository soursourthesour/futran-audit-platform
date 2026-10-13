from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class Engagement(TimestampedTenantMixin, Base):
    """One audit of one client for one period. organization_id == client_id (the client tenant)."""

    __tablename__ = "engagements"

    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(30), default="initial_assessment")
    audit_ref: Mapped[str | None] = mapped_column(String(30), unique=True)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    letter_due: Mapped[date | None] = mapped_column(Date)
    report_due: Mapped[date | None] = mapped_column(Date)
    draft_report_target: Mapped[date | None] = mapped_column(Date)
    final_report_target: Mapped[date | None] = mapped_column(Date)
    fieldwork_start: Mapped[date | None] = mapped_column(Date)
    methodology_version: Mapped[str] = mapped_column(String(80), default="Futran AI Audit Procedure v1.0")
    frameworks: Mapped[list | None] = mapped_column(JSON)
    business_processes: Mapped[str | None] = mapped_column(Text)
    data_environments: Mapped[list | None] = mapped_column(JSON)
    geographic_scope: Mapped[str | None] = mapped_column(Text)
    exclusions: Mapped[str | None] = mapped_column(Text)
    systems_excluded: Mapped[str | None] = mapped_column(Text)
    planned_systems: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    stage: Mapped[int] = mapped_column(Integer, default=1)
    submitted_by: Mapped[str | None] = mapped_column(String(36))
    approved_by: Mapped[str | None] = mapped_column(String(36))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    returned_comment: Mapped[str | None] = mapped_column(Text)
    overall_rating: Mapped[str | None] = mapped_column(String(12))
    retention_years: Mapped[int | None] = mapped_column(Integer)
    wizard_state: Mapped[dict | None] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class EngagementTeam(TimestampedTenantMixin, Base):
    __tablename__ = "engagement_team"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(30))  # engagement_manager | chief_auditor | auditor | qa_reviewer | legal_reviewer
    conflict_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ClientRequirement(TimestampedTenantMixin, Base):
    """A law or framework in scope for a client (spec §9.2). organization_id is the client."""

    __tablename__ = "client_requirements"

    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    regulation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("regulations.id"), index=True)
    source: Mapped[str] = mapped_column(String(20), default="auto")  # auto | manual | futran_default
    reason_text: Mapped[str | None] = mapped_column(Text)
    in_scope: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    free_text: Mapped[str | None] = mapped_column(Text)


class ClientLocation(TimestampedTenantMixin, Base):
    """A client site (spec §9.2). Its resolved jurisdictions drive law suggestions."""

    __tablename__ = "client_locations"

    site_name: Mapped[str] = mapped_column(String(120))
    street: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(120))
    subdivision_code: Mapped[str | None] = mapped_column(String(12))  # ISO 3166-2, e.g. US-NY
    country_code: Mapped[str] = mapped_column(String(2))
    employees_at_site: Mapped[int | None] = mapped_column(Integer)
    in_scope: Mapped[bool] = mapped_column(Boolean, default=True)
    jurisdiction_ids: Mapped[list] = mapped_column(JSON, default=list)  # city → state → country → regional groups


class ScopeItem(TimestampedTenantMixin, Base):
    __tablename__ = "scope_items"

    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    regulation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("regulations.id"))
    framework_id: Mapped[str | None] = mapped_column(String(36))
    location_ids: Mapped[list | None] = mapped_column(JSON)
    department_ids: Mapped[list | None] = mapped_column(JSON)
    exclusions_text: Mapped[str | None] = mapped_column(Text)


class ClientContact(TimestampedTenantMixin, Base):
    """A named client contact for a sign-off or setup role (spec §9.1, §18.3). organization_id is the client."""

    __tablename__ = "client_contacts"

    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    contact_role: Mapped[str] = mapped_column(String(20))  # caico | client_admin | exec_sponsor | dpo | project_lead | technical_lead | compliance_lead
    name: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    not_appointed: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
