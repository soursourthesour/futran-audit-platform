from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.reference.models import DocumentTemplate
from app.reference.templates import edit_template

router = APIRouter(prefix="/admin/templates", tags=["templates"])


class BodyIn(BaseModel):
    body: str


def t_out(t: DocumentTemplate) -> dict:
    return {"key": t.key, "name": t.name, "type": t.type, "version": t.version, "body": t.body, "package_item": t.package_item, "requires_action": t.requires_action, "format": t.format, "updated_at": t.created_at.isoformat()}


@router.get("")
def list_templates(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if not actor.is_futran:
        raise NotFound()
    rows = db.scalars(select(DocumentTemplate).where(DocumentTemplate.active.is_(True)).order_by(DocumentTemplate.package_item.is_(None), DocumentTemplate.package_item, DocumentTemplate.name))
    return [t_out(t) for t in rows]


@router.get("/{key}/versions")
def versions(key: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if not actor.is_futran:
        raise NotFound()
    return [t_out(t) | {"active": t.active} for t in db.scalars(select(DocumentTemplate).where(DocumentTemplate.key == key).order_by(DocumentTemplate.version.desc()))]


@router.put("/{key}")
def save(key: str, body: BodyIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.CONFIGURE_TEMPLATES)
    return t_out(edit_template(db, actor.user, key, body.body))
