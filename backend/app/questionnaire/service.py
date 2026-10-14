"""Per-system and engagement-level assessment: who sees which questions, the template's golden rules, auto-drafted
findings and completion (spec §18.1, §19.1)."""
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.engagements.models import ClientRequirement, Engagement
from app.files.models import FileObject
from app.findings.models import DraftFindingLink, Finding
from app.questionnaire.models import RESPONSE_STATUSES, ChecklistItem, ChecklistResult, Question, Response, ResponseVersion
from app.questionnaire.rules import EngagementFacts, SystemContext, evaluate_finding, is_applicable
from app.questionnaire.seed import active_template_version
from app.systems.models import BUILT_BY, AISystem
from app.tenancy.models import Organization, User

LIGHT_CHECKLISTS = {"5.4", "9.3"}  # the checklists of the light sections (§5, §9); §7.3 covers all of §7, so it is full only
CLIENT_LOCKED = "Answers are locked after management representation; ask the auditor to reopen."
TEXT_LIMITS = {"text": 2000, "long_text": 20000, "person": 160}


@dataclass
class Target:
    """What is being assessed: one AI system, or the engagement itself (system None)."""

    engagement: Engagement
    system: AISystem | None = None

    @property
    def system_id(self) -> str | None:
        return self.system.id if self.system else None

    @property
    def label(self) -> str:
        return f"{self.system.reference_id} {self.system.name}" if self.system else (self.engagement.audit_ref or "the engagement")


# ---- context
def facts_for(db: Session, e: Engagement) -> EngagementFacts:
    from app.initiation.context import eu_operations
    from app.laws.models import Regulation

    fw = set(e.frameworks or [])
    org = db.get(Organization, e.client_id)
    regs = db.scalars(
        select(Regulation.short_name).join(ClientRequirement, ClientRequirement.regulation_id == Regulation.id)
        .where(ClientRequirement.engagement_id == e.id, ClientRequirement.in_scope.is_(True), ClientRequirement.deleted_at.is_(None))
    )
    bias_law = any(re.search(r"\b144\b|bias audit", n or "", re.I) for n in regs)
    return EngagementFacts(
        eu_in_scope="eu_ai_act" in fw or eu_operations(db, org), gdpr_in_scope="gdpr" in fw, hipaa_in_scope="hipaa" in fw, dpdp_in_scope="dpdp" in fw,
        bias_audit_in_scope=e.type == "ll144_bias_audit" or bias_law, industry=org.industry,
    )


def system_context(s: AISystem | None) -> SystemContext:
    return SystemContext(built_by=s.built_by if s else None, depth=s.assessment_depth if s else "full")  # type: ignore[arg-type]


def _responses(db: Session, t: Target) -> dict[str, Response]:
    rows = db.scalars(select(Response).where(Response.engagement_id == t.engagement.id, Response.ai_system_id.is_(None) if t.system is None else Response.ai_system_id == t.system.id, Response.deleted_at.is_(None)))
    return {r.question_id: r for r in rows}


def _answers(db: Session, t: Target) -> dict[str, object]:
    """Answers by question code for applicability rules: the engagement's own answers, then this system's."""
    qs = {q.id: q.code for q in db.scalars(select(Question))}
    out: dict[str, object] = {}
    for target in ([Target(t.engagement)] if t.system else []) + [t]:
        for r in _responses(db, target).values():
            if r.status in ("answered", "not_yet_in_place"):
                out[qs.get(r.question_id, "")] = r.value
    return out


def _bank(db: Session, scope: str) -> list[Question]:
    tv = active_template_version(db)
    if tv is None:
        return []
    return list(db.scalars(select(Question).where(Question.template_version_id == tv.id, Question.scope == scope).order_by(Question.order)))


def _in_build(build_types: list | None, s: AISystem | None) -> bool:
    return not build_types or (s is not None and s.built_by in build_types)


def questions_for(db: Session, t: Target, futran: bool) -> list[Question]:
    """The questions that apply: scope, build type, light depth, applicability rules; clients see only theirs."""
    s = t.system
    answers, ctx, facts = _answers(db, t), system_context(s), facts_for(db, t.engagement)
    out = []
    for q in _bank(db, "system" if s else "engagement"):
        if not futran and q.default_respondent != "client":
            continue
        if s is not None and s.assessment_depth == "light" and not q.light:
            continue
        if not _in_build(q.build_types, s):
            continue
        if not is_applicable(q.section_rule, answers, ctx, facts) or not is_applicable(q.applicability_rule, answers, ctx, facts):
            continue
        out.append(q)
    return out


def checklist_for(db: Session, t: Target) -> list[ChecklistItem]:
    tv = active_template_version(db)
    if tv is None:
        return []
    s = t.system
    answers, ctx, facts = _answers(db, t), system_context(s), facts_for(db, t.engagement)
    items = db.scalars(select(ChecklistItem).where(ChecklistItem.template_version_id == tv.id, ChecklistItem.scope == ("system" if s else "engagement")).order_by(ChecklistItem.order))
    return [
        i for i in items
        if (s is None or s.assessment_depth == "full" or i.section in LIGHT_CHECKLISTS) and _in_build(i.build_types, s) and is_applicable(i.applicability_rule, answers, ctx, facts)
    ]


def _question(db: Session, t: Target, code: str, futran: bool) -> Question:
    q = next((q for q in questions_for(db, t, futran) if q.code == code), None)
    if q is None:
        raise NotFound("This question does not apply here.")
    return q


# ---- validation
def _option_values(q: Question) -> list[str]:
    return [str(o["value"]) for o in q.options or []]


def _clean_value(q: Question, value):
    """Normalise an answer to the question's type. Raises Invalid on a value of the wrong shape."""
    bad = lambda msg: Invalid(errors=[{"field": "value", "message": msg}])  # noqa: E731
    if value in (None, "", []):
        return None
    t = q.type
    if t in ("single", "yes_no", "yes_no_unknown"):
        if str(value) not in _option_values(q):
            raise bad("Choose one of the options.")
        return str(value)
    if t == "multi":
        if not isinstance(value, list) or not all(str(v) in _option_values(q) for v in value):
            raise bad("Choose from the options.")
        return list(dict.fromkeys(str(v) for v in value))
    if t == "date":
        try:
            return date.fromisoformat(str(value)[:10]).isoformat()
        except ValueError:
            raise bad("Enter a date.") from None
    if t in ("number", "percent"):
        try:
            n = float(str(value).replace(",", "").strip())
        except ValueError:
            raise bad("Enter a number.") from None
        if n < 0 or n != n or n == float("inf") or (t == "percent" and n > 100):
            raise bad("Enter a percentage from 0 to 100." if t == "percent" else "Enter a number of 0 or more.")
        return int(n) if n.is_integer() else n
    if t == "person":
        if isinstance(value, dict):
            name, title = " ".join(str(value.get("name") or "").split()), " ".join(str(value.get("title") or "").split())
        else:
            name, title = " ".join(str(value).split()), ""
        if not name:
            return None
        if len(name) > 160 or len(title) > 160:
            raise bad("Names and titles must be 160 characters or fewer.")
        return {"name": name, "title": title or None}
    text = str(value).strip()
    limit = TEXT_LIMITS.get(t, 2000)
    if len(text) > limit:
        raise bad(f"Answers to this question must be {limit:,} characters or fewer.")
    return text


def _evidence(db: Session, t: Target, ids) -> list[str]:
    if ids in (None, ""):
        return []
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise Invalid(errors=[{"field": "evidence_ids", "message": "Choose evidence files from this engagement."}])
    out = []
    for fid in dict.fromkeys(ids):
        f = db.get(FileObject, fid)
        if f is None or f.deleted_at is not None or f.engagement_id != t.engagement.id or f.linked_type != "evidence":
            raise Invalid(errors=[{"field": "evidence_ids", "message": "Choose evidence files from this engagement."}])
        out.append(fid)
    return out


def _text(v, limit: int) -> str | None:
    return str(v).strip()[:limit] or None if v not in (None, "") else None


def _check_locks(db: Session, t: Target, futran: bool) -> None:
    if t.system is not None and t.system.status == "locked":
        raise Conflict("This system's assessment is locked.")
    if not futran and t.engagement.client_answers_locked_at is not None:
        raise Conflict(CLIENT_LOCKED)


# ---- saving
def save_response(db: Session, actor: User, t: Target, code: str, body: dict, futran: bool) -> Response:
    """Save one answer. Golden rules: N/A needs a reason; an auditor's verified answer needs its source person;
    "not yet in place" is stored as such and counts as No for findings."""
    _check_locks(db, t, futran)
    q = _question(db, t, code, futran)
    status = body.get("status") or "answered"
    if not isinstance(status, str) or status not in RESPONSE_STATUSES:
        raise Invalid(errors=[{"field": "status", "message": "Choose answered, not applicable, not yet in place or unanswered."}])
    value = _clean_value(q, body.get("value")) if status in ("answered", "not_yet_in_place") else None
    detail = _text(body.get("detail"), 20000)
    na_reason = _text(body.get("na_reason"), 4000) if status == "na" else None
    errs = []
    if status == "answered" and value is None:
        errs.append({"field": "value", "message": "Enter an answer, or mark the question not applicable."})
    if status == "na" and not na_reason:
        errs.append({"field": "na_reason", "message": "Say why this question does not apply."})
    evidence = _evidence(db, t, body.get("evidence_ids"))
    verified = bool(body.get("verified")) and futran
    src_name, src_title = _text(body.get("source_person_name"), 160), _text(body.get("source_person_title"), 160)
    if verified and status != "unanswered":
        if not src_name:
            errs.append({"field": "source_person_name", "message": "Name the person who gave this answer."})
        if not src_title:
            errs.append({"field": "source_person_title", "message": "Give that person's job title."})
    if errs:
        raise Invalid(errors=errs)

    r = db.scalar(select(Response).where(Response.engagement_id == t.engagement.id, Response.question_id == q.id, Response.ai_system_id.is_(None) if t.system is None else Response.ai_system_id == t.system.id))
    if r is None:
        r = Response(organization_id=t.engagement.client_id, engagement_id=t.engagement.id, ai_system_id=t.system_id, question_id=q.id, status="unanswered", evidence_ids=[], client_evidence_ids=[], created_by=actor.id)
        db.add(r)
    before = {"value": r.value, "status": r.status}
    now = utcnow()
    if futran:
        changed = (r.value, r.status, r.na_reason) != (value, status, na_reason)
        r.value, r.status, r.na_reason, r.detail, r.evidence_ids = value, status, na_reason, detail, evidence
        r.source_person_name, r.source_person_title = src_name, src_title
        r.answered_by, r.answered_side, r.answered_at = actor.id, "futran", now
        if verified:
            r.verified_by, r.verified_at = actor.id, now
        elif changed:
            r.verified_by = r.verified_at = None
    else:
        r.client_value, r.client_status, r.client_na_reason, r.client_detail, r.client_evidence_ids = value, status, na_reason, detail, evidence
        r.client_answered_by, r.client_answered_at = actor.id, now
        if r.answered_side != "futran" and r.verified_at is None:  # the client's answer stands until Futran records its own
            r.value, r.status, r.na_reason, r.detail, r.evidence_ids = value, status, na_reason, detail, evidence
            r.answered_by, r.answered_side, r.answered_at = actor.id, "client", now
    r.updated_by = actor.id
    db.flush()
    db.add(ResponseVersion(organization_id=r.organization_id, response_id=r.id, side="futran" if futran else "client", value=value, detail=detail, status=status, na_reason=na_reason,
                           source_person_name=src_name if futran else None, source_person_title=src_title if futran else None, evidence_ids=evidence, verified=verified, created_by=actor.id))
    audit.record(db, actor_id=actor.id, action="response.save", obj=r, before=before, after={"code": q.code, "value": value, "status": status, "side": "futran" if futran else "client", "verified": verified},
                 summary=f"Answered {q.code} for {t.label}{' (verified)' if verified else ''}")
    if t.system is not None:
        if q.code == "3.2.04" and t.system.built_by is None and r.value in BUILT_BY:
            t.system.built_by = r.value  # the answer sets the question set when the auditor has not chosen one yet
        if futran and t.system.status in ("not_started", "client_prefill"):
            t.system.status = "in_review"
        elif not futran and t.system.status == "not_started":
            t.system.status = "client_prefill"
    sync_draft_finding(db, actor, t, q, r)
    after_change(db, t)
    return r


def verify(db: Session, actor: User, r: Response) -> Response:
    e = db.get(Engagement, r.engagement_id)
    t = Target(e, db.get(AISystem, r.ai_system_id) if r.ai_system_id else None)
    _check_locks(db, t, True)
    if r.status == "unanswered":
        raise Conflict("There is no answer to verify yet.")
    if r.answered_side == "futran" and not (r.source_person_name and r.source_person_title):
        raise Invalid("Record who gave this answer before verifying it.", [{"field": "source_person_name", "message": "Name the person who gave this answer."}, {"field": "source_person_title", "message": "Give that person's job title."}])
    r.verified_by, r.verified_at = actor.id, utcnow()
    q = db.get(Question, r.question_id)
    audit.record(db, actor_id=actor.id, action="response.verify", obj=r, after={"code": q.code}, summary=f"Verified {q.code} for {t.label}")
    return r


def verify_section(db: Session, actor: User, t: Target, sub_section: str) -> int:
    """Verify every answered question in a section. Futran-recorded answers without a source person are listed."""
    qs = [q for q in questions_for(db, t, True) if q.sub_section == sub_section]
    if not qs:
        raise NotFound()
    rs = _responses(db, t)
    todo = [(q, rs[q.id]) for q in qs if q.id in rs and rs[q.id].status != "unanswered" and rs[q.id].verified_at is None]
    missing = [q.code for q, r in todo if r.answered_side == "futran" and not (r.source_person_name and r.source_person_title)]
    if missing:
        raise Invalid("Record who gave these answers first.", [{"field": c, "message": "Name the person who gave this answer and their job title."} for c in missing])
    for q, r in todo:
        verify(db, actor, r)
    return len(todo)


# ---- draft findings (golden rule 6)
def next_finding_ref(db: Session, e: Engagement) -> str:
    refs = db.scalars(select(Finding.ref).where(Finding.engagement_id == e.id))
    n = max((int(r[2:]) for r in refs if r and r[2:].isdigit()), default=0)
    return f"F-{n + 1:03d}"


def _display(q: Question, value) -> str:
    labels = {str(o["value"]): o["label"] for o in q.options or []}
    if isinstance(value, list):
        return ", ".join(labels.get(str(v), str(v)) for v in value) or "none"
    if isinstance(value, dict):
        return " · ".join(v for v in (value.get("name"), value.get("title")) if v)
    return labels.get(str(value), str(value)) if value not in (None, "") else "no answer"


def sync_draft_finding(db: Session, actor: User, t: Target, q: Question, r: Response) -> Finding | None:
    """Create, update or withdraw the draft finding an answer raises. A draft the auditor dismissed is not raised again."""
    if not q.finding_rule:
        return None
    draft = evaluate_finding(q.finding_rule, r.value, r.status, _answers(db, t), system_context(t.system), facts_for(db, t.engagement))
    links = list(db.scalars(select(DraftFindingLink).where(DraftFindingLink.response_id == r.id, DraftFindingLink.deleted_at.is_(None)).order_by(DraftFindingLink.created_at)))
    active = None
    for link in links:
        f = db.get(Finding, link.finding_id)
        if link.dismissed_at is None and f is not None and f.deleted_at is None:
            active = (link, f)
    untouched = active is not None and active[1].status == "draft" and active[1].confirmed_at is None
    if draft is None:
        if untouched:
            link, f = active
            f.deleted_at = utcnow()
            link.dismissed_at, link.dismissed_reason = utcnow(), "The answer changed and no longer raises this finding."
        return None
    nyip = " The client says this is planned but not yet in place." if draft.not_yet_in_place else ""
    description = f"Raised automatically from {q.code} ({q.label}). Answer: {_display(q, r.value) if r.status == 'answered' else 'not yet in place'}.{nyip}"
    if active is not None:
        link, f = active
        if untouched:
            f.title, f.severity, f.description, f.not_yet_in_place, f.null_compliance_flag = draft.title[:300], draft.severity, description, draft.not_yet_in_place, draft.null_compliance
        return f
    if any(link.dismissed_by and link.rule_title == draft.title for link in links):
        return None
    f = Finding(organization_id=t.engagement.client_id, engagement_id=t.engagement.id, ref=next_finding_ref(db, t.engagement), ai_system_id=t.system_id, template_section=q.sub_section,
                source_question_ids=[q.code], title=draft.title[:300], description=description, severity=draft.severity, author_id=None, status="draft", origin="auto_response",
                null_compliance_flag=draft.null_compliance, not_yet_in_place=draft.not_yet_in_place, use_case_ids=list(t.system.use_case_ids or []) if t.system else [], control_refs=[], created_by=actor.id)
    db.add(f)
    db.flush()
    db.add(DraftFindingLink(organization_id=f.organization_id, response_id=r.id, finding_id=f.id, rule_title=draft.title[:300], created_by=actor.id))
    audit.record(db, actor_id=actor.id, action="finding.auto_draft", obj=f, after={"ref": f.ref, "severity": f.severity, "question": q.code}, summary=f"Draft finding {f.ref} raised by the answer to {q.code} for {t.label}")
    db.flush()
    return f


def draft_findings(db: Session, t: Target) -> list[dict]:
    out = []
    rows = db.execute(
        select(DraftFindingLink, Finding, Response).join(Finding, Finding.id == DraftFindingLink.finding_id).join(Response, Response.id == DraftFindingLink.response_id)
        .where(Finding.engagement_id == t.engagement.id, Finding.deleted_at.is_(None), DraftFindingLink.dismissed_at.is_(None), Finding.status == "draft",
               Finding.ai_system_id.is_(None) if t.system is None else Finding.ai_system_id == t.system.id)
        .order_by(Finding.ref)
    )
    codes = {q.id: q.code for q in db.scalars(select(Question))}
    for link, f, r in rows:
        out.append({"id": link.id, "finding_id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "question_code": codes.get(r.question_id), "not_yet_in_place": f.not_yet_in_place, "confirmed": f.confirmed_at is not None})
    return out


def dismiss_draft(db: Session, actor: User, link: DraftFindingLink, reason: str | None) -> None:
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why this is not a finding."}])
    f = db.get(Finding, link.finding_id)
    if link.dismissed_at is not None or f is None or f.deleted_at is not None or f.status != "draft":
        raise Conflict("This draft finding has already been dealt with.")
    link.dismissed_at, link.dismissed_by, link.dismissed_reason = utcnow(), actor.id, reason[:2000]
    f.deleted_at = utcnow()
    audit.record(db, actor_id=actor.id, action="finding.dismiss_draft", obj=f, after={"reason": reason}, summary=f"Dismissed draft finding {f.ref}: {reason[:120]}")


def confirm_draft(db: Session, actor: User, link: DraftFindingLink) -> Finding:
    f = db.get(Finding, link.finding_id)
    if link.dismissed_at is not None or f is None or f.deleted_at is not None:
        raise Conflict("This draft finding has already been dealt with.")
    f.confirmed_at, f.confirmed_by, f.author_id = utcnow(), actor.id, f.author_id or actor.id
    audit.record(db, actor_id=actor.id, action="finding.confirm_draft", obj=f, summary=f"Kept draft finding {f.ref} for review")
    return f


# ---- checklists (golden rule 1)
def tick_checklist(db: Session, actor: User, t: Target, code: str, confirmed, evidence_ids, note) -> ChecklistResult:
    _check_locks(db, t, True)
    item = next((i for i in checklist_for(db, t) if i.code == code), None)
    if item is None:
        raise NotFound("This checklist item does not apply here.")
    if not isinstance(confirmed, bool):
        raise Invalid(errors=[{"field": "confirmed", "message": "Tick or untick the item."}])
    evidence = _evidence(db, t, evidence_ids)
    if confirmed and not evidence:
        raise Invalid(errors=[{"field": "evidence_ids", "message": "Link at least one evidence file before ticking this item."}])
    res = db.scalar(select(ChecklistResult).where(ChecklistResult.engagement_id == t.engagement.id, ChecklistResult.checklist_item_id == item.id, ChecklistResult.ai_system_id.is_(None) if t.system is None else ChecklistResult.ai_system_id == t.system.id))
    if res is None:
        res = ChecklistResult(organization_id=t.engagement.client_id, engagement_id=t.engagement.id, ai_system_id=t.system_id, checklist_item_id=item.id, created_by=actor.id)
        db.add(res)
    before = {"confirmed": res.confirmed}
    res.confirmed, res.evidence_ids, res.auditor_note, res.updated_by = confirmed, evidence, _text(note, 4000), actor.id
    res.confirmed_by, res.confirmed_at = (actor.id, utcnow()) if confirmed else (None, None)
    db.flush()
    audit.record(db, actor_id=actor.id, action="checklist.tick", obj=res, before=before, after={"code": code, "confirmed": confirmed, "evidence": len(evidence)}, summary=f"{'Ticked' if confirmed else 'Unticked'} checklist item {code} for {t.label}")
    after_change(db, t)
    return res


def checklist_results(db: Session, t: Target) -> dict[str, ChecklistResult]:
    rows = db.scalars(select(ChecklistResult).where(ChecklistResult.engagement_id == t.engagement.id, ChecklistResult.deleted_at.is_(None), ChecklistResult.ai_system_id.is_(None) if t.system is None else ChecklistResult.ai_system_id == t.system.id))
    return {r.checklist_item_id: r for r in rows}


# ---- completion
def completion(db: Session, t: Target, futran: bool = True) -> dict:
    """Answered (answered, N/A or not yet in place) over applicable, per section and overall."""
    qs = questions_for(db, t, futran)
    rs = _responses(db, t)

    def done(q: Question) -> bool:
        r = rs.get(q.id)
        status = (r.status if futran else r.client_status) if r else None
        return status in ("answered", "na", "not_yet_in_place")

    sections: dict[str, dict] = {}
    for q in qs:
        sec = sections.setdefault(q.sub_section, {"code": q.sub_section, "title": q.section_title, "answered": 0, "applicable": 0})
        sec["applicable"] += 1
        sec["answered"] += done(q)
    answered = sum(s["answered"] for s in sections.values())
    applicable = sum(s["applicable"] for s in sections.values())
    return {"answered": answered, "applicable": applicable, "pct": round(100 * answered / applicable) if applicable else 0, "sections": list(sections.values())}


def after_change(db: Session, t: Target) -> None:
    """Keep the system's completion current. The scoring engine hooks in here."""
    if t.system is None:
        return
    t.system.completion_pct = completion(db, t)["pct"]
    try:
        from app.scoring.service import recalculate
    except ImportError:
        return
    recalculate(db, t.system)


def submit_prefill(db: Session, settings, actor: User, t: Target) -> list[str]:
    """The client marks its pre-fill complete. Required questions need an answer, N/A with a reason, or not yet in place."""
    _check_locks(db, t, False)
    rs = _responses(db, t)
    missing = [q for q in questions_for(db, t, False) if q.required and (rs.get(q.id) is None or (rs[q.id].client_status or "unanswered") == "unanswered")]
    if missing:
        raise Invalid("Answer the required questions first, or mark them not applicable with a reason.", [{"field": q.code, "message": f"{q.code} {q.label}"} for q in missing])
    if t.system is not None and t.system.status in ("not_started", "client_prefill"):
        t.system.status = "in_review"
    audit.record(db, actor_id=actor.id, action="prefill.submit", obj=t.system or t.engagement, summary=f"Submitted the pre-fill for {t.label}")
    from app.notifications.service import futran_team, notify

    org = db.get(Organization, t.engagement.client_id)
    link = f"/systems/{t.system.id}/assess" if t.system else f"/clients/{org.id}/assessment"
    notify(db, futran_team(db, t.engagement), "prefill_submitted", f"{org.name}: pre-fill submitted for {t.label}", f"Submitted by {actor.name}.", link, engagement=t.engagement, settings=settings)
    return []
