"""AI records (spec §21: AIInteraction, Obligation, Questionnaire, AnswerLibraryItem; wave 3 plan, AI rules 1–3).

`AIInteraction` is one suggestion the model made, so each one carries its own decision: a pre-fill run over a section
writes one row per question, sharing a `call_id`. A row is written for every call (rule 3) and updated when a named
person accepts, edits or rejects it. `status`: suggested | unsupported (a cited quote is not in the cited document, or
there is no citation; it can never be accepted as an answer or as evidence) | accepted | edited | rejected.

`feature`: copilot_prefill | evidence_check | draft_finding | review_check (completeness contradictions) | summary |
ask | explain (client Q&A helper) | obligation_extract | questionnaire.

`citations`: [{"file_id", "filename", "page", "quote", "found"}] for documents; [{"source_type", "source_id", "label",
"quote", "found"}] for law text, policies, the signed report and the answer library.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

FEATURES = ("copilot_prefill", "evidence_check", "draft_finding", "review_check", "summary", "ask", "explain", "obligation_extract", "questionnaire")
CONFIDENCE = ("high", "medium", "low")
STATUSES = ("suggested", "unsupported", "accepted", "edited", "rejected")


class AIInteraction(TimestampedTenantMixin, Base):
    __tablename__ = "ai_interactions"

    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    ai_system_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_systems.id"), index=True)
    feature: Mapped[str] = mapped_column(String(24), index=True)
    call_id: Mapped[str] = mapped_column(String(36), index=True)  # rows written by the same model call
    model: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(20))
    prompt_version: Mapped[str] = mapped_column(String(40))
    input_refs: Mapped[list] = mapped_column(JSON, default=list)  # [{"type": "file", "id": ...}, {"type": "response", "id": ...}]
    target_type: Mapped[str | None] = mapped_column(String(24))  # question | checklist_item | finding | system | engagement | law | questionnaire_item
    target_id: Mapped[str | None] = mapped_column(String(36), index=True)
    target_code: Mapped[str | None] = mapped_column(String(40))
    output: Mapped[dict | None] = mapped_column(JSON)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12), default="suggested")
    decided_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    reason: Mapped[str | None] = mapped_column(Text)
    result_refs: Mapped[list] = mapped_column(JSON, default=list)  # what acceptance wrote: [{"type": "response", "id": ...}]
    follow_up: Mapped[str | None] = mapped_column(String(20))  # interview | evidence_request (unsupported pre-fill items)
    follow_up_ref: Mapped[str | None] = mapped_column(String(40))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)


class Obligation(TimestampedTenantMixin, Base):
    """An obligation in a law (F5). Proposed by the model from the law's stored text, approved by the Legal Reviewer or
    the Chief Auditor. Approved rows show on the law record (M2) and feed lineage (F6). organization_id is Futran's."""

    __tablename__ = "obligations"

    regulation_id: Mapped[str] = mapped_column(String(36), ForeignKey("regulations.id"), index=True)
    law_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("law_versions.id"))
    text: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(20))  # developer | deployer | employer | provider | data_fiduciary
    action: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[str | None] = mapped_column(String(300))
    citation: Mapped[str | None] = mapped_column(String(200))
    quote: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    control_ids: Mapped[list] = mapped_column(JSON, default=list)  # framework control codes (§10.4)
    question_ids: Mapped[list] = mapped_column(JSON, default=list)  # template question codes (§18.4)
    requirement_ids: Mapped[list] = mapped_column(JSON, default=list)  # Requirement ids of the law version
    confidence: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12), default="suggested")  # suggested | unsupported | approved | rejected
    interaction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_interactions.id"))
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejected_reason: Mapped[str | None] = mapped_column(Text)


class DocumentText(TimestampedTenantMixin, Base):
    """Text extracted from an uploaded file, kept by page so citations can name the page (PDF pages; DOCX and plain
    text in "pages" of about 3,000 characters). Re-extracted when the file's hash changes."""

    __tablename__ = "ai_document_texts"

    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("files.id"), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(10))  # pdf | docx | xlsx | text | none
    pages: Mapped[list] = mapped_column(JSON, default=list)  # [{"page": 1, "text": "..."}]
    chars: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))


class Questionnaire(TimestampedTenantMixin, Base):
    """A customer's security or AI due-diligence questionnaire the client uploaded (F10)."""

    __tablename__ = "questionnaires"

    title: Mapped[str] = mapped_column(String(200))
    customer_name: Mapped[str | None] = mapped_column(String(200))
    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("files.id"))
    format: Mapped[str] = mapped_column(String(5))  # xlsx | docx | pdf
    status: Mapped[str] = mapped_column(String(12), default="in_progress")  # in_progress | completed
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[str | None] = mapped_column(String(36))


class QuestionnaireItem(TimestampedTenantMixin, Base):
    """One detected question and its answer. `locator` says where it sits in the original file, so the export writes
    the answer back in place: {"sheet", "row", "col", "answer_col"} | {"paragraph"} | {"table", "row", "cell"} | {"page"}."""

    __tablename__ = "questionnaire_items"

    questionnaire_id: Mapped[str] = mapped_column(String(36), ForeignKey("questionnaires.id"), index=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    locator: Mapped[dict] = mapped_column(JSON, default=dict)
    section: Mapped[str | None] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | suggested | unsupported | accepted | edited | rejected | answered
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[str | None] = mapped_column(String(8))
    audited_by_futran: Mapped[bool] = mapped_column(Boolean, default=False)  # proposed by a draft; shown in an export only once confirmed
    audited_confirmed_by: Mapped[str | None] = mapped_column(String(36))  # the approver who confirmed the "Audited by Futran" label
    audited_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    interaction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("ai_interactions.id"))
    decided_by: Mapped[str | None] = mapped_column(String(36))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    library_item_id: Mapped[str | None] = mapped_column(String(36))


class AnswerLibraryItem(TimestampedTenantMixin, Base):
    """An approved answer the client reuses in later questionnaires. Grows from accepted questionnaire answers."""

    __tablename__ = "answer_library_items"

    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | questionnaire
    source_item_id: Mapped[str | None] = mapped_column(String(36))
    audited_by_futran: Mapped[bool] = mapped_column(Boolean, default=False)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    approved_by: Mapped[str | None] = mapped_column(String(36))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)
