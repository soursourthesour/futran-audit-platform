"""G-11 records (spec B11).

Partner rows belong to Futran's own organization. Commission and Referral rows carry the client they are about as
organization_id (the client tenant), so a client's billing export and audit trail find them.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

PARTNER_TYPES = ("law_firm", "ats_vendor", "hr_tech", "cloud_partner", "audit_firm", "other")
TYPE_LABELS = {"law_firm": "Law firm", "ats_vendor": "ATS vendor", "hr_tech": "HR-tech vendor", "cloud_partner": "Cloud partner", "audit_firm": "Audit firm", "other": "Other"}
COMMISSION_STATUSES = ("due", "paid", "void")


class Partner(TimestampedTenantMixin, Base):
    __tablename__ = "partners"

    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))
    agreement_label: Mapped[str | None] = mapped_column(String(120))  # "Referral agreement", "Channel agreement"
    agreement_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"))
    commission_rule: Mapped[dict | None] = mapped_column(JSON)  # {"rate_pct": 15, "basis": "first_year_value"}; always null for law firms
    contact_name: Mapped[str | None] = mapped_column(String(160))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | inactive
    notes: Mapped[str | None] = mapped_column(Text)


class Commission(TimestampedTenantMixin, Base):
    """organization_id is the client won."""

    __tablename__ = "partner_commissions"

    partner_id: Mapped[str] = mapped_column(String(36), ForeignKey("partners.id"), index=True)
    opportunity_id: Mapped[str] = mapped_column(String(36), index=True)
    order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    order_ref: Mapped[str | None] = mapped_column(String(12))
    base_value: Mapped[float] = mapped_column(Float)
    rate: Mapped[float] = mapped_column(Float)  # percent
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(6), default="due")
    due_on: Mapped[date] = mapped_column(Date, index=True)
    paid_on: Mapped[date | None] = mapped_column(Date)
    settled_by: Mapped[str | None] = mapped_column(String(36))
    void_reason: Mapped[str | None] = mapped_column(String(300))


class Referral(TimestampedTenantMixin, Base):
    """organization_id is the client the referral is about (Futran's own organization when there is none yet)."""

    __tablename__ = "partner_referrals"

    partner_id: Mapped[str] = mapped_column(String(36), ForeignKey("partners.id"), index=True)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    opportunity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime)
    recorded_by: Mapped[str | None] = mapped_column(String(36))
