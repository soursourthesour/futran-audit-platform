"""Staff endpoints for SM-05 (record on the call), SM-06 (send to the client), SM-08 (review and lock) and the SM-14
Question bank and Mapping rules tabs."""
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.sales.models import Opportunity
from app.scoping import bank, bridge, rulebook, sending, service
from app.scoping.models import QuestionnaireSend
from app.tenancy.models import Organization, User

router = APIRouter(prefix="/scoping", tags=["scoping"])


def _can(db: Session, actor: Actor, action: Action) -> bool:
    try:
        authorize(db, actor, action)
        return True
    except (Forbidden, NotFound):
        return False


def _futran_only(actor: Actor) -> None:
    if not actor.is_futran:
        raise NotFound()


def _opp(db: Session, opp_id: str) -> Opportunity:
    o = db.get(Opportunity, opp_id)
    if o is None:
        raise NotFound()
    return o


def _q(db: Session, actor: Actor, qid: str, action: Action):
    _futran_only(actor)
    authorize(db, actor, action)
    return service.get(db, qid)


def _audit(db: Session, actor: Actor, request: Request, action: str, obj, summary: str) -> None:
    audit.record(db, actor_id=actor.id, action=action, obj=obj, organization_id=actor.organization.id, request=request, summary=summary)


def _names(db: Session, ids) -> dict:
    ids = [i for i in set(ids) if i]
    return {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _view(db: Session, actor: Actor, opp: Opportunity) -> dict:
    org = db.get(Organization, opp.organization_id)
    q = service.current(db, opp.id)
    head = {"opportunity": {"id": opp.id, "name": opp.service, "company": org.name if org else "", "stage": opp.stage,
                            "prospect": getattr(org, "status", None) == "prospect"},
            "can_work": _can(db, actor, Action.WORK_SCOPING)}
    if q is None:
        return {**head, "questionnaire": None}
    answers = service.effective_answers(db, q)
    rows = service._rows(db, q)
    qs = bank.questions(db, q.bank_version)
    labels = service._labels({x.code: x for x in qs})
    comp = service.completion(db, q, answers)
    sections = []
    for key in bank.SECTION_LABELS:
        in_sec = [x for x in qs if x.section == key]
        if not in_sec:
            continue
        sections.append({"key": key, "label": bank.SECTION_LABELS[key], "intro": bank.SECTION_INTROS.get(key), "internal": all(x.internal_only for x in in_sec),
                         "answered": comp.get(key, {}).get("answered", 0), "total": len(in_sec),
                         "questions": [bank.question_out(x) for x in in_sec]})
    ans_out = {}
    for code, a in answers.items():
        out = service._answer_out(a, labels, code)
        rep = rows.get(code, {}).get("rep")
        client = rows.get(code, {}).get("client")
        if rep is not None:
            out["note"] = rep.note
        out["client"] = service._answer_out(client, labels) if client is not None and a.source != "client" else None
        ans_out[code] = out
    lines = service.suggest_lines(db, q.id)
    found = bridge.catalog_items(db, [x["code"] for x in lines])
    items = found or {}
    for x in lines:
        item = items.get(x["code"])
        x["name"] = getattr(item, "name", None) if item is not None else None
        x["sellable_status"] = getattr(item, "sellable_status", None) if item is not None else None
        x["in_catalog"] = None if found is None else (item is not None and not bridge.is_retired(item))
    pending = [s for s in ("A", "B", "C", "D", "E", "F", "G", "H") if comp.get(s, {}).get("answered", 0) == 0 and any(x.section == s for x in qs)]
    return {**head, "questionnaire": _q_out(db, q), "bank": {"version": q.bank_version, "starter": bank.STARTER_NOTE.startswith("Starter")},
            "sections": sections, "answers": ans_out, "suggested": lines, "not_answered_sections": [bank.SECTION_LABELS[s] for s in pending],
            "estimate": service.estimate(db, q, lines), "assumptions": service.assumptions(db, q), "conflict_count": len(service.conflicts(db, q)),
            "rule_errors": service.rule_errors(db, q),
            "sends": [sending.send_out(db, s) for s in db.scalars(select(QuestionnaireSend).where(QuestionnaireSend.questionnaire_id == q.id)
                                                                 .order_by(QuestionnaireSend.sent_at))],
            "versions": [{"id": v.id, "version": v.version, "status": v.status} for v in service.versions(db, opp.id)]}


def _q_out(db: Session, q) -> dict:
    names = _names(db, [q.locked_by])
    return {"id": q.id, "version": q.version, "mode": q.mode, "status": q.status, "bank_version": q.bank_version, "locked": q.status == "locked",
            "locked_by_name": names.get(q.locked_by), "locked_at": q.locked_at.isoformat() if q.locked_at else None,
            "updated_at": q.updated_at.isoformat() if q.updated_at else None, "removed_lines": q.removed_lines or [], "proposal_id": q.proposal_id}


@router.get("/opportunities/{opp_id}")
def get_for_opportunity(opp_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.VIEW_SCOPING)
    return _view(db, actor, _opp(db, opp_id))


class StartIn(BaseModel):
    mode: str = "recorded"


@router.post("/opportunities/{opp_id}/start")
def start(opp_id: str, request: Request, body: StartIn | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.WORK_SCOPING)
    opp = _opp(db, opp_id)
    existed = service.current(db, opp.id)
    q = service.start(db, opp, actor.user, mode=(body.mode if body and body.mode in ("recorded", "sent", "hybrid") else "recorded"))
    if existed is None:
        _audit(db, actor, request, "scoping.start", q, f"Scoping questionnaire started for {opp.service}")
    db.commit()
    return _q_out(db, q)


class AnswersIn(BaseModel):
    answers: list[dict] = Field(default_factory=list, max_length=200)


@router.put("/{qid}/answers")
def save_answers(qid: str, body: AnswersIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid, Action.WORK_SCOPING)
    out = service.save_answers(db, q, body.answers, actor=actor.user)
    db.commit()
    return out


class LineIn(BaseModel):
    code: str
    reason: str = ""


@router.post("/{qid}/lines/remove")
def remove_line(qid: str, body: LineIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid, Action.WORK_SCOPING)
    service.remove_line(db, q, body.code, body.reason, actor.user)
    _audit(db, actor, request, "scoping.remove_line", q, f"Removed suggested line {body.code}: {body.reason.strip()}")
    db.commit()
    return {"removed": body.code}


@router.post("/{qid}/lines/restore")
def restore_line(qid: str, body: LineIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid, Action.WORK_SCOPING)
    service.restore_line(db, q, body.code, actor.user)
    db.commit()
    return {"restored": body.code}


# ---- SM-06
@router.get("/{qid}/send-options")
def send_options(qid: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid, Action.WORK_SCOPING)
    answers = {code for code, slots in service._rows(db, q).items() if slots}  # a total worked out from its parts still goes to the client
    qs = bank.questions(db, q.bank_version)
    sections = []
    for key, label in bank.SECTION_LABELS.items():
        in_sec = [x for x in qs if x.section == key]
        if not in_sec:
            continue
        visible = [x for x in in_sec if not x.internal_only]
        unanswered = [x for x in visible if x.code not in answers]
        sections.append({"key": key, "label": label, "internal": not visible, "unanswered": len(unanswered), "total": len(visible),
                         "questions": [{"code": x.code, "label": x.label, "internal_only": x.internal_only, "locked": x.internal_only,
                                        "answered": x.code in answers, "default": x.client_visible and not x.internal_only and x.code not in answers}
                                       for x in in_sec]})
    from app.mail import delivery

    sender = delivery.resolve_sender(db, request.app.state.settings, sending.futran_org(db).id, prefer="me", user_id=actor.id)
    opp = db.get(Opportunity, q.opportunity_id)
    contacts = bridge.opportunity_contacts(db, q.opportunity_id)
    return {"sections": sections, "contacts": contacts, "sender": sender.from_address or sender.label,
            "own_mailbox": sender.user_connection is not None, "subject": sending.SUBJECT, "message": sending.MESSAGE,
            "company": db.get(Organization, opp.organization_id).name if opp else "", "rep_name": actor.user.name,
            "expires_days": sending.LINK_DAYS, "reminder_choices": [{"value": "3,7", "label": "Day 3 and day 7"}, {"value": "3", "label": "Day 3 only"},
                                                                       {"value": "", "label": "None"}]}


class SendIn(BaseModel):
    contact: dict
    question_codes: list[str] = Field(min_length=1, max_length=200)
    due_on: date | None = None
    reminders: list[int] | None = None
    allow_forward: bool = True
    subject: str | None = None
    message: str | None = None


@router.post("/{qid}/send")
def send(qid: str, body: SendIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid, Action.WORK_SCOPING)
    s = sending.send(db, request.app.state.settings, q, actor.user, contact=body.contact, question_codes=body.question_codes, due_on=body.due_on,
                     reminders=body.reminders, allow_forward=body.allow_forward, subject=body.subject, message=body.message)
    _audit(db, actor, request, "scoping.send", s, f"Scoping questions sent to {s.contact_name} <{s.contact_email}>")
    db.commit()
    return sending.send_out(db, s)


@router.post("/sends/{send_id}/close")
def close_send(send_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.WORK_SCOPING)
    s = db.get(QuestionnaireSend, send_id)
    if s is None:
        raise NotFound()
    sending.revoke(db, s)
    _audit(db, actor, request, "scoping.close_link", s, f"Closed the scoping link for {s.contact_email}")
    db.commit()
    return sending.send_out(db, s)


# ---- SM-08
@router.get("/{qid}/review")
def review(qid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid, Action.VIEW_SCOPING)
    opp = db.get(Opportunity, q.opportunity_id)
    org = db.get(Organization, opp.organization_id) if opp else None
    qs = bank.questions(db, q.bank_version)
    rows = service._rows(db, q)
    labels = service._labels({x.code: x for x in qs})
    answers = service.effective_answers(db, q)
    side = []
    for x in qs:
        slots = rows.get(x.code, {})
        if not slots and x.code not in answers:
            continue
        side.append({"code": x.code, "label": x.label, "section": x.section, "internal_only": x.internal_only,
                     "rep": service._answer_out(slots.get("rep"), labels), "client": service._answer_out(slots.get("client"), labels),
                     "used": service._answer_out(answers.get(x.code), labels, x.code)})
    conflicts = service.conflicts(db, q)
    lines = service.suggest_lines(db, q.id)
    builder = bridge.proposal_builder()
    sends = list(db.scalars(select(QuestionnaireSend).where(QuestionnaireSend.questionnaire_id == q.id)))
    received = max((s.last_saved_at for s in sends if s.last_saved_at), default=None)
    return {"questionnaire": _q_out(db, q), "company": org.name if org else "", "opportunity_id": q.opportunity_id,
            "summary": f"Questionnaire v{q.version} · " + ("recorded on call" if any("rep" in r for r in rows.values()) else "no rep answers")
                       + (f" + client answers received {received.day} {received:%b}" if received else ""),
            "counts": {"answered": len(answers), "total": len(qs), "conflicts": len(conflicts), "unknown": sum(a.confidence == "unknown" for a in answers.values()),
                       "lines": len([x for x in lines if not x["removed_reason"]])},
            "conflicts": conflicts, "unknowns": service.unknowns(db, q), "answers": side, "suggested": lines, "assumptions": service.assumptions(db, q),
            "rule_errors": service.rule_errors(db, q),
            "can_work": _can(db, actor, Action.WORK_SCOPING), "can_build_proposal": builder is not None,
            "build_note": None if builder is not None else "The proposal builder is not available yet. Lock the questionnaire now; build the proposal when it is.",
            "versions": [{"id": v.id, "version": v.version, "status": v.status} for v in service.versions(db, q.opportunity_id)]}


class ResolveIn(BaseModel):
    code: str
    keep: str
    value: object | None = None


@router.post("/{qid}/resolve")
def resolve(qid: str, body: ResolveIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid, Action.WORK_SCOPING)
    service.resolve(db, q, body.code, body.keep, body.value, actor.user)
    _audit(db, actor, request, "scoping.resolve", q, f"{body.code}: kept the {body.keep} answer")
    db.commit()
    return {"conflicts": len(service.conflicts(db, q))}


class LockIn(BaseModel):
    build_proposal: bool = False


@router.post("/{qid}/lock")
def lock(qid: str, request: Request, body: LockIn | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _q(db, actor, qid, Action.WORK_SCOPING)
    q = service.lock(db, qid, actor.user)
    _audit(db, actor, request, "scoping.lock", q, f"Scoping questionnaire version {q.version} locked")
    builder = bridge.proposal_builder() if body and body.build_proposal else None
    if builder is not None:
        p = builder(db, q, actor.user)
        q.proposal_id = getattr(p, "id", None)
    db.commit()
    return _q_out(db, q)


@router.post("/{qid}/unlock")
def unlock(qid: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _q(db, actor, qid, Action.WORK_SCOPING)
    q = service.unlock(db, qid, actor.user)
    _audit(db, actor, request, "scoping.unlock", q, f"Scoping questionnaire unlocked; version {q.version} started")
    db.commit()
    return _q_out(db, q)


# ---- SM-14 Question bank tab
@router.get("/bank")
def get_bank(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.VIEW_SCOPING_SETUP)
    from app.scoping.models import ScopingBankVersion

    v = bank.ensure_seed(db)
    bv = db.scalar(select(ScopingBankVersion).where(ScopingBankVersion.version == v))
    rows = bank.questions(db, v, include_inactive=True)
    db.commit()
    return {"version": v, "label": bv.label if bv else "", "note": bv.note if bv else None, "can_edit": _can(db, actor, Action.MANAGE_SCOPING_BANK),
            "sections": [{"key": k, "label": label} for k, label in bank.SECTION_LABELS.items()], "types": list(bank.QUESTION_TYPES),
            "questions": [bank.question_out(x) for x in rows]}


@router.put("/bank/questions/{code}")
def edit_question(code: str, body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.MANAGE_SCOPING_BANK)
    q = bank.edit_question(db, code, body, actor.id)
    audit.record(db, actor_id=actor.id, action="scoping.bank_edit", obj=q, organization_id=actor.organization.id, request=request,
                 summary=f"Question {code} edited (bank version {q.bank_version})")
    db.commit()
    return {"version": q.bank_version, "question": bank.question_out(q)}


@router.post("/bank/questions")
def add_question(body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.MANAGE_SCOPING_BANK)
    q = bank.add_question(db, body, actor.id)
    audit.record(db, actor_id=actor.id, action="scoping.bank_add", obj=q, organization_id=actor.organization.id, request=request,
                 summary=f"Question {q.code} added (bank version {q.bank_version})")
    db.commit()
    return {"version": q.bank_version, "question": bank.question_out(q)}


# ---- SM-14 Mapping rules tab
def _bank_codes(db: Session) -> dict[str, str]:
    """Question code -> answer type, for checking rules."""
    return {x.code: x.type for x in bank.questions(db, include_inactive=True)}


def _rule_view(db: Session, r, flags: dict | None = None) -> dict:
    flags = flags if flags is not None else {**rulebook.flags(db, [r]), **rulebook.run_flags(db, [r])}
    return rulebook.rule_out(r, flags.get(r.code), _names(db, [r.pending_by, r.approved_by]))


@router.get("/rules")
def get_rules(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.VIEW_SCOPING_SETUP)
    rows = rulebook.all_rules(db)
    flags = {**rulebook.flags(db, rows), **rulebook.run_flags(db, rows)}
    names = _names(db, [x for r in rows for x in (r.pending_by, r.approved_by)])
    db.commit()
    return {"rules": [rulebook.rule_out(r, flags.get(r.code), names) for r in rows], "flagged": len(flags),
            "catalog_installed": bridge.catalog_service() is not None, "can_edit": _can(db, actor, Action.MANAGE_MAPPING_RULES),
            "can_approve": _can(db, actor, Action.APPROVE_MAPPING_RULES), "me": actor.id}


@router.put("/rules/{code}")
def edit_rule(code: str, body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.MANAGE_MAPPING_RULES)
    r = rulebook.propose_edit(db, code, body, actor.id, _bank_codes(db))
    audit.record(db, actor_id=actor.id, action="scoping.rule_edit", obj=r, organization_id=actor.organization.id, request=request,
                 summary=f"Mapping rule {code} edit sent for approval")
    db.commit()
    return _rule_view(db, r)


@router.post("/rules")
def add_rule(body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.MANAGE_MAPPING_RULES)
    r = rulebook.add(db, body, actor.id, _bank_codes(db))
    audit.record(db, actor_id=actor.id, action="scoping.rule_add", obj=r, organization_id=actor.organization.id, request=request,
                 summary=f"Mapping rule {r.code} added, waiting for approval")
    db.commit()
    return _rule_view(db, r)


class ActiveIn(BaseModel):
    active: bool


@router.post("/rules/{code}/active")
def set_rule_active(code: str, body: ActiveIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.MANAGE_MAPPING_RULES)
    r = rulebook.set_active(db, code, body.active, actor.id, _bank_codes(db))
    audit.record(db, actor_id=actor.id, action="scoping.rule_active", obj=r, organization_id=actor.organization.id, request=request,
                 summary=f"Mapping rule {code}: {'switch on' if body.active else 'switch off'} sent for approval")
    db.commit()
    return _rule_view(db, r)


@router.post("/rules/{code}/approve")
def approve_rule(code: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.APPROVE_MAPPING_RULES)
    r = rulebook.approve(db, code, actor.id)
    audit.record(db, actor_id=actor.id, action="scoping.rule_approve", obj=r, organization_id=actor.organization.id, request=request,
                 summary=f"Mapping rule {code} approved")
    db.commit()
    return _rule_view(db, r)


@router.post("/rules/{code}/reject")
def reject_rule(code: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.APPROVE_MAPPING_RULES)
    r = rulebook.reject(db, code, actor.id)
    audit.record(db, actor_id=actor.id, action="scoping.rule_reject", obj=r, organization_id=actor.organization.id, request=request,
                 summary=f"Mapping rule {code} change returned")
    db.commit()
    return _rule_view(db, r)
