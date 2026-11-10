from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.reference.models import DocumentTemplate
from app.reference.templates import edit_template

router = APIRouter(prefix="/admin/templates", tags=["templates"])


class BodyIn(BaseModel):
    body: str


def t_out(t: DocumentTemplate, db: Session | None = None) -> dict:
    """`approved_by` is the person who saved this revision (a Futran Admin's save is the approval); None for the
    platform's standard text."""
    from app.tenancy.models import User

    by = db.get(User, t.created_by) if db is not None and t.created_by else None
    return {"key": t.key, "name": t.name, "type": t.type, "version": t.version, "body": t.body, "package_item": t.package_item, "requires_action": t.requires_action, "format": t.format,
            "updated_at": t.created_at.isoformat(), "approved_at": t.created_at.isoformat(), "approved_by": by.name if by else None}


def _may_read(db: Session, actor: Actor) -> None:
    """Reading templates (and who approved each revision) needs a template permission: configure or approve.
    Client users get 404, as the screen does not exist for them."""
    if not actor.is_futran:
        raise NotFound()
    try:
        authorize(db, actor, Action.CONFIGURE_TEMPLATES)
    except Forbidden:
        authorize(db, actor, Action.APPROVE_TEMPLATES)


@router.get("")
def list_templates(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _may_read(db, actor)
    rows = db.scalars(select(DocumentTemplate).where(DocumentTemplate.active.is_(True)).order_by(DocumentTemplate.package_item.is_(None), DocumentTemplate.package_item, DocumentTemplate.name))
    return [t_out(t, db) for t in rows]


@router.get("/{key}/versions")
def versions(key: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _may_read(db, actor)
    return [t_out(t, db) | {"active": t.active} for t in db.scalars(select(DocumentTemplate).where(DocumentTemplate.key == key).order_by(DocumentTemplate.version.desc()))]


@router.put("/{key}")
def save(key: str, body: BodyIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.CONFIGURE_TEMPLATES)
    return t_out(edit_template(db, actor.user, key, body.body), db)
