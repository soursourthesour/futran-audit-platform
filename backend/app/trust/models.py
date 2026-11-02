"""Trust Center (spec §21 F9, screen 32). organization_id is the client that owns the page."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

ITEM_KINDS = ("commitment", "policy", "bias_summary", "badge", "governance", "rights_contact")


class TrustCenterPage(TimestampedTenantMixin, Base):
    __tablename__ = "trust_center_pages"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_trust_page_org"), UniqueConstraint("slug", name="uq_trust_page_slug"))

    slug: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    intro: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(String(254))
    live: Mapped[bool] = mapped_column(Boolean, default=False)  # the public page exists only while live
    access: Mapped[str] = mapped_column(String(8), default="public")  # public | nda (NDA click-through before detailed documents)
    nda_text: Mapped[str | None] = mapped_column(Text)
    indexable: Mapped[bool] = mapped_column(Boolean, default=False)  # search engines may index the page (noindex unless opted in)


class TrustCenterItem(TimestampedTenantMixin, Base):
    """One card on the page. The working copy is edited by the CAICO; the public sees only `published_content`, the
    snapshot a Futran Chief Auditor confirmed against the signed report."""

    __tablename__ = "trust_center_items"

    page_id: Mapped[str] = mapped_column(String(36), ForeignKey("trust_center_pages.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    link_label: Mapped[str | None] = mapped_column(String(80))
    link_url: Mapped[str | None] = mapped_column(String(500))
    source_id: Mapped[str | None] = mapped_column(String(36))  # policy document, public summary or engagement
    options: Mapped[dict] = mapped_column(JSON, default=dict)  # badge: {show_rating}
    order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="draft")  # draft | awaiting_confirmation | returned | published | withdrawn
    approved_content: Mapped[dict | None] = mapped_column(JSON)  # what the CAICO approved
    client_approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    client_approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_report_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("reports.id"))
    confirm_note: Mapped[str | None] = mapped_column(Text)
    return_note: Mapped[str | None] = mapped_column(Text)
    published_content: Mapped[dict | None] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)


class TrustCenterView(TimestampedTenantMixin, Base):
    """Public page views per day (no visitor data is kept)."""

    __tablename__ = "trust_center_views"
    __table_args__ = (UniqueConstraint("page_id", "day", name="uq_trust_view_day"),)

    page_id: Mapped[str] = mapped_column(String(36), ForeignKey("trust_center_pages.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    views: Mapped[int] = mapped_column(Integer, default=0)


class TrustCenterNdaAcceptance(TimestampedTenantMixin, Base):
    """A visitor who accepted the NDA click-through. The access token is stored as its hash only."""

    __tablename__ = "trust_center_nda_acceptances"

    page_id: Mapped[str] = mapped_column(String(36), ForeignKey("trust_center_pages.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254))
    company: Mapped[str | None] = mapped_column(String(200))
    nda_text: Mapped[str | None] = mapped_column(Text)  # the text they accepted
    accepted_at: Mapped[datetime] = mapped_column(DateTime)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
