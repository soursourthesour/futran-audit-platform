from datetime import date

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Invalid, NotFound
from app.files.models import FileObject
from app.governance import service as gov
from app.governance.models import Commitment, GovernanceItem, GovernanceRequest
from app.initiation.context import eu_operations
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization, User
from app.tenancy.people import current_engagement

router = APIRouter(tags=["governance"])


class SetupIn(BaseModel):
    codes: list[str]
    due_date: date | None = None


class SubmitIn(BaseModel):
    accuracy_confirmed: bool = False


class ExtraIn(BaseModel):
    fields: dict


def _request(db: Session, actor: Actor, client_id: str, action: Action) -> GovernanceRequest:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=e.id)
    req = gov.current_request(db, e)
    if req is None:
        raise NotFound("The governance request has not been sent yet.")
    return req


def item_out(db: Session, it: GovernanceItem) -> dict:
    files = [{"id": f.id, "filename": f.filename} for f in db.scalars(select(FileObject).where(FileObject.id.in_(it.file_ids or []), FileObject.deleted_at.is_(None)))]
    return {
        "id": it.id, "code": it.catalog_code, "kind": it.kind, "title": it.title, "description": it.description, "control_refs": it.control_refs,
        "committee": it.committee, "optional": it.optional, "status": it.status, "files": files, "names": it.names or [], "chair": it.chair,
        "member_count": it.member_count, "meeting_frequency": it.meeting_frequency, "target_date": it.target_date.isoformat() if it.target_date else None,
        "interim_owner": it.interim_owner, "planned_members": it.planned_members, "na_reason": it.na_reason,
    }


def request_out(db: Session, req: GovernanceRequest) -> dict:
    its = gov.items(db, req)
    org = db.get(Organization, req.organization_id)
    eu = eu_operations(db, org)
    who = db.get(User, req.requested_by) if req.requested_by else None
    roles = [i for i in its if i.kind == "role"]
    docs = [i for i in its if i.kind != "role"]
    commitments = db.scalars(select(Commitment).where(Commitment.engagement_id == req.engagement_id, Commitment.deleted_at.is_(None)).order_by(Commitment.target_date))
    return {
        "request": {"id": req.id, "status": req.status, "due_date": req.due_date.isoformat() if req.due_date else None, "requested_by": who.name if who else None, "submitted_at": req.submitted_at.isoformat() if req.submitted_at else None, "extra_fields": req.extra_fields or {}},
        "items": [item_out(db, i) for i in its],
        "counts": {"roles": {"answered": sum(i.status != "unanswered" for i in roles), "total": len(roles)}, "documents": {"answered": sum(i.status != "unanswered" for i in docs), "total": len(docs)}},
        "coverage": gov.coverage(its),
        "commitments": [{"id": c.id, "description": c.description, "target_date": c.target_date.isoformat(), "owner": c.owner, "status": c.status} for c in commitments],
        "catalog": [{"code": c.code, "kind": c.kind, "title": c.title, "optional": c.optional, "selected": c.code in (req.items_selected or []), "available": c.conditional != "eu_operations" or eu} for c in gov.catalog(db)],
        "extra_field_defs": gov.EXTRA_FIELDS,
    }


@router.get("/clients/{client_id}/governance")
def get_governance(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return request_out(db, _request(db, actor, client_id, Action.VIEW_GOVERNANCE))


@router.put("/clients/{client_id}/governance/setup")
def put_setup(client_id: str, body: SetupIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    req = _request(db, actor, client_id, Action.APPROVE_ENGAGEMENT)  # the Chief Auditor chooses the items
    gov.update_setup(db, actor.user, req, body.codes, body.due_date)
    return request_out(db, req)


def _item(db: Session, actor: Actor, item_id: str, action: Action) -> GovernanceItem:
    it = db.get(GovernanceItem, item_id)
    if it is None or it.deleted_at:
        raise NotFound()
    authorize(db, actor, action, engagement_id=it.engagement_id)
    return it


@router.put("/governance/items/{item_id}")
def put_item(item_id: str, payload: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    it = gov.answer_item(db, actor.user, _item(db, actor, item_id, Action.ANSWER_GOVERNANCE), payload)
    return item_out(db, it)


@router.post("/governance/items/{item_id}/files")
def post_file(item_id: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    it = _item(db, actor, item_id, Action.ANSWER_GOVERNANCE)
    settings = request.app.state.settings
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not data:
        raise Invalid(errors=[{"field": "file", "message": "The file is empty."}])
    return item_out(db, gov.attach_file(db, settings, actor.user, it, data, file.filename or "document", file.content_type))


@router.put("/clients/{client_id}/governance/extra")
def put_extra(client_id: str, body: ExtraIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    req = _request(db, actor, client_id, Action.ANSWER_GOVERNANCE)
    return {"extra_fields": gov.save_extra(db, actor.user, req, body.fields)}


@router.post("/clients/{client_id}/governance/submit")
def post_submit(client_id: str, body: SubmitIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    req = _request(db, actor, client_id, Action.ANSWER_GOVERNANCE)
    gov.submit(db, request.app.state.settings, actor.user, req, body.accuracy_confirmed)
    return {"status": req.status}
