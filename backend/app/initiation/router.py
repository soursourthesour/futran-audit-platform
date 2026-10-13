from html import escape

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.documents.render import render_markdown
from app.engagements.models import ClientContact, ClientLocation, ClientRequirement, Engagement
from app.engagements.wizard_router import _load
from app.initiation.context import TYPE_LABELS, build_context
from app.initiation.models import InitiationPackage, PackageDocument
from app.initiation.service import ACTION_LABELS, EDITABLE_ITEMS, approve_and_send, documents, edit_document, ensure_package
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.policy.roles import ROLE_LABELS
from app.tenancy.models import User

router = APIRouter(tags=["initiation"])


class ApproveIn(BaseModel):
    client_message: str | None = None
    checklist: dict[str, bool] = {}


class EditIn(BaseModel):
    body_md: str


def doc_out(d: PackageDocument) -> dict:
    return {
        "id": d.id, "item": d.item, "title": d.title, "requires_action": d.requires_action, "action_label": ACTION_LABELS.get(d.requires_action, ""),
        "format": d.format, "docx_file_id": d.docx_file_id, "pdf_file_id": d.pdf_file_id, "csv_file_id": d.csv_file_id,
        "editable": d.item in EDITABLE_ITEMS and d.format == "md", "edited": d.edited, "template_version": d.template_version,
        "completed_at": d.completed_at.isoformat() if d.completed_at else None,
    }


def package_out(db: Session, request: Request, e: Engagement, pkg: InitiationPackage) -> dict:
    ctx = build_context(db, request.app.state.settings, e)
    people: dict[str, dict] = {}
    for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.contact_role.in_(["caico", "client_admin"]), ClientContact.deleted_at.is_(None)).order_by(ClientContact.contact_role)):
        if not c.email:
            continue
        p = people.setdefault(c.email.lower(), {"name": c.name, "roles": [], "email": c.email})
        p["roles"].append(ROLE_LABELS.get(c.contact_role, c.contact_role))
    sites = [loc.site_name for loc in db.scalars(select(ClientLocation).where(ClientLocation.organization_id == e.client_id, ClientLocation.deleted_at.is_(None), ClientLocation.in_scope.is_(True)))]
    prepared = db.get(User, pkg.prepared_by) if pkg.prepared_by else None
    return {
        "id": pkg.id, "status": pkg.status, "version": pkg.version, "client_message": pkg.client_message,
        "prepared_by": prepared.name if prepared else None,
        "documents": [doc_out(d) for d in documents(db, pkg)],
        "sends_to": sorted(people.values(), key=lambda p: "Chief AI Compliance Officer" not in p["roles"]),
        "summary": {
            "type_label": TYPE_LABELS.get(e.type, e.type), "sites": sites, "laws": [law["short_name"] for law in ctx["laws"]],
            "departments": ctx["engagement"]["departments"], "team": [f"{m['name']} ({m['role_label']})" for m in ctx["team"]],
            "requirements": db.query(ClientRequirement).filter_by(engagement_id=e.id, deleted_at=None).count(),
        },
    }


@router.get("/clients/{client_id}/package")
def get_package(client_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    _, e = _load(db, actor, client_id, Action.VIEW_ENGAGEMENT)
    if not actor.is_futran:
        raise NotFound()
    pkg = ensure_package(db, request.app.state.settings, actor.user, e)
    if pkg is None:
        raise NotFound("The package is generated when the engagement is submitted for approval.")
    return package_out(db, request, e, pkg)


def _doc(db: Session, actor: Actor, doc_id: str, action: Action) -> PackageDocument:
    d = db.get(PackageDocument, doc_id)
    if d is None or d.deleted_at:
        raise NotFound()
    authorize(db, actor, action, engagement_id=d.engagement_id)
    return d


@router.get("/packages/documents/{doc_id}/preview")
def preview(doc_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    d = _doc(db, actor, doc_id, Action.VIEW_ENGAGEMENT)
    html = f"<pre>{escape(d.body_md)}</pre>" if d.format == "csv" else render_markdown(d.body_md)
    return {"id": d.id, "title": d.title, "html": html, "body_md": d.body_md if actor.is_futran else None}


@router.put("/packages/documents/{doc_id}")
def put_document(doc_id: str, body: EditIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    d = _doc(db, actor, doc_id, Action.APPROVE_ENGAGEMENT)
    return doc_out(edit_document(db, request.app.state.settings, actor.user, d, body.body_md))


@router.post("/clients/{client_id}/approve")
def approve(client_id: str, body: ApproveIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    _, e = _load(db, actor, client_id, Action.APPROVE_ENGAGEMENT)
    pkg = approve_and_send(db, request.app.state.settings, actor.user, e, (body.client_message or "").strip() or None, body.checklist)
    return {"engagement_id": e.id, "status": e.status, "stage": e.stage, "package_id": pkg.id}
