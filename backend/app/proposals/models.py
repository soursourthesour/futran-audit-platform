"""Proposals (spec §4.6, §4.7, §4.11; screens SM-09 to SM-12).

Proposal rows are Futran's own sales data, like the price list and the scoping questionnaire: no client tenant owns
them and only Futran staff hold the actions that read them. The client sees one proposal version through its personal
acceptance link (`ProposalLink`), and nothing else.

Versions of the same proposal share `thread_id` (the first version's id). A version is editable while it is a draft;
once sent it never changes again (a new version is made instead)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin

STATUSES = ("draft", "awaiting_approval", "approved", "sent", "viewed", "changes_requested", "accepted", "expired", "superseded")
EDITABLE = ("draft", "awaiting_approval", "approved")
LINE_SOURCES = ("rule", "package", "manual")


class Proposal(IdMixin, Base):
    __tablename__ = "proposals"
    __table_args__ = (UniqueConstraint("thread_id", "version", name="uq_proposal_version"),)

    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    opportunity_id: Mapped[str] = mapped_column(String(36), ForeignKey("opportunities.id"), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)  # the prospect or client the proposal is for
    estimate_id: Mapped[str | None] = mapped_column(String(36))
    questionnaire_id: Mapped[str | None] = mapped_column(String(36))
    questionnaire_version: Mapped[int | None] = mapped_column(Integer)
    catalog_version: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_id: Mapped[str | None] = mapped_column(String(36))
    package: Mapped[str | None] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200), default="AI governance proposal")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    valid_days: Mapped[int] = mapped_column(Integer, default=30)
    valid_until: Mapped[date | None] = mapped_column(Date)  # set when sent
    discount_recurring_pct: Mapped[float] = mapped_column(Float, default=0)
    # payment_days, payment_terms, term_years, sla, data_region, custom_liability, sla_credits, discount_one_time_pct, start_on
    terms: Mapped[dict] = mapped_column(JSON, default=dict)
    sections: Mapped[list] = mapped_column(JSON, default=list)  # [{key, title, body, edited}]
    totals: Mapped[dict] = mapped_column(JSON, default=dict)  # one_time, recurring_y1, discount, y1_total, arr
    independence: Mapped[dict] = mapped_column(JSON, default=dict)  # {flag, reason} when the version was last saved
    alerts: Mapped[dict] = mapped_column(JSON, default=dict)  # owner alerts already sent: not_opened, expiring
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    file_ids: Mapped[dict] = mapped_column(JSON, default=dict)  # {pdf, docx} frozen at send
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def editable(self) -> bool:
        return self.status in EDITABLE


class ProposalLine(IdMixin, Base):
    """One line. Price precedence: `override_price` (edited on this proposal) → `list_price` (catalog) → none (blocked).
    `removed_reason` set means the line stays on the record but is not offered (a rule line needs a reason)."""

    __tablename__ = "proposal_lines"

    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposals.id"), index=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    catalog_code: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(200))
    product: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    deliverables_text: Mapped[str | None] = mapped_column(Text)  # copied from the catalog, editable per proposal
    deliverables_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    qty: Mapped[float] = mapped_column(Float, default=1)
    list_price: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    override_price: Mapped[float | None] = mapped_column(Float)
    edited_by: Mapped[str | None] = mapped_column(String(36))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)
    unit_price_used: Mapped[float | None] = mapped_column(Float)
    periods_per_year: Mapped[int] = mapped_column(Integer, default=1)
    line_value: Mapped[float | None] = mapped_column(Float)
    percent_of: Mapped[float | None] = mapped_column(Float)  # %-items: the year-1 value the percentage is taken of
    billing: Mapped[str] = mapped_column(String(12), default="one_time")
    basis: Mapped[str] = mapped_column(String(1), default="$")
    pricing_unit: Mapped[str | None] = mapped_column(String(80))
    applies_to: Mapped[list] = mapped_column(JSON, default=list)
    included_quantities: Mapped[dict] = mapped_column(JSON, default=dict)
    price_status: Mapped[str | None] = mapped_column(String(10))
    sellable_status: Mapped[str | None] = mapped_column(String(16))
    on_catalog: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")  # rule | package | manual
    rule_code: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(400))
    removed_reason: Mapped[str | None] = mapped_column(String(500))
    removed_by: Mapped[str | None] = mapped_column(String(36))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ApprovalRequest(IdMixin, Base):
    """One rule's approval for one proposal version. An approval counts only while the proposal still matches the
    `fingerprint` it was given for: editing prices, quantities, the discount or the terms afterwards needs it again."""

    __tablename__ = "proposal_approval_requests"

    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposals.id"), index=True)
    rule: Mapped[str] = mapped_column(String(4), index=True)  # P-1 … P-6, I-1 … I-3
    line_ids: Mapped[list] = mapped_column(JSON, default=list)
    codes: Mapped[list] = mapped_column(JSON, default=list)
    message: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approver_role: Mapped[str] = mapped_column(String(20), index=True)
    approver_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # pending | approved | returned | withdrawn
    note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class ProposalLink(IdMixin, Base):
    """A personal acceptance link (SM-12) for one contact and one proposal version: a random 256-bit token stored only as
    its SHA-256 hash, expiring with the proposal. A reminder carries a fresh link and the old one stops working."""

    __tablename__ = "proposal_links"

    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposals.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254))
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    mail_send_id: Mapped[str | None] = mapped_column(String(36))
    sent_by: Mapped[str | None] = mapped_column(String(36))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    replaced_by_id: Mapped[str | None] = mapped_column(String(36))


class ProposalEvent(IdMixin, Base):
    """The send log and view tracking: sent, reminder, opened, exported, changes_requested, accepted, expired."""

    __tablename__ = "proposal_events"

    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposals.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    by_id: Mapped[str | None] = mapped_column(String(36))
    by_name: Mapped[str | None] = mapped_column(String(200))
    link_id: Mapped[str | None] = mapped_column(String(36))
    detail: Mapped[str | None] = mapped_column(Text)


class Acceptance(IdMixin, Base):
    __tablename__ = "proposal_acceptances"
    __table_args__ = (UniqueConstraint("proposal_id", name="uq_proposal_acceptance"),)

    proposal_id: Mapped[str] = mapped_column(String(36), ForeignKey("proposals.id"), index=True)
    link_id: Mapped[str | None] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254))
    authorised_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    po_number: Mapped[str | None] = mapped_column(String(80))
    po_file_id: Mapped[str | None] = mapped_column(String(36))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    handoff_id: Mapped[str | None] = mapped_column(String(36))


class ProposalTemplate(IdMixin, Base):
    """A section template the Futran Admin maintains (SM-14 Proposal templates tab). The body is the standard wording;
    the builder adds the generated parts (service blocks, pricing table, assumptions) under it. Merge fields in square
    brackets: [Company], [Rep name], [Valid until], [Version], [Date]."""

    __tablename__ = "proposal_templates"
    __table_args__ = (UniqueConstraint("key", name="uq_proposal_template_key"),)

    key: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_starter: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
