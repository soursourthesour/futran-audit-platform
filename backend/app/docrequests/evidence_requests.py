"""Fieldwork evidence requests (spec §9.6, §14 "evidence request created / due in 3 days")."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today as _today
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid
from app.docrequests.models import EvidenceRequest
from app.engagements.models import ClientContact, Engagement
from app.inventory.models import UseCase
from app.notifications.service import notify
from app.tenancy.models import Organization, RoleAssignment, User


def next_ref(db: Session, e: Engagement) -> str:
    refs = db.scalars(select(EvidenceRequest.ref).where(EvidenceRequest.engagement_id == e.id))
    n = max((int(r[3:]) for r in refs if r and r[3:].isdigit()), default=0)
    return f"ER-{n + 1:03d}"


def default_owner(db: Session, e: Engagement, uc: UseCase | None) -> User | None:
    """The use case's Department Lead, else the CAICO."""
    if uc is not None:
        lead = db.scalar(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(RoleAssignment.role == "dept_compliance_lead", RoleAssignment.scope_id == uc.department_id,
                                                                                                RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None), User.status != "disabled").limit(1))
        if lead is not None:
            return lead
    c = db.scalar(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.contact_role == "caico", ClientContact.deleted_at.is_(None)))
    return db.get(User, c.user_id) if c and c.user_id else None


def create(db: Session, settings, actor: User, e: Engagement, data: dict, uc: UseCase | None = None) -> EvidenceRequest:
    desc = " ".join(str(data.get("description") or "").split())
    errs = []
    if not desc:
        errs.append({"field": "description", "message": "Say what you need."})
    try:
        due = date.fromisoformat(str(data.get("due_date") or ""))
        if due < _today():
            errs.append({"field": "due_date", "message": "The due date can't be in the past."})
    except ValueError:
        due = None
        errs.append({"field": "due_date", "message": "Enter a due date."})
    owner = None
    if data.get("owner_user_id"):
        owner = db.get(User, data["owner_user_id"]) if isinstance(data["owner_user_id"], str) else None
        if owner is None or owner.organization_id != e.client_id or owner.deleted_at is not None:
            errs.append({"field": "owner_user_id", "message": "Choose a person from the client."})
    if errs:
        raise Invalid(errors=errs)
    owner = owner or default_owner(db, e, uc)
    req = EvidenceRequest(organization_id=e.client_id, engagement_id=e.id, ref=next_ref(db, e), use_case_id=uc.id if uc else None, description=desc[:4000], requested_by=actor.id,
                          owner_user_id=owner.id if owner else None, due_date=due, status="outstanding", file_ids=[], created_by=actor.id)
    db.add(req)
    db.flush()
    audit.record(db, actor_id=actor.id, action="evidence_request.create", obj=req, after={"ref": req.ref, "description": req.description, "due": due.isoformat()}, summary=f"Requested evidence {req.ref}: {desc[:120]}")
    org = db.get(Organization, e.client_id)
    notify(db, [owner] if owner else [], "evidence_request", f"{org.name}: evidence requested ({req.ref})", f"{desc} Due {due.day} {due:%B %Y}.", "/documents", engagement=e, settings=settings)
    return req


def _client_change(req: EvidenceRequest) -> None:
    if req.status == "waived":
        raise Conflict("Futran has waived this request.")


def answer(db: Session, actor: User, req: EvidenceRequest, text: str | None) -> EvidenceRequest:
    _client_change(req)
    text = str(text or "").strip()
    if not text:
        raise Invalid(errors=[{"field": "answer", "message": "Write your answer."}])
    req.answer = text[:8000]
    if req.status == "outstanding":
        req.status, req.closed_at = "answered", utcnow()
    audit.record(db, actor_id=actor.id, action="evidence_request.answer", obj=req, summary=f"Answered evidence request {req.ref}")
    return req


def add_file(db: Session, actor: User, req: EvidenceRequest, file_id: str) -> EvidenceRequest:
    _client_change(req)
    req.file_ids = [*(req.file_ids or []), file_id]
    req.status, req.closed_at = "received", utcnow()
    audit.record(db, actor_id=actor.id, action="evidence_request.file", obj=req, summary=f"Uploaded a file for evidence request {req.ref}")
    return req


def waive(db: Session, actor: User, req: EvidenceRequest, reason: str | None) -> EvidenceRequest:
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why the request is waived."}])
    req.status, req.waived_reason, req.closed_at = "waived", reason[:2000], utcnow()
    audit.record(db, actor_id=actor.id, action="evidence_request.waive", obj=req, after={"reason": req.waived_reason}, summary=f"Waived evidence request {req.ref}")
    return req


def due_soon(db: Session, settings, today: date) -> int:
    n = 0
    for req in db.scalars(select(EvidenceRequest).where(EvidenceRequest.status == "outstanding", EvidenceRequest.deleted_at.is_(None), EvidenceRequest.due_date == today + timedelta(days=3), EvidenceRequest.due_warned_at.is_(None))):
        owner = db.get(User, req.owner_user_id) if req.owner_user_id else None
        e = db.get(Engagement, req.engagement_id)
        org = db.get(Organization, e.client_id)
        notify(db, [owner] if owner else [], "evidence_request", f"{org.name}: evidence request {req.ref} is due in 3 days", req.description, "/documents", engagement=e, settings=settings)
        req.due_warned_at = utcnow()
        n += 1
    return n


def request_out(db: Session, r: EvidenceRequest, futran: bool) -> dict:
    from app.files.models import FileObject

    owner = db.get(User, r.owner_user_id) if r.owner_user_id else None
    uc = db.get(UseCase, r.use_case_id) if r.use_case_id else None
    out = {"id": r.id, "ref": r.ref, "description": r.description, "status": r.status, "due_date": r.due_date.isoformat(), "answer": r.answer, "use_case": uc.name if uc else None,
           "owner": owner.name if owner else None, "files": [{"id": f.id, "filename": f.filename} for f in (db.get(FileObject, i) for i in r.file_ids or []) if f is not None and f.deleted_at is None],
           "overdue": r.status == "outstanding" and r.due_date < _today()}
    if futran:
        out["waived_reason"] = r.waived_reason
    return out
