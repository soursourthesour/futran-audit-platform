"""The AI audit copilot on the system assessment (spec §21 F1, screen 25).

Pre-fill proposes an answer per template question from the engagement's uploaded documents; an auditor accepts, edits
or rejects each one. Accepting writes the answer as the auditor's own (`Response.source = ai_suggested_accepted`),
unverified, with the cited file linked as evidence when it is an evidence upload, and the citation in the detail."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import prompts as P
from app.ai import service as ai
from app.ai.models import AIInteraction
from app.audit_log import service as audit
from app.core.errors import Conflict, Invalid, NotFound
from app.engagements.models import Engagement
from app.findings.models import SEVERITIES, Finding
from app.questionnaire import service as qs
from app.questionnaire.models import Question
from app.systems.models import AISystem
from app.tenancy.models import User

CHOICE = ("single", "yes_no", "yes_no_unknown")


def target_of(db: Session, i: AIInteraction) -> qs.Target:
    e = db.get(Engagement, i.engagement_id)
    return qs.Target(e, db.get(AISystem, i.ai_system_id) if i.ai_system_id else None)


def _question_view(q: Question) -> dict:
    return {"code": q.code, "label": q.label, "help": q.help_text, "type": q.type, "options": [{"value": str(o["value"]), "label": o["label"]} for o in q.options or []]}


def questions_prompt(questions: list[Question]) -> str:
    lines = []
    for q in questions:
        opts = "; ".join(f"{o['value']} = {o['label']}" for o in q.options or [])
        lines.append(f"- {q.code} ({q.type}) {q.label}" + (f". Help: {q.help_text}" if q.help_text else "") + (f". Options: {opts}" if opts else ""))
    return "\n".join(lines)


def _value(q: Question, raw):
    """The model's answer as the question's value, or None when it does not fit the question."""
    if raw in (None, ""):
        return None
    if q.type == "multi":
        raw = [x.strip() for x in str(raw).split(",") if x.strip()]
    try:
        return qs._clean_value(q, raw)
    except Invalid:
        return None


def prefill(db: Session, app_state, settings, actor: User, t: qs.Target, sub_section: str, file_ids: list | None = None) -> list[AIInteraction]:
    ai.require_ai(t.engagement)
    qs._check_locks(db, t, True)
    questions = [q for q in qs.questions_for(db, t, True) if q.sub_section == sub_section]
    if not questions:
        raise NotFound("No questions in this section apply here.")
    files = ai.engagement_files(db, t.engagement, t.system_id)
    if file_ids:
        files = [f for f in files if f.id in set(file_ids)]
    if not files:
        raise Invalid("Upload the client's documents as evidence first. The copilot only reads documents uploaded to this engagement.", [{"field": "file_ids", "message": "No documents to read."}])
    docs = ai.load_docs(db, settings, files)
    prompt = (f"System under audit: {t.label}\nSection: §{sub_section} {questions[0].section_title}\n\nQuestions:\n{questions_prompt(questions)}\n\n"
              f"Documents:\n{ai.docs_prompt(docs)}")
    c = ai.call(app_state, settings, task="copilot_prefill", prompt_version=P.PREFILL_VERSION, system=P.PREFILL_SYSTEM, prompt=prompt, schema=P.PREFILL_SCHEMA,
                context={"questions": [_question_view(q) for q in questions], "documents": ai.docs_context(docs)})
    by_code = {}
    for s in c.reply.data.get("suggestions") or []:
        if isinstance(s, dict) and isinstance(s.get("code"), str):
            by_code.setdefault(s["code"], s)
    refs = [{"type": "file", "id": d.file.id} for d in docs]
    rows = []
    for n, q in enumerate(questions):
        s = by_code.get(q.code) or {}
        value = _value(q, s.get("answer"))
        cite = ai.check_citation(docs, s.get("document"), s.get("page"), s.get("quote"))
        note = s.get("not_found_note") or None
        if s.get("answer") in (None, ""):
            note = note or "No passage in the uploaded documents answers this question."
        elif value is None:
            note = "The suggested answer does not fit this question's options."
        elif cite is None:
            note = "The suggestion cites no passage."
        elif cite.get("too_short"):
            note = "The quoted passage is too short to show that the document supports the answer."
        elif not cite["found"]:
            note = "The quoted passage is not in the cited document."
        supported = value is not None and cite is not None and cite["found"]
        draft = s.get("draft_finding") if isinstance(s.get("draft_finding"), dict) and supported else None
        output = {"value": value, "display": qs._display(q, value) if value is not None else None, "detail": (s.get("detail") or None), "note": None if supported else note,
                  "draft_finding": draft, "question": {"code": q.code, "label": q.label, "type": q.type, "options": _question_view(q)["options"]}}
        rows.append(ai.record(db, actor, c, organization_id=t.engagement.client_id, feature="copilot_prefill", engagement_id=t.engagement.id, ai_system_id=t.system_id, input_refs=refs,
                              target_type="question", target_id=q.id, target_code=q.code, output=output, citations=[cite] if cite else [], confidence=s.get("confidence"),
                              status="suggested" if supported else "unsupported", first=n == 0))
    ai.log_call(db, actor, c, rows, f"Copilot read {len(docs)} document{'s' if len(docs) != 1 else ''} and proposed answers for §{sub_section} of {t.label}", t.engagement.id, t.engagement.client_id)
    return rows


def _finding_text(d: dict) -> tuple[str, str]:
    parts = [f"{k.title()}: {str(d.get(k) or '').strip()}" for k in ("condition", "criteria", "cause", "effect") if str(d.get(k) or "").strip()]
    return "\n".join(parts), str(d.get("recommendation") or "").strip()


def create_draft_finding(db: Session, actor: User, t: qs.Target, d: dict, question_code: str | None, sub_section: str | None) -> Finding:
    """A draft finding in the existing findings flow. It stays a draft until the auditor submits it for review."""
    from app.findings.service import assert_open

    assert_open(db, t.engagement)
    title = " ".join(str(d.get("title") or "").split())[:300]
    if not title:
        raise Invalid(errors=[{"field": "title", "message": "The draft finding needs a title."}])
    severity = d.get("severity") if d.get("severity") in SEVERITIES else "medium"
    description, recommendation = _finding_text(d)
    f = Finding(organization_id=t.engagement.client_id, engagement_id=t.engagement.id, ref=qs.next_finding_ref(db, t.engagement), ai_system_id=t.system_id, template_section=sub_section,
                source_question_ids=[question_code] if question_code else [], title=title, description=description or None, severity=severity, control_refs=[],
                recommended_remediation=recommendation or None, author_id=actor.id, status="draft", origin="ai_suggestion", confirmed_at=None,
                use_case_ids=list(t.system.use_case_ids or []) if t.system else [], created_by=actor.id)
    db.add(f)
    db.flush()
    audit.record(db, actor_id=actor.id, action="finding.ai_draft", obj=f, after={"ref": f.ref, "severity": severity, "question": question_code},
                 summary=f"Created draft finding {f.ref} from a copilot suggestion for {t.label}")
    return f


def accept(db: Session, actor: User, i: AIInteraction, body: dict) -> AIInteraction:
    """Accept (or edit and accept) a pre-fill suggestion; optionally create its draft finding."""
    if i.feature != "copilot_prefill":
        raise Conflict("Use the accept action for this kind of suggestion.")
    t = target_of(db, i)
    ai.require_ai(t.engagement)
    if i.status == "unsupported":
        raise Conflict("This suggestion has no supporting passage in the documents, so it cannot be accepted. Add it to the interview list or request evidence.")
    if i.status != "suggested":
        raise Conflict("This suggestion has already been decided.")
    out = i.output or {}
    draft = out.get("draft_finding")
    if body.get("create_finding") and not isinstance(draft, dict):
        raise Invalid(errors=[{"field": "create_finding", "message": "The copilot did not suggest a finding for this answer."}])
    q = db.get(Question, i.target_id)
    edited = ("value" in body and body["value"] != out.get("value")) or ("detail" in body and (body.get("detail") or None) != out.get("detail"))
    value = body["value"] if "value" in body else out.get("value")
    cite = (i.citations or [{}])[0]
    detail = body.get("detail") if "detail" in body else out.get("detail")
    citation = f"Copilot citation: {cite.get('filename')}, page {cite.get('page')}: \"{cite.get('quote')}\""
    detail = "\n".join(x for x in (str(detail or "").strip(), citation) if x)
    existing = qs._responses(db, t).get(q.id)
    evidence = list(existing.evidence_ids or []) if existing else []
    from app.files.models import FileObject

    f = db.get(FileObject, cite.get("file_id")) if cite.get("file_id") else None
    if f is not None and f.linked_type == "evidence" and f.engagement_id == t.engagement.id and f.deleted_at is None and f.id not in evidence:
        evidence.append(f.id)
    r = qs.save_response(db, actor, t, q.code, {"status": "answered", "value": value, "detail": detail, "evidence_ids": evidence,
                                                "source_person_name": existing.source_person_name if existing else None,
                                                "source_person_title": existing.source_person_title if existing else None}, futran=True)
    r.source = "ai_suggested_accepted"
    refs = [{"type": "response", "id": r.id}]
    if body.get("create_finding"):
        fnd = create_draft_finding(db, actor, t, draft, q.code, q.sub_section)
        refs.append({"type": "finding", "id": fnd.id})
    return ai.decide(db, actor, i, "edited" if edited else "accepted", result_refs=refs)


def accept_high(db: Session, actor: User, t: qs.Target, ids: list) -> int:
    """The explicit "Accept all high-confidence" click: each supported high-confidence suggestion is accepted and logged."""
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise Invalid(errors=[{"field": "ids", "message": "List the suggestions shown."}])
    n = 0
    for iid in dict.fromkeys(ids):
        i = db.get(AIInteraction, iid)
        if i is None or i.engagement_id != t.engagement.id or i.ai_system_id != t.system_id or i.feature != "copilot_prefill":
            continue
        if i.status == "suggested" and i.confidence == "high":
            accept(db, actor, i, {})
            n += 1
    return n


def to_interview(db: Session, actor: User, i: AIInteraction) -> AIInteraction:
    ai.require_ai(db.get(Engagement, i.engagement_id))
    if i.feature != "copilot_prefill":
        raise Conflict("Only pre-fill questions go on the interview list.")
    i.follow_up, i.follow_up_ref, i.updated_by = "interview", None, actor.id
    audit.record(db, actor_id=actor.id, action="ai.interview_list", obj=i, summary=f"Added {i.target_code} to the interview list")
    return i


def to_evidence_request(db: Session, settings, actor: User, i: AIInteraction, data: dict) -> AIInteraction:
    from app.docrequests import evidence_requests as er

    t = target_of(db, i)
    ai.require_ai(t.engagement)
    if i.feature != "copilot_prefill":
        raise Conflict("Only pre-fill questions raise evidence requests here.")
    q = db.get(Question, i.target_id)
    desc = data.get("description") or f"Evidence for {q.code} {q.label} ({t.label})"
    req = er.create(db, settings, actor, t.engagement, {"description": desc, "due_date": data.get("due_date"), "owner_user_id": data.get("owner_user_id")})
    req.ai_system_id = t.system_id
    i.follow_up, i.follow_up_ref, i.updated_by = "evidence_request", req.ref, actor.id
    audit.record(db, actor_id=actor.id, action="ai.evidence_request", obj=i, after={"request": req.ref}, summary=f"Requested evidence {req.ref} for {q.code} after the copilot found no passage")
    return i


def latest(db: Session, t: qs.Target, feature: str, sub_section: str | None = None) -> list[AIInteraction]:
    """The newest suggestion per target for this system and feature (a re-run replaces what the panel shows)."""
    rows = db.scalars(select(AIInteraction).where(AIInteraction.engagement_id == t.engagement.id, AIInteraction.feature == feature, AIInteraction.deleted_at.is_(None),
                                                  AIInteraction.ai_system_id.is_(None) if t.system is None else AIInteraction.ai_system_id == t.system.id)
                      .order_by(AIInteraction.created_at.desc()))
    seen, out = set(), []
    for r in rows:
        if r.target_code in seen:
            continue
        seen.add(r.target_code)
        out.append(r)
    if sub_section is not None:
        prefix = sub_section + "."
        out = [r for r in out if (r.target_code or "").startswith(prefix)]
    return sorted(out, key=lambda r: r.target_code or "")
