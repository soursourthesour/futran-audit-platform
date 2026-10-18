from datetime import date

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Invalid, NotFound
from app.docrequests import service as svc
from app.docrequests.models import DocumentRequest
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.files.service import upload
from app.findings.models import Finding
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.reference.models import DocumentCatalogItem
from app.systems.models import AISystem
from app.tenancy.models import Organization
from app.tenancy.people import current_engagement

router = APIRouter(tags=["documents"])


class NoteIn(BaseModel):
    note: str | None = None


def _engagement(db: Session, actor: Actor, client_id: str, action: Action) -> Engagement:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=e.id)
    return e


def _request(db: Session, actor: Actor, req_id: str, client_action: Action = Action.UPLOAD_REQUESTED_DOCUMENT) -> DocumentRequest:
    req = db.get(DocumentRequest, req_id)
    if req is None or req.deleted_at is not None:
        raise NotFound()
    if actor.is_futran:
        authorize(db, actor, Action.MANAGE_DOCUMENT_REQUESTS, engagement_id=req.engagement_id)
    else:
        s = db.get(AISystem, req.ai_system_id) if req.ai_system_id else None
        if s is None:
            authorize(db, actor, client_action, engagement_id=req.engagement_id, org_id=req.organization_id)
            if departments_for(actor, client_action) is not None:  # organization-wide documents are for organization-level roles
                raise NotFound()
        else:
            authorize(db, actor, client_action, engagement_id=req.engagement_id, department_id=s.department_id, system_id=s.id)
    return req


def _files(db: Session, ids: list[str]) -> list[dict]:
    return [{"id": f.id, "filename": f.filename} for f in (db.get(FileObject, i) for i in ids or []) if f is not None and f.deleted_at is None]


def request_out(db: Session, r: DocumentRequest, futran: bool) -> dict:
    item = db.get(DocumentCatalogItem, r.catalog_item_id)
    s = db.get(AISystem, r.ai_system_id) if r.ai_system_id else None
    out = {
        "id": r.id, "code": item.code, "title": item.title, "description": item.description, "category": item.category, "category_title": item.category_title,
        "system_id": s.id if s else None, "system": s.name if s else None, "system_ref": s.reference_id if s else None,
        "status": r.status, "due_at": r.due_at.isoformat() if r.due_at else None, "received_at": r.received_at.isoformat() if r.received_at else None,
        "files": _files(db, r.evidence_ids), "not_available_note": r.not_available_note,
    }
    if futran:
        c = svc.last_chase(db, r)
        f = db.get(Finding, r.finding_id) if r.finding_id else None
        from app.docrequests.models import DocumentChase
        from sqlalchemy import func, select

        out |= {
            "chases": db.scalar(select(func.count()).select_from(DocumentChase).where(DocumentChase.document_request_id == r.id, DocumentChase.deleted_at.is_(None))) or 0,
            "last_chased_at": c.chased_at.isoformat() if c else None,
            "escalate": r.status == "pending" and c is not None and svc.business_days_between(c.chased_at.date(), date.today()) >= svc.ESCALATE_AFTER,
            "finding": {"id": f.id, "ref": f.ref} if f is not None and f.deleted_at is None else None,
        }
    return out


@router.get("/clients/{client_id}/document-requests")
def register(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if not actor.is_futran:
        raise NotFound()
    e = _engagement(db, actor, client_id, Action.VIEW_ENGAGEMENT)
    rows = svc.requests_for(db, e)
    org = db.get(Organization, client_id)
    return {
        "client": {"id": org.id, "name": org.name}, "audit_ref": e.audit_ref, "fieldwork_start": e.fieldwork_start.isoformat() if e.fieldwork_start else None,
        "due": svc.subtract_business_days(e.fieldwork_start, svc.DUE_BUSINESS_DAYS).isoformat() if e.fieldwork_start else None,
        "requested_at": min((r.requested_at for r in rows), default=None) and min(r.requested_at for r in rows).isoformat(),
        "kpis": svc.kpis(db, rows), "not_yet_requested": len(svc._missing(db, e)),
        "requests": [request_out(db, r, True) for r in rows],
        "systems": [{"id": s.id, "reference_id": s.reference_id, "name": s.name} for s in svc.systems_for(db, e)],
    }


@router.get("/clients/{client_id}/document-requests/preview")
def preview(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.MANAGE_DOCUMENT_REQUESTS)
    return svc.preview(db, actor.user, e)


@router.post("/clients/{client_id}/document-requests/issue")
def issue(client_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.MANAGE_DOCUMENT_REQUESTS)
    rows = svc.issue_register(db, request.app.state.settings, actor.user, e)
    return {"kpis": svc.kpis(db, rows), "count": len(rows)}


@router.post("/clients/{client_id}/document-requests/chase")
def chase_all(client_id: str, body: NoteIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.MANAGE_DOCUMENT_REQUESTS)
    return {"chased": svc.chase_all(db, request.app.state.settings, actor.user, e, body.note)}


@router.post("/document-requests/{req_id}/chase")
def chase(req_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    req = _request(db, actor, req_id)
    if not actor.is_futran:
        raise NotFound()
    svc.chase(db, actor.user, req, body.note)
    return request_out(db, req, True)


@router.post("/document-requests/{req_id}/files")
def post_file(req_id: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    req = _request(db, actor, req_id)
    settings = request.app.state.settings
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not data:
        raise Invalid(errors=[{"field": "file", "message": "The file is empty."}])
    f = upload(db, settings, actor.user, data=data, filename=file.filename or "document", content_type=file.content_type, organization_id=req.organization_id,
               engagement_id=req.engagement_id, linked_type="evidence", linked_id=req.ai_system_id or req.engagement_id)
    return request_out(db, svc.receive(db, actor.user, req, [f.id]), actor.is_futran)


@router.post("/document-requests/{req_id}/not-available")
def not_available(req_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    req = _request(db, actor, req_id)
    return request_out(db, svc.mark_not_available(db, actor.user, req, body.note), actor.is_futran)


@router.get("/me/document-requests")
def mine(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """The client's own requests: organization-wide ones for organization-level roles, and those for systems in the person's departments."""
    if actor.is_futran:
        raise NotFound()
    e = current_engagement(db, actor.organization)
    if e is None:
        return {"requests": [], "due": None}
    authorize(db, actor, Action.UPLOAD_REQUESTED_DOCUMENT, engagement_id=e.id, list_view=True)
    depts = departments_for(actor, Action.UPLOAD_REQUESTED_DOCUMENT)
    own = {r.scope_id for r in actor.roles if r.scope_type == "system"}
    out = []
    for r in svc.requests_for(db, e):
        if depts is not None:
            s = db.get(AISystem, r.ai_system_id) if r.ai_system_id else None
            if s is None or (s.department_id not in depts and s.id not in own):
                continue
        out.append(request_out(db, r, False))
    return {"requests": out, "due": out[0]["due_at"] if out else None}


# ---- fieldwork evidence requests
from app.docrequests import evidence_requests as er  # noqa: E402
from app.docrequests.models import EvidenceRequest  # noqa: E402
from app.inventory.models import UseCase  # noqa: E402


class AnswerIn(BaseModel):
    answer: str | None = None


class WaiveIn(BaseModel):
    reason: str | None = None


@router.post("/use-cases/{uc_id}/evidence-requests")
def create_evidence_request(uc_id: str, data: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    uc = db.get(UseCase, uc_id)
    if uc is None or uc.deleted_at is not None or not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.MANAGE_DOCUMENT_REQUESTS, engagement_id=uc.engagement_id)
    return er.request_out(db, er.create(db, request.app.state.settings, actor.user, db.get(Engagement, uc.engagement_id), data, uc), True)


def _er(db: Session, actor: Actor, req_id: str) -> EvidenceRequest:
    r = db.get(EvidenceRequest, req_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    if actor.is_futran:
        authorize(db, actor, Action.MANAGE_DOCUMENT_REQUESTS, engagement_id=r.engagement_id)
    else:
        authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=r.engagement_id)
        if r.owner_user_id != actor.id and not actor.has_role("caico"):
            raise NotFound()
    return r


@router.post("/evidence-requests/{req_id}/answer")
def answer_evidence_request(req_id: str, body: AnswerIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    r = _er(db, actor, req_id)
    return er.request_out(db, er.answer(db, actor.user, r, body.answer), actor.is_futran)


@router.post("/evidence-requests/{req_id}/files")
def evidence_request_file(req_id: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    r = _er(db, actor, req_id)
    settings = request.app.state.settings
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not data:
        raise Invalid(errors=[{"field": "file", "message": "The file is empty."}])
    f = upload(db, settings, actor.user, data=data, filename=file.filename or "evidence", content_type=file.content_type, organization_id=r.organization_id,
               engagement_id=r.engagement_id, linked_type="evidence", linked_id=r.engagement_id)
    return er.request_out(db, er.add_file(db, actor.user, r, f.id), actor.is_futran)


@router.post("/evidence-requests/{req_id}/waive")
def waive_evidence_request(req_id: str, body: WaiveIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if not actor.is_futran:
        raise NotFound()
    r = _er(db, actor, req_id)
    return er.request_out(db, er.waive(db, actor.user, r, body.reason), True)


@router.get("/me/evidence-requests")
def my_evidence_requests(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.is_futran:
        raise NotFound()
    from sqlalchemy import select

    e = current_engagement(db, actor.organization)
    if e is None:
        return {"requests": []}
    authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=e.id)
    q = select(EvidenceRequest).where(EvidenceRequest.engagement_id == e.id, EvidenceRequest.deleted_at.is_(None)).order_by(EvidenceRequest.ref)
    rows = [r for r in db.scalars(q) if actor.has_role("caico") or r.owner_user_id == actor.id]
    return {"requests": [er.request_out(db, r, False) for r in rows]}
