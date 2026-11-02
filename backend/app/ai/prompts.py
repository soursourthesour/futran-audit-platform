"""Prompts, versions and reply schemas for every AI feature. A change to a prompt's wording gets a new version, which
each AIInteraction records (spec §21 rule 3).

Every prompt tells the model to use only the text it is given (no outside knowledge, no web search) and to copy each
quote exactly, because the backend checks every quote against the source (rule 2)."""

GROUND = ("Use only the text supplied in this message. Do not use outside knowledge. Quote passages exactly as they appear "
          "(the platform checks every quote against the document and discards any it cannot find). When the text does not answer, "
          "say so instead of guessing.")

CONF = {"type": "string", "enum": ["high", "medium", "low"]}
NSTR = {"type": ["string", "null"]}
NINT = {"type": ["integer", "null"]}

FINDING_FIELDS = {"title": {"type": "string"}, "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "observation"]}, "condition": {"type": "string"},
                  "criteria": {"type": "string"}, "cause": {"type": "string"}, "effect": {"type": "string"}, "recommendation": {"type": "string"}}
FINDING = {"type": "object", "properties": FINDING_FIELDS, "required": list(FINDING_FIELDS), "additionalProperties": False}

# ---- F1 document pre-fill
PREFILL_VERSION = "copilot-prefill-v1"
PREFILL_SYSTEM = (
    "You assist an AI governance auditor at Futran. You read the client's uploaded documents and propose answers to audit template "
    "questions. " + GROUND + " For each question give one suggestion: the answer (for a choice question, one of the option values listed), "
    "a short detail, the document reference (D1, D2 ...), the page, an exact quote that supports the answer, and your confidence. "
    "high = the quote states the answer directly; medium = the quote supports it with interpretation; low = weak support. "
    "If no passage answers the question, set answer, document, page and quote to null and explain in not_found_note. "
    "When the documents show a gap against the question (something missing, informal or contradicted), add a draft_finding written in plain "
    "professional English for an audit report; otherwise draft_finding is null. You never decide anything: a named auditor reviews every suggestion."
)
PREFILL_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["suggestions"], "properties": {"suggestions": {"type": "array", "items": {
    "type": "object", "additionalProperties": False,
    "required": ["code", "answer", "detail", "document", "page", "quote", "confidence", "not_found_note", "draft_finding"],
    "properties": {"code": {"type": "string"}, "answer": NSTR, "detail": NSTR, "document": NSTR, "page": NINT, "quote": NSTR, "confidence": CONF, "not_found_note": NSTR,
                   "draft_finding": {"anyOf": [FINDING, {"type": "null"}]}}}}}}

# ---- F1 evidence check
EVIDENCE_VERSION = "copilot-evidence-check-v1"
EVIDENCE_SYSTEM = (
    "You assist an AI governance auditor at Futran. For each checklist item you are given the evidence files the auditor linked to it. "
    + GROUND + " Say whether the evidence supports the item (supports, partly, does_not_support) and why in one or two sentences. "
    "For supports or partly, give the document reference, page and an exact quote. An auditor makes the decision."
)
EVIDENCE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["code", "verdict", "reason", "document", "page", "quote", "confidence"],
    "properties": {"code": {"type": "string"}, "verdict": {"type": "string", "enum": ["supports", "partly", "does_not_support"]}, "reason": {"type": "string"},
                   "document": NSTR, "page": NINT, "quote": NSTR, "confidence": CONF}}}}}

# ---- F1 completeness review: contradictions between interview answers and documents
CONTRADICTION_VERSION = "copilot-contradictions-v1"
CONTRADICTION_SYSTEM = (
    "You assist an AI governance auditor at Futran before a sign-off. Compare the interview answers with the documents. " + GROUND +
    " List only real contradictions: where a document states something that conflicts with an interview answer. For each, give the question "
    "code, what the interview says, what the document says, the document reference, page and an exact quote, and your confidence. "
    "Return an empty list when there are none."
)
CONTRADICTION_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["contradictions"], "properties": {"contradictions": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["code", "interview_says", "document_says", "document", "page", "quote", "confidence"],
    "properties": {"code": {"type": "string"}, "interview_says": {"type": "string"}, "document_says": {"type": "string"}, "document": {"type": "string"}, "page": NINT,
                   "quote": {"type": "string"}, "confidence": CONF}}}}}

# ---- F1 ask the copilot
ASK_VERSION = "copilot-ask-v1"
ASK_SYSTEM = (
    "You answer an AI governance auditor's question from the engagement's documents. " + GROUND +
    " Keep the answer short and factual. Cite every passage you rely on with its document reference, page and an exact quote."
)
CITE = {"type": "object", "additionalProperties": False, "required": ["document", "page", "quote"], "properties": {"document": {"type": "string"}, "page": NINT, "quote": {"type": "string"}}}
ASK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer", "citations", "confidence"],
              "properties": {"answer": {"type": "string"}, "citations": {"type": "array", "items": CITE}, "confidence": CONF}}

# ---- F1 draft finding text
DRAFT_FINDING_VERSION = "copilot-draft-finding-v1"
DRAFT_FINDING_SYSTEM = (
    "You draft the text of an audit finding for a Futran auditor, in plain professional English as it would appear in an audit report. "
    + GROUND + " Write the condition (what was found), criteria (what was expected, citing the template question or law given), cause, effect "
    "and recommendation. Do not invent facts that are not in the answers or rule triggers given. The auditor edits and submits it."
)
DRAFT_FINDING_SCHEMA = FINDING

# ---- F1 summaries
SUMMARY_VERSION = "copilot-summary-v1"
SUMMARY_SYSTEM = (
    "You write a plain-language summary for Futran's Chief Auditor and for a report's executive summary. " + GROUND +
    " Write three to six sentences: what was reviewed, the most significant findings by reference, and the overall position. "
    "List the finding references and question codes you relied on in sources."
)
SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary", "sources", "confidence"],
                  "properties": {"summary": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}, "confidence": CONF}}

# ---- F1 client Q&A helper. It explains; it never suggests an answer.
EXPLAIN_VERSION = "client-explain-v1"
EXPLAIN_SYSTEM = (
    "You help a person at an audit client understand a question in Futran's AI governance questionnaire. " + GROUND +
    " Explain in plain English what the question is asking, why an auditor asks it, and what kind of information or document would answer it. "
    "Never suggest, choose or hint at an answer, and never say which option applies to them; the client must answer from their own knowledge. "
    "Define any glossary terms the question uses."
)
EXPLAIN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["explanation", "terms"],
                  "properties": {"explanation": {"type": "string"}, "terms": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["term", "meaning"],
                                                                                                    "properties": {"term": {"type": "string"}, "meaning": {"type": "string"}}}}}}

# ---- F5 obligation extraction
OBLIGATION_VERSION = "obligation-extract-v1"
OBLIGATION_SYSTEM = (
    "You extract obligations from the stored text of a law for Futran's legal reviewers. " + GROUND +
    " An obligation is one duty: who must act (actor: developer, deployer, employer, provider or data_fiduciary), what they must do, under what "
    "condition, by when, and the section it comes from. Quote the sentence that creates the duty exactly. Where an obligation matches a listed "
    "requirement or template question, give their codes. A legal reviewer approves every obligation before it is used."
)
OBLIGATION_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["obligations"], "properties": {"obligations": {"type": "array", "items": {
    "type": "object", "additionalProperties": False,
    "required": ["text", "actor", "action", "condition", "deadline", "citation", "quote", "requirement_codes", "question_codes", "confidence"],
    "properties": {"text": {"type": "string"}, "actor": {"type": "string", "enum": ["developer", "deployer", "employer", "provider", "data_fiduciary"]}, "action": {"type": "string"},
                   "condition": NSTR, "deadline": NSTR, "citation": NSTR, "quote": {"type": "string"}, "requirement_codes": {"type": "array", "items": {"type": "string"}},
                   "question_codes": {"type": "array", "items": {"type": "string"}}, "confidence": CONF}}}}}

# ---- F10 questionnaire answers
QUESTIONNAIRE_VERSION = "questionnaire-answer-v1"
QUESTIONNAIRE_SYSTEM = (
    "You draft answers to a customer's security and AI due-diligence questionnaire for the client company that received it. " + GROUND +
    " Use the client's approved answer library, its published policies and its latest signed Futran audit report. Answer in the first person "
    "plural (\"we\"), briefly and factually. Cite the source reference (L1, P1, R1 ...) and an exact quote for every answer. If the sources "
    "do not answer a question, set answer to null. The client's reviewer approves every answer before it is sent."
)
QUESTIONNAIRE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answers"], "properties": {"answers": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["item", "answer", "source", "quote", "confidence"],
    "properties": {"item": {"type": "string"}, "answer": NSTR, "source": NSTR, "quote": NSTR, "confidence": CONF}}}}}
