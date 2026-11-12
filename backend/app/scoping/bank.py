"""The scoping question bank (spec §4.4): stored as data, editable on the Question bank tab of the master price list
(`/staff/admin/catalog/questions`). The Futran Admin maintains it and the Sales Manager owns it (user's default, R2-Q5).

The starter bank holds only the questions shown in the Release 2 screen designs (SM-05, SM-07, SM-08) and every
question code the spec §4.5 mapping rules read, worded from the spec and the designs. It is marked as a starter: the
Sales Collateral scoping questionnaire replaces it when it is in hand. Nothing here is invented beyond that.

Editing a question that a questionnaire already uses copies the bank to a new version first, so answered questionnaires
keep the wording they were answered against.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import Invalid, NotFound
from app.scoping.models import QUESTION_TYPES, SECTIONS, ScopingBankVersion, ScopingQuestion, ScopingQuestionnaire

STARTER_LABEL = "Starter question bank"
STARTER_NOTE = "Starter — replace with the Sales Collateral questionnaire. Taken from the Release 2 screen designs and the questions the mapping rules read."

SECTION_LABELS = {
    "A": "Account and deal", "B": "Footprint", "C": "AI inventory", "D": "Hiring AI and LL144", "E": "Audit needs",
    "F": "Monitoring and retention", "G": "Agents", "H": "Other and terms", "RF": "Red flags (internal)",
}
SECTION_INTROS = {
    "C": "The number of AI systems sets the audit and Monitor tier. Unknown is fine.",
    "D": "Hiring tools that score, rank or screen candidates may need an independent bias audit (NYC Local Law 144).",
    "RF": "Internal notes. Never sent to the client.",
}

YES_NO = [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]


def _opts(*pairs: tuple[str, str]) -> list[dict]:
    return [{"value": v, "label": label} for v, label in pairs]


# (code, section, type, label, client_label, extra)
STARTER: list[dict] = [
    # A. Account and deal (SM-03 trigger list; budget, competitors and independence are internal, never sent)
    {"code": "SQ-A.01", "section": "A", "type": "single", "label": "What prompted this conversation?",
     "client_label": "What prompted you to look at AI compliance now?",
     "options": _opts(("ll144_due", "LL144 audit due"), ("new_state_law", "New state law"), ("lawsuit", "Lawsuit worry"),
                      ("customer_rfp", "Customer or RFP asked"), ("agents_copilot", "Agents or Copilot rollout"), ("shadow_ai", "Shadow AI"),
                      ("ma", "M&A"))},
    {"code": "SQ-A.02", "section": "A", "type": "text", "label": "Budget", "internal_only": True, "client_visible": False,
     "help": "Internal. Never shown on the client link."},
    {"code": "SQ-A.03", "section": "A", "type": "text", "label": "Competitors in the deal", "internal_only": True, "client_visible": False,
     "help": "Internal. Never shown on the client link."},
    {"code": "SQ-A.04", "section": "A", "type": "text", "label": "Independence notes", "internal_only": True, "client_visible": False,
     "help": "Internal. Anything that touches Futran's independence as auditor (current or recent audit work, open remediation)."},
    # B. Footprint
    {"code": "SQ-B.01", "section": "B", "type": "count", "label": "Number of employees", "client_label": "About how many employees do you have?"},
    {"code": "SQ-B.06", "section": "B", "type": "count", "label": "US states the audit covers",
     "client_label": "In how many US states do you hire or use AI?", "help": "One state is included in the audit; each extra state is a line."},
    {"code": "SQ-B.07", "section": "B", "type": "multi", "label": "Jurisdictions to watch (regulatory alerts)",
     "client_label": "Which states' AI rules do you need to follow?",
     "options": _opts(("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("IL", "Illinois"), ("MD", "Maryland"), ("NJ", "New Jersey"),
                      ("NY", "New York"), ("TX", "Texas"), ("UT", "Utah"), ("VA", "Virginia"), ("other", "Another state"))},
    {"code": "SQ-B.08", "section": "B", "type": "yes_no", "label": "Do any AI systems affect people in the EU?",
     "client_label": "Do any of your AI tools affect people in the European Union?", "options": YES_NO},
    # C. AI inventory (SM-05)
    {"code": "SQ-C.01", "section": "C", "type": "count", "label": "Vendor apps with AI", "client_label": "How many software products you buy have AI features?"},
    {"code": "SQ-C.02", "section": "C", "type": "count", "label": "Embedded AI (Copilot etc.)", "client_label": "How many embedded AI assistants (such as Copilot) are switched on?"},
    {"code": "SQ-C.03", "section": "C", "type": "count", "label": "GenAI chat tools", "client_label": "How many AI chat tools do people use (such as ChatGPT)?"},
    {"code": "SQ-C.04", "section": "C", "type": "count", "label": "Model APIs", "client_label": "How many AI model APIs do your systems call?"},
    {"code": "SQ-C.05", "section": "C", "type": "count", "label": "In-house models", "client_label": "How many AI models has your team built?"},
    {"code": "SQ-C.06", "section": "C", "type": "count", "label": "Agents that act", "client_label": "How many AI agents take actions on their own?"},
    {"code": "SQ-C.07", "section": "C", "type": "total", "label": "Total AI systems", "client_label": "In total, how many AI systems do you use?",
     "sum_of": ["SQ-C.01", "SQ-C.02", "SQ-C.03", "SQ-C.04", "SQ-C.05", "SQ-C.06"], "help": "The sum of the counts above; it can be overridden.",
     "unknown_assumption": "AI system count not confirmed; a discovery sweep (A-05) confirms the inventory before the audit tier is fixed."},
    {"code": "SQ-C.08", "section": "C", "type": "count", "label": "Number of AI vendors", "client_label": "How many vendors supply your AI tools?",
     "unknown_assumption": "Vendor review priced per vendor once the inventory is complete."},
    {"code": "SQ-C.09", "section": "C", "type": "count", "label": "High-risk systems (decisions about people)",
     "client_label": "How many of these tools help make decisions about people (hiring, credit, insurance, health)?"},
    {"code": "SQ-C.10", "section": "C", "type": "single", "label": "How well do they know their AI?",
     "client_label": "Do you have a list of the AI tools you use?",
     "options": _opts(("full", "Full inventory exists and is current"), ("partial", "Partial list, probably missing tools"), ("none", "No inventory"))},
    {"code": "SQ-C.11", "section": "C", "type": "multi", "label": "Systems we could pull discovery data from",
     "client_label": "Which of these systems could you export data from?",
     "options": _opts(("okta_entra", "Okta / Entra ID"), ("m365", "Microsoft 365"), ("google", "Google Workspace"), ("expense", "Expense export"),
                      ("casb", "CASB / proxy logs"))},
    {"code": "SQ-C.12", "section": "C", "type": "multi", "label": "Embedded AI switched on", "client_label": "Which built-in AI assistants are switched on?",
     "options": _opts(("m365_copilot", "Microsoft 365 Copilot"), ("gemini", "Gemini for Google Workspace"), ("einstein", "Salesforce Einstein"),
                      ("now_assist", "ServiceNow Now Assist"), ("other", "Another assistant"))},
    # D. Hiring AI and LL144 (SM-07, SM-08)
    {"code": "SQ-D.01", "section": "D", "type": "text", "label": "Hiring tools that score, rank or screen candidates",
     "client_label": "Which hiring tools score, rank or screen candidates?", "help": "Tool names."},
    {"code": "SQ-D.02", "section": "D", "type": "count", "label": "Number of AEDTs", "client_label": "How many tools is that?"},
    {"code": "SQ-D.03", "section": "D", "type": "count", "label": "Annual hiring volume", "client_label": "About how many people do you hire a year?",
     "unknown_assumption": "Synthetic test-data audit if historical data is insufficient."},
    {"code": "SQ-D.04", "section": "D", "type": "yes_no", "label": "Hires for roles in New York City", "client_label": "Do you hire for jobs in New York City?",
     "options": YES_NO},
    {"code": "SQ-D.05", "section": "D", "type": "single", "label": "Demographic data collected from candidates",
     "client_label": "Do you collect race/ethnicity and sex data from candidates?",
     "options": _opts(("yes", "Yes, voluntary self-ID"), ("partly", "Partly"), ("no", "No"))},
    {"code": "SQ-D.06", "section": "D", "type": "single", "label": "Historical hiring data for the bias audit",
     "client_label": "How much past hiring data with outcomes do you have for these tools?",
     "options": _opts(("plenty", "Plenty (a year or more)"), ("some", "Some"), ("little", "Little"), ("none", "None"))},
    {"code": "SQ-D.07", "section": "D", "type": "single", "label": "Business model", "client_label": "Which best describes your business?",
     "options": _opts(("employer", "We hire for ourselves"), ("staffing", "Staffing or recruiting agency"), ("hr_vendor", "HR technology vendor"),
                      ("other", "Something else"))},
    {"code": "SQ-D.08", "section": "D", "type": "count", "label": "End-clients with NYC roles", "client_label": "For how many end-clients do you fill NYC roles?"},
    {"code": "SQ-D.09", "section": "D", "type": "multi", "label": "Other states with hiring AI rules", "client_label": "Do you also hire in any of these states?",
     "options": _opts(("IL", "Illinois"), ("CO", "Colorado"), ("CA", "California"), ("MD", "Maryland"), ("NJ", "New Jersey"))},
    # E. Audit needs
    {"code": "SQ-E.01", "section": "E", "type": "count", "label": "High-risk systems needing an impact assessment (Colorado, EU, DPIA)",
     "client_label": "How many systems need an impact assessment (Colorado, EU or a DPIA)?"},
    # F. Monitoring and retention
    {"code": "SQ-F.01", "section": "F", "type": "single", "label": "Interest in ongoing monitoring",
     "client_label": "Would you like ongoing monitoring after the audit?",
     "options": _opts(("monitor", "Monitor"), ("monitor_plus", "Monitor Plus"), ("no", "No"))},
    {"code": "SQ-F.02", "section": "F", "type": "single", "label": "Record retention", "client_label": "How long must you keep AI audit records?",
     "options": _opts(("3", "3 yrs"), ("5", "5 yrs"), ("7", "7 yrs"), ("10", "10 yrs"))},
    {"code": "SQ-F.17", "section": "F", "type": "count", "label": "Storage volume (GB)", "client_label": "About how much evidence storage do you expect (GB)?",
     "unknown_assumption": "Vault includes 50 GB; extra storage billed per 100 GB."},
    # G. Agents
    {"code": "SQ-G.01", "section": "G", "type": "count", "label": "Agents live today", "client_label": "How many AI agents are live today?"},
    {"code": "SQ-G.02", "section": "G", "type": "count", "label": "Agents planned in the next 12 months", "client_label": "How many more do you plan in the next 12 months?"},
    {"code": "SQ-G.03", "section": "G", "type": "single", "label": "Agent autonomy", "client_label": "How much do the agents do on their own?",
     "options": _opts(("suggest", "Suggest only; a person acts"), ("approve", "Act after a person approves"), ("autonomous", "Act on their own"))},
    {"code": "SQ-G.04", "section": "G", "type": "multi", "label": "Actions agents can take", "client_label": "What can the agents do?",
     "options": _opts(("send_messages", "Send emails or messages"), ("update_records", "Update records"), ("move_money", "Move money or pay"),
                      ("change_access", "Change access or permissions"), ("order", "Buy or order"))},
    # H. Other and terms
    {"code": "SQ-H.01", "section": "H", "type": "yes_no", "label": "Microsoft 365 Copilot rollout", "client_label": "Are you rolling out Microsoft 365 Copilot?",
     "options": YES_NO},
    # Red flags (internal)
    {"code": "SQ-RF.01", "section": "RF", "type": "text", "label": "Red flags", "internal_only": True, "client_visible": False,
     "help": "Internal. Never shown on the client link."},
]

EDITABLE = ("label", "client_label", "help", "options", "client_visible", "internal_only", "unknown_assumption", "order", "active", "section", "type", "sum_of")


def current_version(db: Session) -> int:
    return db.scalar(select(func.max(ScopingBankVersion.version))) or 0


def ensure_seed(db: Session) -> int:
    """Load the starter bank once. Returns the current bank version."""
    v = current_version(db)
    if v:
        return v
    db.add(ScopingBankVersion(version=1, label=STARTER_LABEL, note=STARTER_NOTE))
    for i, q in enumerate(STARTER):
        db.add(ScopingQuestion(bank_version=1, order=(i + 1) * 10, **{"client_visible": True, "internal_only": False, "options": [], "sum_of": [], **q}))
    db.flush()
    return 1


def questions(db: Session, bank_version: int | None = None, *, include_inactive: bool = False) -> list[ScopingQuestion]:
    v = bank_version or ensure_seed(db)
    stmt = select(ScopingQuestion).where(ScopingQuestion.bank_version == v)
    if not include_inactive:
        stmt = stmt.where(ScopingQuestion.active.is_(True))
    rows = list(db.scalars(stmt))
    order = {s: i for i, s in enumerate(SECTIONS)}
    return sorted(rows, key=lambda q: (order.get(q.section, 99), q.order, q.code))


def by_code(db: Session, bank_version: int) -> dict[str, ScopingQuestion]:
    return {q.code: q for q in questions(db, bank_version, include_inactive=True)}


def _in_use(db: Session, version: int) -> bool:
    return db.scalar(select(ScopingQuestionnaire.id).where(ScopingQuestionnaire.bank_version == version).limit(1)) is not None


def _writable_version(db: Session, actor_id: str | None) -> int:
    """The bank version an edit goes into: the current one, or a copy of it when a questionnaire already uses it."""
    v = ensure_seed(db)
    if not _in_use(db, v):
        return v
    cur = db.get(ScopingBankVersion, db.scalar(select(ScopingBankVersion.id).where(ScopingBankVersion.version == v)))
    db.add(ScopingBankVersion(version=v + 1, label=cur.label if cur else STARTER_LABEL, note=cur.note if cur else None, created_by=actor_id))
    for q in db.scalars(select(ScopingQuestion).where(ScopingQuestion.bank_version == v)):
        cols = {c.key: getattr(q, c.key) for c in ScopingQuestion.__table__.columns if c.key not in ("id", "bank_version", "updated_at")}
        db.add(ScopingQuestion(bank_version=v + 1, **cols))
    db.flush()
    return v + 1


def _clean(changes: dict) -> dict:
    out = {k: v for k, v in changes.items() if k in EDITABLE and v is not None}
    errors = []
    if "type" in out and out["type"] not in QUESTION_TYPES:
        errors.append({"field": "type", "message": "Choose count, total, single, multi, yes_no or text."})
    if "section" in out and out["section"] not in SECTIONS:
        errors.append({"field": "section", "message": "Choose a section A to H or red flags."})
    if "label" in out and not str(out["label"]).strip():
        errors.append({"field": "label", "message": "Enter the question."})
    if "options" in out:
        opts = out["options"]
        if not isinstance(opts, list) or any(not isinstance(o, dict) or not str(o.get("value", "")).strip() or not str(o.get("label", "")).strip() for o in opts):
            errors.append({"field": "options", "message": "Each option needs a value and a label."})
    if errors:
        raise Invalid(errors=errors)
    if out.get("internal_only"):
        out["client_visible"] = False
    return out


def edit_question(db: Session, code: str, changes: dict, actor_id: str | None) -> ScopingQuestion:
    changes = _clean(changes)
    if not any(c.code == code for c in questions(db, include_inactive=True)):
        raise NotFound("That question is not in the bank.")
    v = _writable_version(db, actor_id)
    q = db.scalar(select(ScopingQuestion).where(ScopingQuestion.bank_version == v, ScopingQuestion.code == code))
    for k, val in changes.items():
        setattr(q, k, val)
    if q.type in ("single", "multi", "yes_no") and not q.options:
        raise Invalid(errors=[{"field": "options", "message": "Add at least one option."}])
    q.updated_by, q.updated_at = actor_id, utcnow()
    db.flush()
    return q


def add_question(db: Session, data: dict, actor_id: str | None) -> ScopingQuestion:
    code = str(data.get("code") or "").strip().upper()
    import re

    if not re.fullmatch(r"SQ-(A|B|C|D|E|F|G|H|RF)\.\d{2}", code):
        raise Invalid(errors=[{"field": "code", "message": "Use a code like SQ-C.13: the section letter, a dot and two digits."}])
    fields = _clean({**data, "section": code.split("-", 1)[1].split(".", 1)[0]})
    for need in ("label", "type"):
        if need not in fields:
            raise Invalid(errors=[{"field": need, "message": "Enter the question and choose its type."}])
    if any(c.code == code for c in questions(db, include_inactive=True)):
        raise Invalid(errors=[{"field": "code", "message": "That code is already in the bank."}])
    v = _writable_version(db, actor_id)
    order = (max((q.order for q in questions(db, v, include_inactive=True) if q.section == fields["section"]), default=0) + 10)
    q = ScopingQuestion(bank_version=v, code=code, order=fields.pop("order", order), updated_by=actor_id,
                        **{"client_visible": True, "internal_only": False, "options": [], "sum_of": [], **fields})
    if q.internal_only:
        q.client_visible = False
    db.add(q)
    db.flush()
    return q


def question_out(q: ScopingQuestion) -> dict:
    return {"code": q.code, "section": q.section, "section_label": SECTION_LABELS.get(q.section, q.section), "label": q.label,
            "client_label": q.client_label, "help": q.help, "type": q.type, "options": q.options or [], "sum_of": q.sum_of or [],
            "client_visible": q.client_visible, "internal_only": q.internal_only, "unknown_assumption": q.unknown_assumption, "order": q.order,
            "active": q.active}
