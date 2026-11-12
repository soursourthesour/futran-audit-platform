"""Scoping entities (spec §4.11): the question bank, questionnaires and their answers, client sends, mapping rules."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin

SECTIONS = ("A", "B", "C", "D", "E", "F", "G", "H", "RF")
QUESTION_TYPES = ("count", "total", "single", "multi", "yes_no", "text")
MODES = ("recorded", "sent", "hybrid")
STATUSES = ("draft", "sent", "client_in_progress", "client_submitted", "locked")
SOURCES = ("rep", "client", "rep_confirmed_client")
CONFIDENCES = ("confirmed", "estimate", "unknown")
SEND_STATUSES = ("sent", "opened", "in_progress", "submitted", "revoked", "expired")
RULE_STATUSES = ("pending", "approved", "rejected")


class ScopingBankVersion(IdMixin, Base):
    """One version of the scoping question bank. Editing a question that a questionnaire already uses makes a new
    version, so a questionnaire always shows the wording it was answered against."""

    __tablename__ = "scoping_bank_versions"

    version: Mapped[int] = mapped_column(Integer, unique=True)
    label: Mapped[str] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)  # e.g. "Starter — replace with the Sales Collateral questionnaire"
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScopingQuestion(IdMixin, Base):
    """Reference data: one question of the bank (spec §4.4). `code` is stable across versions."""

    __tablename__ = "scoping_questions"
    __table_args__ = (UniqueConstraint("bank_version", "code", name="uq_scoping_question_code"),)

    bank_version: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(20))
    section: Mapped[str] = mapped_column(String(4))
    label: Mapped[str] = mapped_column(String(300))  # what the rep sees
    client_label: Mapped[str | None] = mapped_column(String(300))  # plain wording on the client link; label when empty
    help: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(10))
    options: Mapped[list] = mapped_column(JSON, default=list)  # [{value, label}]
    sum_of: Mapped[list] = mapped_column(JSON, default=list)  # a "total" question adds these counts (can be overridden)
    client_visible: Mapped[bool] = mapped_column(Boolean, default=True)  # offered on the send dialog
    internal_only: Mapped[bool] = mapped_column(Boolean, default=False)  # never on a client link, whatever is chosen
    unknown_assumption: Mapped[str | None] = mapped_column(Text)  # proposal assumption when the answer is unknown
    order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScopingQuestionnaire(IdMixin, Base):
    """One version of an opportunity's questionnaire. Unlocking a locked version starts the next version."""

    __tablename__ = "scoping_questionnaires"
    __table_args__ = (UniqueConstraint("opportunity_id", "version", name="uq_scoping_questionnaire_version"),)

    # the prospect or client the answers are about. The rows themselves are Futran's sales data (Futran's tenant).
    prospect_id: Mapped[str] = mapped_column(String(36), index=True)
    opportunity_id: Mapped[str] = mapped_column(String(36), ForeignKey("opportunities.id"), index=True)
    bank_version: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(10), default="recorded")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    previous_id: Mapped[str | None] = mapped_column(String(36))
    # rule-proposed lines the rep removed, each with the reason (read by the proposal builder):
    # [{code, rule_code, reason, by, at}]
    removed_lines: Mapped[list] = mapped_column(JSON, default=list)
    locked_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    proposal_id: Mapped[str | None] = mapped_column(String(36))  # set when "Lock and build proposal" made one
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScopingAnswer(IdMixin, Base):
    """An answer keeps who gave it. The rep's answer and the client's answer to the same question are separate rows
    (`slot`), so a client answer never overwrites the rep's; a difference is a conflict on SM-08 until resolved."""

    __tablename__ = "scoping_answers"
    __table_args__ = (UniqueConstraint("questionnaire_id", "question_code", "slot", name="uq_scoping_answer_slot"),)

    questionnaire_id: Mapped[str] = mapped_column(String(36), ForeignKey("scoping_questionnaires.id"), index=True)
    question_code: Mapped[str] = mapped_column(String(20))
    slot: Mapped[str] = mapped_column(String(6))  # rep | client
    value: Mapped[object | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(22))  # rep | client | rep_confirmed_client
    confidence: Mapped[str] = mapped_column(String(10), default="confirmed")
    note: Mapped[str | None] = mapped_column(Text)
    answered_by: Mapped[str | None] = mapped_column(String(36))  # user id (rep) or QuestionnaireSend id (client contact)
    answered_by_name: Mapped[str | None] = mapped_column(String(200))
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)  # rep slot: when a conflict with the client was settled
    resolved_by: Mapped[str | None] = mapped_column(String(36))


class QuestionnaireSend(IdMixin, Base):
    """A personal no-login link to part of a questionnaire for one client contact (SM-06, SM-07). Only the hash of the
    link token is stored; a reminder carries a new link and the old one stops working."""

    __tablename__ = "scoping_questionnaire_sends"

    questionnaire_id: Mapped[str] = mapped_column(String(36), ForeignKey("scoping_questionnaires.id"), index=True)
    contact_id: Mapped[str | None] = mapped_column(String(36))  # the opportunity contact, when there is one
    contact_name: Mapped[str] = mapped_column(String(200))
    contact_email: Mapped[str] = mapped_column(String(254))
    question_codes: Mapped[list] = mapped_column(JSON, default=list)
    mail_send_id: Mapped[str | None] = mapped_column(String(36))
    mail_recipient_id: Mapped[str | None] = mapped_column(String(36))
    due_on: Mapped[date | None] = mapped_column(Date)
    reminder_days: Mapped[list] = mapped_column(JSON, default=list)  # e.g. [3, 7]
    reminders_sent: Mapped[list] = mapped_column(JSON, default=list)  # the reminder days already sent
    allow_forward: Mapped[bool] = mapped_column(Boolean, default=True)
    forwarded_from_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(12), default="sent")
    token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    subject: Mapped[str | None] = mapped_column(String(300))
    message: Mapped[str | None] = mapped_column(Text)
    sent_by: Mapped[str | None] = mapped_column(String(36))  # the rep whose mailbox it goes from
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    partial_notified_at: Mapped[datetime | None] = mapped_column(DateTime)


class MappingRule(IdMixin, Base):
    """A rule reads answers and proposes one line item, quantity and reason (spec §4.5). Edited by the Futran Admin;
    an edit waits in `pending` until the Pricing Approver approves it, and until then the approved definition runs.
    A rule whose line code is not in the catalog stays and is flagged; it is never dropped."""

    __tablename__ = "scoping_mapping_rules"

    code: Mapped[str] = mapped_column(String(20), unique=True)
    catalog_version: Mapped[int | None] = mapped_column(Integer)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)  # {"all"|"any": [conditions]} on question codes
    line_code: Mapped[str] = mapped_column(String(20))
    qty_formula: Mapped[dict] = mapped_column(JSON, default=dict)
    reason_template: Mapped[str] = mapped_column(String(400))
    note: Mapped[str | None] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(10), default="approved")
    pending: Mapped[dict | None] = mapped_column(JSON)  # an edit awaiting approval
    pending_by: Mapped[str | None] = mapped_column(String(36))
    pending_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[str | None] = mapped_column(String(36))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
