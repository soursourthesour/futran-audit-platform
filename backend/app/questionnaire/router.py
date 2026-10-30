from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, Invalid, NotFound
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.files.service import upload
from app.findings.models import DraftFindingLink
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.questionnaire import service as qs
from app.questionnaire.models import Response
from app.systems.models import AISystem
from app.systems.service import get_system, systems_for
from app.tenancy.models import Organization, User
from app.tenancy.people import current_engagement

router = APIRouter(tags=["assessment"])


class ChecklistIn(BaseModel):
    confirmed: bool
    evidence_ids: list[str] = []
    auditor_note: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


def _system_target(db: Session, actor: Actor, system_id: str, write: bool = False) -> qs.Target:
    s = get_system(db, system_id)
    if actor.is_futran:
        authorize(db, actor, Action.VERIFY_SYSTEM_ANSWERS if write else Action.VIEW_ENGAGEMENT, engagement_id=s.engagement_id)
    else:
        authorize(db, actor, Action.PREFILL_SYSTEM, engagement_id=s.engagement_id, department_id=s.department_id, system_id=s.id)
    return qs.Target(db.get(Engagement, s.engagement_id), s)


def _engagement_target(db: Session, actor: Actor, client_id: str, write: bool = False) -> qs.Target:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    if actor.is_futran:
        authorize(db, actor, Action.VERIFY_SYSTEM_ANSWERS if write else Action.VIEW_ENGAGEMENT, engagement_id=e.id)
    else:
        authorize(db, actor, Action.PREFILL_SYSTEM, engagement_id=e.id)
    return qs.Target(e)


def _files(db: Session, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    return [{"id": f.id, "filename": f.filename} for f in db.scalars(select(FileObject).where(FileObject.id.in_(ids), FileObject.deleted_at.is_(None)))]


def _name(db: Session, user_id: str | None) -> str | None:
    u = db.get(User, user_id) if user_id else None
    return u.name if u else None


def client_response(db: Session, r: Response | None) -> dict:
    if r is None:
        return {"value": None, "status": "unanswered", "na_reason": None, "detail": None, "evidence": []}
    return {"value": r.client_value, "status": r.client_status or "unanswered", "na_reason": r.client_na_reason, "detail": r.client_detail, "evidence": _files(db, r.client_evidence_ids or [])}


def futran_response(db: Session, r: Response | None) -> dict | None:
    if r is None:
        return None
    return {
        "id": r.id, "value": r.value, "status": r.status, "na_reason": r.na_reason, "detail": r.detail, "source_person_name": r.source_person_name, "source_person_title": r.source_person_title,
        "evidence": _files(db, r.evidence_ids or []), "answered_by": _name(db, r.answered_by), "answered_side": r.answered_side, "answered_at": r.answered_at.isoformat() if r.answered_at else None,
        "verified": r.verified_at is not None, "verified_by": _name(db, r.verified_by), "verified_at": r.verified_at.isoformat() if r.verified_at else None,
        "client_value": r.client_value, "client_status": r.client_status, "client_detail": r.client_detail, "client_na_reason": r.client_na_reason,
    }


def assessment_out(db: Session, actor: Actor, t: qs.Target) -> dict:
    futran = actor.is_futran
    questions = qs.questions_for(db, t, futran)
    rs = qs._responses(db, t)
    comp = qs.completion(db, t, futran)
    notes = {q.sub_section: q.section_note for q in questions}
    sections = [sec | ({"note": notes.get(sec["code"])} if futran else {}) for sec in comp["sections"]]
    s = t.system
    out = {
        "target": {"engagement_id": t.engagement.id, "client_id": t.engagement.client_id, "audit_ref": t.engagement.audit_ref, "client": db.get(Organization, t.engagement.client_id).name,
                   "system": {"id": s.id, "reference_id": s.reference_id, "name": s.name, "built_by": s.built_by, "assessment_depth": s.assessment_depth, "status": s.status, "vendor_id": s.vendor_id} if s else None},
        "sections": sections,
        "questions": [
            {"id": q.id, "code": q.code, "section": q.section, "sub_section": q.sub_section, "section_title": q.section_title, "label": q.label, "help_text": q.help_text, "type": q.type,
             "options": q.options, "detail_label": q.detail_label, "required": q.required, "respondent": q.default_respondent, "evidence_required": q.evidence_required,
             "response": futran_response(db, rs.get(q.id)) if futran else client_response(db, rs.get(q.id))}
            for q in questions
        ],
        "completion": {"answered": comp["answered"], "applicable": comp["applicable"], "pct": comp["pct"]},
        "locked": bool(s and s.status == "locked") or (not futran and t.engagement.client_answers_locked_at is not None),
    }
    if futran:
        results = qs.checklist_results(db, t)
        out["checklists"] = [
            {"code": i.code, "section": i.section, "section_title": i.section_title, "text": i.text, "maturity_domain": i.maturity_domain, "pending_review": i.pending_review,
             "confirmed": bool(results.get(i.id) and results[i.id].confirmed), "evidence": _files(db, results[i.id].evidence_ids or []) if i.id in results else [],
             "auditor_note": results[i.id].auditor_note if i.id in results else None}
            for i in qs.checklist_for(db, t)
        ]
        out["draft_findings"] = qs.draft_findings(db, t)
        out["evidence_files"] = [{"id": f.id, "filename": f.filename} for f in db.scalars(select(FileObject).where(FileObject.engagement_id == t.engagement.id, FileObject.linked_type == "evidence", FileObject.deleted_at.is_(None), FileObject.linked_id == (s.id if s else t.engagement.id)).order_by(FileObject.created_at))]
    return out


# ---- per system
@router.get("/systems/{system_id}/assessment")
def get_assessment(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return assessment_out(db, actor, _system_target(db, actor, system_id))


@router.put("/systems/{system_id}/responses/{code}")
def put_response(system_id: str, code: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = _system_target(db, actor, system_id, write=True)
    r = qs.save_response(db, actor.user, t, code, body, actor.is_futran)
    return {"id": r.id, "response": futran_response(db, r) if actor.is_futran else client_response(db, r), "completion": {k: v for k, v in qs.completion(db, t, actor.is_futran).items() if k != "sections"}}


@router.put("/systems/{system_id}/checklist/{code}")
def put_checklist(system_id: str, code: str, body: ChecklistIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = _system_target(db, actor, system_id, write=True)
    if not actor.is_futran:
        raise Forbidden("Only the auditor can do this.")
    res = qs.tick_checklist(db, actor.user, t, code, body.confirmed, body.evidence_ids, body.auditor_note)
    return {"code": code, "confirmed": res.confirmed, "evidence": _files(db, res.evidence_ids or [])}


@router.post("/systems/{system_id}/sections/{sub_section}/verify")
def verify_section(system_id: str, sub_section: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = _system_target(db, actor, system_id, write=True)
    if not actor.is_futran:
        raise Forbidden("Only the auditor can do this.")
    return {"verified": qs.verify_section(db, actor.user, t, sub_section)}


@router.post("/systems/{system_id}/prefill/submit")
def submit_prefill(system_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = _system_target(db, actor, system_id, write=True)
    if actor.is_futran:
        raise Forbidden("The client submits its own pre-fill.")
    qs.submit_prefill(db, request.app.state.settings, actor.user, t)
    return {"status": t.system.status}


def _evidence_upload(db: Session, request: Request, actor: Actor, t: qs.Target, file: UploadFile) -> dict:
    if actor.is_futran:
        authorize(db, actor, Action.UPLOAD_EVIDENCE if not actor.has_role("chief_auditor") else Action.VERIFY_SYSTEM_ANSWERS, engagement_id=t.engagement.id)
    qs._check_locks(db, t, actor.is_futran)
    settings = request.app.state.settings
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not data:
        raise Invalid(errors=[{"field": "file", "message": "The file is empty."}])
    f = upload(db, settings, actor.user, data=data, filename=file.filename or "evidence", content_type=file.content_type, organization_id=t.engagement.client_id,
               engagement_id=t.engagement.id, linked_type="evidence", linked_id=t.system.id if t.system else t.engagement.id)
    from app.audit_log import service as audit

    audit.record(db, actor_id=actor.id, action="evidence.upload", obj=f, summary=f"Uploaded evidence {f.filename} for {t.label}")
    return {"id": f.id, "filename": f.filename}


@router.post("/systems/{system_id}/evidence")
def post_system_evidence(system_id: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _evidence_upload(db, request, actor, _system_target(db, actor, system_id, write=True), file)


# ---- engagement level (§4, checklist 4.3)
@router.get("/clients/{client_id}/assessment")
def get_engagement_assessment(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return assessment_out(db, actor, _engagement_target(db, actor, client_id))


@router.put("/clients/{client_id}/responses/{code}")
def put_engagement_response(client_id: str, code: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = _engagement_target(db, actor, client_id, write=True)
    r = qs.save_response(db, actor.user, t, code, body, actor.is_futran)
    return {"id": r.id, "response": futran_response(db, r) if actor.is_futran else client_response(db, r)}


@router.put("/clients/{client_id}/checklist/{code}")
def put_engagement_checklist(client_id: str, code: str, body: ChecklistIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = _engagement_target(db, actor, client_id, write=True)
    if not actor.is_futran:
        raise Forbidden("Only the auditor can do this.")
    res = qs.tick_checklist(db, actor.user, t, code, body.confirmed, body.evidence_ids, body.auditor_note)
    return {"code": code, "confirmed": res.confirmed, "evidence": _files(db, res.evidence_ids or [])}


@router.post("/clients/{client_id}/sections/{sub_section}/verify")
def verify_engagement_section(client_id: str, sub_section: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = _engagement_target(db, actor, client_id, write=True)
    if not actor.is_futran:
        raise Forbidden("Only the auditor can do this.")
    return {"verified": qs.verify_section(db, actor.user, t, sub_section)}


@router.post("/clients/{client_id}/evidence")
def post_engagement_evidence(client_id: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _evidence_upload(db, request, actor, _engagement_target(db, actor, client_id, write=True), file)


# ---- shared
@router.post("/responses/{response_id}/verify")
def verify_response(response_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    r = db.get(Response, response_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.VERIFY_SYSTEM_ANSWERS, engagement_id=r.engagement_id)
    return futran_response(db, qs.verify(db, actor.user, r))


def _link(db: Session, actor: Actor, link_id: str) -> DraftFindingLink:
    link = db.get(DraftFindingLink, link_id)
    if link is None or link.deleted_at is not None:
        raise NotFound()
    r = db.get(Response, link.response_id)
    authorize(db, actor, Action.RECORD_FINDINGS, engagement_id=r.engagement_id)
    return link


@router.post("/draft-findings/{link_id}/dismiss")
def dismiss(link_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    link = _link(db, actor, link_id)
    qs.dismiss_draft(db, actor.user, link, body.reason)
    from app.engagements.gates import advance_if_ready
    from app.engagements.models import Engagement
    from app.findings.models import Finding

    db.flush()
    advance_if_ready(db, actor.user, db.get(Engagement, db.get(Finding, link.finding_id).engagement_id))
    return {"dismissed": True}


@router.post("/draft-findings/{link_id}/confirm")
def confirm(link_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    f = qs.confirm_draft(db, actor.user, _link(db, actor, link_id))
    return {"ref": f.ref, "confirmed": True}


@router.get("/me/systems")
def my_systems(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The client's systems this person can pre-fill, with their own progress."""
    if actor.is_futran:
        raise NotFound()
    e = current_engagement(db, actor.organization)
    if e is None:
        return {"systems": [], "engagement": None}
    authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=e.id)
    depts = departments_for(actor, Action.PREFILL_SYSTEM)
    own = {r.scope_id for r in actor.roles if r.scope_type == "system"}
    out = []
    for s in systems_for(db, e):
        if depts is not None and s.department_id not in depts and s.id not in own:
            continue
        c = qs.completion(db, qs.Target(e, s), futran=False)
        out.append({"id": s.id, "reference_id": s.reference_id, "name": s.name, "status": s.status, "answered": c["answered"], "applicable": c["applicable"], "pct": c["pct"]})
    can_engagement = depts is None
    return {"systems": out, "engagement": {"id": e.id, "audit_ref": e.audit_ref, "locked": e.client_answers_locked_at is not None, "can_answer_governance_questions": can_engagement}}
