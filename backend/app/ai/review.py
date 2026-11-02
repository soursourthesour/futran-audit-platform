"""Copilot features beyond pre-fill (spec §21 F1): evidence check, completeness review, "Ask the copilot", draft
finding text and summaries, plus accepting each of them. Every one is a suggestion until a named person accepts it."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import prompts as P
from app.ai import service as ai
from app.ai.models import AIInteraction
from app.auth.deps import Actor
from app.core.errors import Conflict, Invalid
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.findings.models import Finding
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.questionnaire import service as qs
from app.questionnaire.models import ChecklistItem, ChecklistResult, Question, Response
from app.systems.models import AISystem
from app.tenancy.models import User


def _live_files(db: Session, ids) -> list[FileObject]:
    out = []
    for fid in ids or []:
        f = db.get(FileObject, fid)
        if f is not None and f.deleted_at is None:
            out.append(f)
    return out


# ---- evidence check
def evidence_check(db: Session, app_state, settings, actor: User, t: qs.Target, section: str | None = None, code: str | None = None) -> list[dict]:
    ai.require_ai(t.engagement)
    items = [i for i in qs.checklist_for(db, t) if (section is None or i.section == section) and (code is None or i.code == code)]
    if not items:
        raise Invalid("No checklist items apply here.", [{"field": "section", "message": "Choose a checklist section."}])
    results = qs.checklist_results(db, t)
    linked = {i.id: _live_files(db, results[i.id].evidence_ids) if i.id in results else [] for i in items}
    out = {i.code: {"code": i.code, "text": i.text, "confirmed": bool(results.get(i.id) and results[i.id].confirmed), "status": "no_evidence", "suggestion": None} for i in items}
    checked = [i for i in items if linked[i.id]]
    if not checked:
        return list(out.values())
    files = list({f.id: f for i in checked for f in linked[i.id]}.values())
    docs = ai.load_docs(db, settings, files)
    ref_of = {d.file.id: d.ref for d in docs}
    lines = [f"- {i.code} {i.text} (linked: {', '.join(ref_of[f.id] for f in linked[i.id])})" for i in checked]
    prompt = f"System under audit: {t.label}\n\nChecklist items and their linked evidence:\n" + "\n".join(lines) + f"\n\nDocuments:\n{ai.docs_prompt(docs)}"
    c = ai.call(app_state, settings, task="evidence_check", prompt_version=P.EVIDENCE_VERSION, system=P.EVIDENCE_SYSTEM, prompt=prompt, schema=P.EVIDENCE_SCHEMA,
                context={"items": [{"code": i.code, "text": i.text, "documents": [ref_of[f.id] for f in linked[i.id]]} for i in checked], "documents": ai.docs_context(docs)})
    by_code = {x.get("code"): x for x in c.reply.data.get("items") or [] if isinstance(x, dict)}
    rows = []
    for n, i in enumerate(checked):
        x = by_code.get(i.code) or {}
        verdict = x.get("verdict") if x.get("verdict") in ("supports", "partly", "does_not_support") else None
        own = [d for d in docs if d.file in linked[i.id]]
        cite = ai.check_citation(own, x.get("document"), x.get("page"), x.get("quote"))
        supported = verdict is not None and (cite["found"] if cite else verdict == "does_not_support")
        output = {"verdict": verdict, "reason": x.get("reason") or "The copilot gave no assessment for this item.", "item": i.text}
        row = ai.record(db, actor, c, organization_id=t.engagement.client_id, feature="evidence_check", engagement_id=t.engagement.id, ai_system_id=t.system_id,
                        input_refs=[{"type": "file", "id": f.id} for f in linked[i.id]], target_type="checklist_item", target_id=i.id, target_code=i.code, output=output,
                        citations=[cite] if cite else [], confidence=x.get("confidence"), status="suggested" if supported else "unsupported", first=n == 0)
        rows.append(row)
        out[i.code] |= {"status": "checked", "suggestion": ai.interaction_out(db, row)}
    ai.log_call(db, actor, c, rows, f"Copilot checked the evidence for {len(rows)} checklist item{'s' if len(rows) != 1 else ''} of {t.label}", t.engagement.id, t.engagement.client_id)
    return list(out.values())


# ---- completeness review (before sign-offs 5 and 7)
def deterministic(db: Session, t: qs.Target) -> dict:
    """The parts of the completeness review that need no model."""
    questions = qs.questions_for(db, t, True)
    rs = qs._responses(db, t)
    unanswered = [{"code": q.code, "label": q.label, "sub_section": q.sub_section} for q in questions if q.required and (q.id not in rs or rs[q.id].status == "unanswered")]
    missing = [{"code": q.code, "label": q.label, "sub_section": q.sub_section} for q in questions
               if q.id in rs and rs[q.id].status != "unanswered" and rs[q.id].answered_side == "futran" and not (rs[q.id].source_person_name and rs[q.id].source_person_title)]
    items = {i.id: i for i in qs.checklist_for(db, t)}
    ticks = [{"code": items[r.checklist_item_id].code, "text": items[r.checklist_item_id].text} for r in qs.checklist_results(db, t).values()
             if r.confirmed and r.checklist_item_id in items and not _live_files(db, r.evidence_ids)]
    return {"unanswered_required": unanswered, "ticks_without_evidence": sorted(ticks, key=lambda x: x["code"]), "missing_source_person": missing}


def latest_contradictions(db: Session, t: qs.Target) -> list[AIInteraction]:
    last = db.scalar(select(AIInteraction.call_id).where(AIInteraction.engagement_id == t.engagement.id, AIInteraction.feature == "review_check",
                                                         AIInteraction.ai_system_id == t.system_id if t.system else AIInteraction.ai_system_id.is_(None))
                     .order_by(AIInteraction.created_at.desc()).limit(1))
    if last is None:
        return []
    rows = db.scalars(select(AIInteraction).where(AIInteraction.call_id == last).order_by(AIInteraction.target_code))
    return [r for r in rows if (r.output or {}).get("interview_says")]


def completeness_out(db: Session, t: qs.Target, signoff: int) -> dict:
    if signoff not in (5, 7):
        raise Invalid(errors=[{"field": "signoff", "message": "Choose sign-off 5 or 7."}])
    last = db.scalar(select(AIInteraction.created_at).where(AIInteraction.engagement_id == t.engagement.id, AIInteraction.feature == "review_check",
                                                            AIInteraction.ai_system_id == t.system_id).order_by(AIInteraction.created_at.desc()).limit(1))
    return {"signoff": signoff, **deterministic(db, t), "contradictions": [ai.interaction_out(db, r) for r in latest_contradictions(db, t)],
            "contradictions_checked_at": last.isoformat() if last else None}


def run_contradictions(db: Session, app_state, settings, actor: User, t: qs.Target) -> None:
    ai.require_ai(t.engagement)
    questions = {q.id: q for q in qs.questions_for(db, t, True)}
    interviews = [(questions[r.question_id], r) for r in qs._responses(db, t).values()
                  if r.question_id in questions and r.answered_side == "futran" and r.status != "unanswered" and r.source_person_name]
    files = ai.engagement_files(db, t.engagement, t.system_id)
    docs = ai.load_docs(db, settings, files)
    lines = [f"- {q.code} {q.label}: {qs._display(q, r.value) if r.status == 'answered' else r.status}" + (f" ({r.detail})" if r.detail else "")
             + f" — said by {r.source_person_name}, {r.source_person_title or 'no title'}" for q, r in interviews]
    prompt = f"System under audit: {t.label}\n\nInterview answers:\n" + ("\n".join(lines) or "(none)") + f"\n\nDocuments:\n{ai.docs_prompt(docs)}"
    c = ai.call(app_state, settings, task="review_check", prompt_version=P.CONTRADICTION_VERSION, system=P.CONTRADICTION_SYSTEM, prompt=prompt, schema=P.CONTRADICTION_SCHEMA,
                context={"interviews": [{"code": q.code, "label": q.label, "answer": qs._display(q, r.value), "detail": r.detail, "person": r.source_person_name} for q, r in interviews],
                         "documents": ai.docs_context(docs)})
    found = [x for x in c.reply.data.get("contradictions") or [] if isinstance(x, dict) and x.get("code")]
    refs = [{"type": "file", "id": d.file.id} for d in docs] + [{"type": "response", "id": r.id} for _, r in interviews]
    rows = []
    for n, x in enumerate(found):
        cite = ai.check_citation(docs, x.get("document"), x.get("page"), x.get("quote"))
        rows.append(ai.record(db, actor, c, organization_id=t.engagement.client_id, feature="review_check", engagement_id=t.engagement.id, ai_system_id=t.system_id, input_refs=refs,
                              target_type="question", target_code=str(x["code"])[:40], output={"interview_says": x.get("interview_says"), "document_says": x.get("document_says")},
                              citations=[cite] if cite else [], confidence=x.get("confidence"), status="suggested" if cite and cite["found"] else "unsupported", first=n == 0))
    if not rows:  # rule 3: every call is on record, also when it found nothing
        rows.append(ai.record(db, actor, c, organization_id=t.engagement.client_id, feature="review_check", engagement_id=t.engagement.id, ai_system_id=t.system_id, input_refs=refs,
                              target_type="system" if t.system else "engagement", target_id=t.system_id or t.engagement.id, output={"none_found": True}))
    ai.log_call(db, actor, c, rows, f"Copilot compared interview answers with the documents for {t.label}", t.engagement.id, t.engagement.client_id)


# ---- ask the copilot
def ask(db: Session, app_state, settings, actor: User, e: Engagement, system: AISystem | None, question) -> AIInteraction:
    ai.require_ai(e)
    question = " ".join(str(question or "").split())
    if not question:
        raise Invalid(errors=[{"field": "question", "message": "Type a question."}])
    files = ai.engagement_files(db, e, system.id if system else None)
    if not files:
        raise Invalid("There are no uploaded documents to answer from yet.", [{"field": "question", "message": "No documents."}])
    docs = ai.load_docs(db, settings, files)
    label = f"{system.reference_id} {system.name}" if system else (e.audit_ref or e.name)
    prompt = f"Engagement: {e.audit_ref or e.name}\nScope of the question: {label}\n\nQuestion: {question[:2000]}\n\nDocuments:\n{ai.docs_prompt(docs)}"
    c = ai.call(app_state, settings, task="ask", prompt_version=P.ASK_VERSION, system=P.ASK_SYSTEM, prompt=prompt, schema=P.ASK_SCHEMA,
                context={"question": question, "documents": ai.docs_context(docs)})
    cites = [ai.check_citation(docs, x.get("document"), x.get("page"), x.get("quote")) for x in c.reply.data.get("citations") or [] if isinstance(x, dict)]
    cites = [x for x in cites if x]
    supported = bool(cites) and all(x["found"] for x in cites)
    row = ai.record(db, actor, c, organization_id=e.client_id, feature="ask", engagement_id=e.id, ai_system_id=system.id if system else None,
                    input_refs=[{"type": "file", "id": d.file.id} for d in docs], target_type="system" if system else "engagement", target_id=system.id if system else e.id,
                    output={"question": question, "answer": str(c.reply.data.get("answer") or "")[:8000]}, citations=cites, confidence=c.reply.data.get("confidence"),
                    status="suggested" if supported else "unsupported")
    ai.log_call(db, actor, c, [row], f"Copilot answered a question about {label}", e.id, e.client_id)
    return row


# ---- draft finding text
def _answers_for(db: Session, f: Finding) -> list[tuple[Question, Response]]:
    codes = set(f.source_question_ids or [])
    if not codes:
        return []
    qrows = {q.id: q for q in db.scalars(select(Question).where(Question.code.in_(codes)))}
    rows = db.scalars(select(Response).where(Response.engagement_id == f.engagement_id, Response.question_id.in_(list(qrows)), Response.deleted_at.is_(None),
                                             Response.ai_system_id.is_(None) if f.ai_system_id is None else Response.ai_system_id == f.ai_system_id))
    return [(qrows[r.question_id], r) for r in rows]


def draft_finding_text(db: Session, app_state, settings, actor: User, f: Finding) -> AIInteraction:
    from app.findings.models import DraftFindingLink
    from app.findings.service import EDITABLE

    e = db.get(Engagement, f.engagement_id)
    ai.require_ai(e)
    if f.status not in EDITABLE:
        raise Conflict("Only a draft or returned finding can be redrafted.")
    answers = _answers_for(db, f)
    rule = db.scalar(select(DraftFindingLink.rule_title).where(DraftFindingLink.finding_id == f.id))
    s = db.get(AISystem, f.ai_system_id) if f.ai_system_id else None
    lines = [f"- {q.code} {q.label}: {qs._display(q, r.value) if r.status == 'answered' else r.status.replace('_', ' ')}" + (f". Detail: {r.detail}" if r.detail else "") for q, r in answers]
    prompt = (f"Finding {f.ref} ({f.severity}): {f.title}\nSystem: {(s.reference_id + ' ' + s.name) if s else 'engagement level'}\nCurrent text: {f.description or '(none)'}\n"
              f"Rule that raised it: {rule or 'none (raised by the auditor)'}\n\nAnswers:\n" + ("\n".join(lines) or "(none)"))
    c = ai.call(app_state, settings, task="draft_finding", prompt_version=P.DRAFT_FINDING_VERSION, system=P.DRAFT_FINDING_SYSTEM, prompt=prompt, schema=P.DRAFT_FINDING_SCHEMA,
                context={"finding": {"ref": f.ref, "title": f.title, "severity": f.severity, "description": f.description}, "rule": rule,
                         "answers": [{"code": q.code, "label": q.label, "answer": qs._display(q, r.value), "detail": r.detail} for q, r in answers]})
    d = {k: c.reply.data.get(k) for k in P.FINDING_FIELDS}
    cites = [{"source_type": "response", "source_id": r.id, "label": q.code, "quote": qs._display(q, r.value) if r.status == "answered" else r.status, "found": True} for q, r in answers]
    row = ai.record(db, actor, c, organization_id=e.client_id, feature="draft_finding", engagement_id=e.id, ai_system_id=f.ai_system_id,
                    input_refs=[{"type": "finding", "id": f.id}] + [{"type": "response", "id": r.id} for _, r in answers], target_type="finding", target_id=f.id, target_code=f.ref,
                    output=d, citations=cites, confidence="medium" if answers else "low", status="suggested" if d.get("title") else "unsupported")
    ai.log_call(db, actor, c, [row], f"Copilot drafted the text of finding {f.ref}", e.id, e.client_id)
    return row


# ---- summaries
def _system_facts(db: Session, e: Engagement, s: AISystem) -> tuple[list[str], set[str]]:
    t = qs.Target(e, s)
    qs_by_id = {q.id: q for q in qs.questions_for(db, t, True)}
    facts, refs = [f"System {s.reference_id} {s.name}: built by {s.built_by or 'not set'}, {s.assessment_depth} assessment, status {s.status}."], set()
    for r in qs._responses(db, t).values():
        q = qs_by_id.get(r.question_id)
        if q and r.status in ("answered", "not_yet_in_place"):
            facts.append(f"  {q.code} {q.label}: {qs._display(q, r.value) if r.status == 'answered' else 'not yet in place'}")
            refs.add(q.code)
    return facts, refs


def summary(db: Session, app_state, settings, actor: User, e: Engagement, kind: str, system: AISystem | None = None) -> AIInteraction:
    from app.findings.service import findings_for
    from app.systems.service import systems_for
    from app.tenancy.models import Organization

    ai.require_ai(e)
    if kind not in ("system", "engagement", "client"):
        raise Invalid(errors=[{"field": "kind", "message": "Choose a system, engagement or client summary."}])
    org = db.get(Organization, e.client_id)
    facts, refs = [f"Client: {org.name}. Engagement {e.audit_ref}: {e.name}, stage {e.stage}."], set()
    systems = [system] if kind == "system" and system else systems_for(db, e)
    for s in systems:
        fs, rs = _system_facts(db, e, s)
        facts += fs if kind == "system" else fs[:1]
        refs |= rs
    findings = [f for f in findings_for(db, e) if kind != "system" or f.ai_system_id == (system.id if system else None)]
    for f in findings:
        facts.append(f"Finding {f.ref} ({f.severity}, {f.status}): {f.title}")
        refs.add(f.ref)
    label = f"{system.reference_id} {system.name}" if kind == "system" and system else (org.name if kind == "client" else e.audit_ref)
    prompt = f"Write a {kind} summary of {label}.\n\nFacts:\n" + "\n".join(facts)
    c = ai.call(app_state, settings, task="summary", prompt_version=P.SUMMARY_VERSION, system=P.SUMMARY_SYSTEM, prompt=prompt, schema=P.SUMMARY_SCHEMA,
                context={"kind": kind, "label": label, "facts": facts, "refs": sorted(refs)})
    sources = [str(x) for x in c.reply.data.get("sources") or []]
    cites = [{"source_type": "record", "source_id": None, "label": x, "quote": None, "found": x in refs} for x in sources]
    supported = bool(cites) and all(x["found"] for x in cites)
    row = ai.record(db, actor, c, organization_id=e.client_id, feature="summary", engagement_id=e.id, ai_system_id=system.id if system else None,
                    input_refs=[{"type": "system", "id": s.id} for s in systems] + [{"type": "finding", "id": f.id} for f in findings], target_type=kind,
                    target_id=system.id if kind == "system" and system else (org.id if kind == "client" else e.id), output={"kind": kind, "summary": str(c.reply.data.get("summary") or "")},
                    citations=cites, confidence=c.reply.data.get("confidence"), status="suggested" if supported else "unsupported")
    ai.log_call(db, actor, c, [row], f"Copilot wrote a {kind} summary of {label}", e.id, e.client_id)
    return row


# ---- accepting the suggestions above
def accept(db: Session, actor: Actor, i: AIInteraction, body: dict) -> AIInteraction:
    from app.findings.service import update_finding
    from app.policy.sod import assert_not_admin_judgment

    user = actor.user
    if i.feature == "evidence_check":
        authorize(db, actor, Action.VERIFY_SYSTEM_ANSWERS, engagement_id=i.engagement_id)
        e = db.get(Engagement, i.engagement_id)
        t = qs.Target(e, db.get(AISystem, i.ai_system_id) if i.ai_system_id else None)
        qs._check_locks(db, t, True)
        res = db.scalar(select(ChecklistResult).where(ChecklistResult.engagement_id == e.id, ChecklistResult.checklist_item_id == i.target_id, ChecklistResult.deleted_at.is_(None),
                                                      ChecklistResult.ai_system_id == i.ai_system_id if i.ai_system_id else ChecklistResult.ai_system_id.is_(None)))
        if res is None:
            raise Conflict("This checklist item has no linked evidence any more.")
        out = i.output or {}
        verdict = {"supports": "supports the item", "partly": "partly supports the item", "does_not_support": "does not support the item"}.get(out.get("verdict"), "")
        note = f"Evidence check (copilot, accepted by {user.name}): the evidence {verdict}. {out.get('reason') or ''}".strip()
        res.auditor_note = "\n".join(x for x in (res.auditor_note, note) if x)[:4000]
        res.updated_by = user.id
        return ai.decide(db, user, i, "accepted", result_refs=[{"type": "checklist_result", "id": res.id}])
    if i.feature == "draft_finding":
        authorize(db, actor, Action.RECORD_FINDINGS, engagement_id=i.engagement_id)
        assert_not_admin_judgment(actor)
        f = db.get(Finding, i.target_id)
        d = (i.output or {}) | {k: v for k, v in body.items() if k in P.FINDING_FIELDS}
        edited = any(k in P.FINDING_FIELDS and body[k] != (i.output or {}).get(k) for k in body)
        parts = [f"{k.title()}: {str(d.get(k) or '').strip()}" for k in ("condition", "criteria", "cause", "effect") if str(d.get(k) or "").strip()]
        data = {"title": d.get("title"), "description": "\n".join(parts), "recommended_remediation": d.get("recommendation")}
        if d.get("severity"):
            data["severity"] = d["severity"]
        update_finding(db, user, f, data)
        return ai.decide(db, user, i, "edited" if edited else "accepted", result_refs=[{"type": "finding", "id": f.id}])
    if i.feature == "summary":
        refs = []
        if body.get("use_in_report"):
            from app.reports.service import narrative, save_narrative

            if (i.output or {}).get("kind") == "system":
                raise Invalid(errors=[{"field": "use_in_report", "message": "Use an engagement or client summary in the report."}])
            authorize(db, actor, Action.RECORD_FINDINGS, engagement_id=i.engagement_id)
            assert_not_admin_judgment(actor)
            e = db.get(Engagement, i.engagement_id)
            n = narrative(db, e)
            keep = {k: getattr(n, k) for k in ("most_significant_finding_id", "most_significant_text", "strengths", "immediate_actions")} if n else {}
            text = str(body.get("summary") or (i.output or {}).get("summary") or "")
            # a narrative someone already wrote is replaced only on an explicit "replace" (the audit log keeps the old text)
            if n is not None and (n.narrative or "").strip() and n.narrative.strip() != text.strip() and body.get("replace_narrative") is not True:
                raise Conflict("The report already has a written narrative. Confirm that the summary should replace it; the current text is kept in the audit log.")
            n = save_narrative(db, user, e, keep | {"narrative": text})
            refs.append({"type": "report_narrative", "id": n.id})
        edited = bool(body.get("summary")) and body["summary"] != (i.output or {}).get("summary")
        return ai.decide(db, user, i, "edited" if edited else "accepted", result_refs=refs)
    if i.feature in ("ask", "review_check"):
        return ai.decide(db, user, i, "accepted")
    raise Conflict("This suggestion cannot be accepted here.")


def item_for(db: Session, i: AIInteraction) -> ChecklistItem | None:
    return db.get(ChecklistItem, i.target_id) if i.target_type == "checklist_item" else None
