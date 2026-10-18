from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin


class Organization(TimestampedTenantMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    trading_name: Mapped[str | None] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(10))  # futran | client
    industry: Mapped[str | None] = mapped_column(String(80))
    employee_band: Mapped[str | None] = mapped_column(String(40))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    annual_revenue_band: Mapped[str | None] = mapped_column(String(40))
    primary_jurisdictions: Mapped[list | None] = mapped_column(JSON)
    ai_systems_in_scope_count: Mapped[int | None] = mapped_column(Integer)
    hq_street: Mapped[str | None] = mapped_column(String(200))
    hq_city: Mapped[str | None] = mapped_column(String(120))
    hq_state: Mapped[str | None] = mapped_column(String(120))
    hq_postal_code: Mapped[str | None] = mapped_column(String(20))
    hq_country: Mapped[str | None] = mapped_column(String(2))
    website: Mapped[str | None] = mapped_column(String(200))
    client_ref: Mapped[str | None] = mapped_column(String(12), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | active | archived
    engagement_reason: Mapped[str | None] = mapped_column(String(2000))
    data_region: Mapped[str | None] = mapped_column(String(40))
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)


class Department(TimestampedTenantMixin, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(120))
    head_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", use_alter=True))
    headcount: Mapped[int | None] = mapped_column(Integer)
    head_name: Mapped[str | None] = mapped_column(String(120))
    head_email: Mapped[str | None] = mapped_column(String(254))
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"))
    in_scope: Mapped[bool] = mapped_column(Boolean, default=True)


class User(TimestampedTenantMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_user_org_email"),
        Index("uq_users_email_ci", text("lower(email)"), unique=True),
    )

    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254), index=True)
    job_title: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(40))
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"))
    location: Mapped[str | None] = mapped_column(String(160))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime)  # client users accept the terms when they first sign in (screen 9a)
    sso_subject: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10), default="invited")  # invited | active | disabled


class RoleAssignment(TimestampedTenantMixin, Base):
    __tablename__ = "role_assignments"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    scope_type: Mapped[str] = mapped_column(String(12), default="org")  # org | department | engagement | system
    scope_id: Mapped[str | None] = mapped_column(String(36))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
