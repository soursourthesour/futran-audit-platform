"""What every AI feature shares: the engagement switch (rule 4), the documents the model may read and their text, the
call to the model, and the AIInteraction written for every suggestion (rule 3)."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import AIClient, AIError, AIReply, client_for
from app.ai.models import AIInteraction, DocumentText
from app.ai.text import extract_pages, find_quote
from app.audit_log import service as audit
from app.auth.deps import Actor
from app.core.clock import utcnow
from app.core.errors import AppError, Conflict, Forbidden, Invalid
from app.core.ids import new_id
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import User

OFF = "AI features are off for this engagement. The Chief Auditor turns them on once the client has consented in the engagement letter."
DOC_TYPES = ("evidence", "governance_document")
MAX_PROMPT_CHARS = 160_000  # document text sent in one call; longer sets are cut, and the prompt says so


class AIUnavailable(AppError):
    status_code = 503

    def __init__(self, detail: str = "The AI model is not set up on this platform. Ask the Futran Admin to add the model key."):
        super().__init__(detail)


# ---- rule 4: the engagement switch
def ai_enabled(e: Engagement | None) -> bool:
    return bool(e is not None and e.ai_features_enabled)


def require_ai(e: Engagement | None) -> None:
    if not ai_enabled(e):
        raise Forbidden(OFF)


def _can(db: Session, actor: Actor, action: Action, e: Engagement) -> bool:
    try:
        authorize(db, actor, action, engagement_id=e.id)
        return True
    except (Forbidden, AppError):
        return False


def switch_out(db: Session, actor: Actor, e: Engagement) -> dict:
    if not actor.is_futran:
        return {"enabled": ai_enabled(e)}
    by = db.get(User, e.ai_enabled_by) if e.ai_enabled_by else None
    return {"enabled": ai_enabled(e), "consent_note": e.ai_consent_note, "enabled_by": by.name if by else None, "enabled_at": e.ai_enabled_at.isoformat() if e.ai_enabled_at else None,
            "can_manage": _can(db, actor, Action.MANAGE_AI_FEATURES, e), "can_use_copilot": _can(db, actor, Action.USE_COPILOT, e), "can_view_log": _can(db, actor, Action.VIEW_AI_LOG, e)}


def set_switch(db: Session, actor: User, e: Engagement, enabled, consent_note) -> Engagement:
    if not isinstance(enabled, bool):
        raise Invalid(errors=[{"field": "enabled", "message": "Turn AI features on or off."}])
    note = " ".join(str(consent_note or "").split())
    if enabled and not note:
        raise Invalid(errors=[{"field": "consent_note", "message": "Record where the client consented to AI-assisted review (for example, the engagement letter clause)."}])
    before = {"enabled": ai_enabled(e)}
    e.ai_features_enabled = enabled
    if enabled:
        e.ai_consent_note, e.ai_enabled_by, e.ai_enabled_at = note[:2000], actor.id, utcnow()
    e.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="ai.features_enabled" if enabled else "ai.features_disabled", obj=e, before=before, after={"enabled": enabled, "consent_note": note or None},
                 summary=f"{'Turned on' if enabled else 'Turned off'} AI features for {e.audit_ref or e.name}" + (f": {note[:160]}" if enabled else ""))
    return e


# ---- documents the model may read
@dataclass
class Doc:
    ref: str  # D1, D2 ... as the prompt names it
    file: FileObject
    pages: list[dict]
    error: str | None


def document_text(db: Session, settings, f: FileObject) -> DocumentText:
    """The file's text by page, extracted once per file content."""
    from app.files.service import read

    dt = db.scalar(select(DocumentText).where(DocumentText.file_id == f.id))
    if dt is not None and dt.sha256 == f.sha256:
        return dt
    try:
        method, pages, error = extract_pages(f.filename, read(settings, f))
    except OSError:
        method, pages, error = "none", [], "The stored file could not be read."
    if dt is None:
        dt = DocumentText(organization_id=f.organization_id, file_id=f.id, sha256=f.sha256, method=method, pages=pages, chars=0)
        db.add(dt)
    dt.sha256, dt.method, dt.pages, dt.chars, dt.error = f.sha256, method, pages, sum(len(p["text"]) for p in pages), error
    db.flush()
    return dt


def engagement_files(db: Session, e: Engagement, system_id: str | None = None) -> list[FileObject]:
    """Uploaded evidence and governance documents of the engagement: the system's own and the engagement-level ones."""
    rows = db.scalars(select(FileObject).where(FileObject.engagement_id == e.id, FileObject.linked_type.in_(DOC_TYPES), FileObject.deleted_at.is_(None),
                                               FileObject.scan_status != "infected").order_by(FileObject.created_at))
    from app.systems.models import AISystem

    others = set() if system_id is None else {s for s in db.scalars(select(AISystem.id).where(AISystem.engagement_id == e.id, AISystem.id != system_id))}
    return [f for f in rows if f.linked_id not in others]


def load_docs(db: Session, settings, files: list[FileObject]) -> list[Doc]:
    return [Doc(f"D{i + 1}", f, (dt := document_text(db, settings, f)).pages, dt.error) for i, f in enumerate(files)]


def docs_prompt(docs: list[Doc]) -> str:
    """The documents as the model sees them. Text past MAX_PROMPT_CHARS is left out and the prompt says so."""
    out, used, cut = [], 0, False
    for d in docs:
        if not d.pages:
            out.append(f"[{d.ref}] {d.file.filename}: no readable text.")
            continue
        out.append(f"[{d.ref}] {d.file.filename}")
        for p in d.pages:
            if used + len(p["text"]) > MAX_PROMPT_CHARS:
                cut = True
                break
            out.append(f"--- {d.ref} page {p['page']} ---\n{p['text']}")
            used += len(p["text"])
    if cut:
        out.append("(Some document text was left out because the set is long. Do not answer from text you were not given.)")
    return "\n".join(out) or "(No documents.)"


def docs_context(docs: list[Doc]) -> list[dict]:
    return [{"ref": d.ref, "filename": d.file.filename, "pages": d.pages} for d in docs]


def check_citation(docs: list[Doc], doc_ref, page, quote) -> dict | None:
    """A citation the model gave, checked against the cited document's text (rule 2). None when it names no document."""
    d = next((x for x in docs if x.ref == doc_ref), None)
    if d is None or not str(quote or "").strip():
        return None
    try:
        hint = int(page) if page is not None else None
    except (TypeError, ValueError):
        hint = None
    found_on = find_quote(d.pages, str(quote), hint)
    return {"file_id": d.file.id, "filename": d.file.filename, "page": found_on if found_on is not None else hint, "quote": str(quote).strip()[:2000], "found": found_on is not None}


# ---- the model call and its record
@dataclass
class Call:
    id: str
    reply: AIReply
    prompt_version: str


def model(app_state, settings) -> AIClient:
    c = client_for(app_state, settings)
    if c is None:
        raise AIUnavailable()
    return c


def call(app_state, settings, *, task: str, prompt_version: str, system: str, prompt: str, schema: dict, context: dict) -> Call:
    try:
        reply = model(app_state, settings).complete(task=task, system=system, prompt=prompt, schema=schema, context=context)
    except AIError as ex:
        raise AIUnavailable(f"{ex} Nothing was saved; try again.") from ex
    return Call(new_id(), reply, prompt_version)


def record(db: Session, actor: User, c: Call, *, organization_id: str, feature: str, engagement_id: str | None = None, ai_system_id: str | None = None, input_refs: list | None = None,
           target_type: str | None = None, target_id: str | None = None, target_code: str | None = None, output: dict | None = None, citations: list | None = None,
           confidence: str | None = None, status: str = "suggested", first: bool = True) -> AIInteraction:
    i = AIInteraction(organization_id=organization_id, engagement_id=engagement_id, ai_system_id=ai_system_id, feature=feature, call_id=c.id, model=c.reply.model, provider=c.reply.provider,
                      prompt_version=c.prompt_version, input_refs=input_refs or [], target_type=target_type, target_id=target_id, target_code=target_code, output=output or {},
                      citations=citations or [], confidence=confidence if confidence in ("high", "medium", "low") else None, status=status, result_refs=[],
                      input_tokens=c.reply.input_tokens if first else None, output_tokens=c.reply.output_tokens if first else None, created_by=actor.id)
    db.add(i)
    db.flush()
    return i


def log_call(db: Session, actor: User, c: Call, rows: list[AIInteraction], summary: str, engagement_id: str | None, organization_id: str) -> None:
    audit.record(db, actor_id=actor.id, action="ai.suggest", object_type="AIInteraction", object_id=rows[0].id if rows else None, organization_id=organization_id, engagement_id=engagement_id,
                 after={"call_id": c.id, "feature": rows[0].feature if rows else None, "model": c.reply.model, "provider": c.reply.provider, "prompt_version": c.prompt_version,
                        "suggestions": len(rows), "unsupported": sum(r.status == "unsupported" for r in rows)}, summary=summary)


def decide(db: Session, actor: User, i: AIInteraction, status: str, reason: str | None = None, result_refs: list | None = None) -> AIInteraction:
    """Record a person's decision on a suggestion (rule 3)."""
    if i.status not in ("suggested", "unsupported"):
        raise Conflict("This suggestion has already been decided.")
    if status in ("accepted", "edited") and i.status == "unsupported":
        raise Conflict("This suggestion has no supporting passage in the documents, so it cannot be accepted.")
    before = i.status
    i.status, i.decided_by, i.decided_at, i.reason = status, actor.id, utcnow(), (reason or None)
    i.result_refs = [*(i.result_refs or []), *(result_refs or [])]
    i.updated_by = actor.id
    label = {"accepted": "Accepted", "edited": "Accepted with edits", "rejected": "Rejected"}[status]
    audit.record(db, actor_id=actor.id, action=f"ai.{'accept' if status == 'accepted' else 'edit' if status == 'edited' else 'reject'}", obj=i, before={"status": before},
                 after={"status": status, "reason": reason, "results": result_refs or []}, summary=f"{label} AI suggestion{(' for ' + i.target_code) if i.target_code else ''}" + (f": {reason[:120]}" if reason else ""))
    return i


def reject(db: Session, actor: User, i: AIInteraction, reason) -> AIInteraction:
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why you are rejecting this suggestion."}])
    return decide(db, actor, i, "rejected", reason[:2000])


def interaction_out(db: Session, i: AIInteraction) -> dict:
    by = db.get(User, i.decided_by) if i.decided_by else None
    req = db.get(User, i.created_by) if i.created_by else None
    return {"id": i.id, "feature": i.feature, "call_id": i.call_id, "target_type": i.target_type, "target_id": i.target_id, "target_code": i.target_code, "output": i.output or {},
            "citations": i.citations or [], "confidence": i.confidence, "status": i.status, "decided_by": by.name if by else None, "decided_at": i.decided_at.isoformat() if i.decided_at else None,
            "reason": i.reason, "result_refs": i.result_refs or [], "follow_up": i.follow_up, "follow_up_ref": i.follow_up_ref, "model": i.model, "provider": i.provider,
            "prompt_version": i.prompt_version, "created_at": i.created_at.isoformat() if i.created_at else None, "requested_by": req.name if req else None, "ai_system_id": i.ai_system_id}
