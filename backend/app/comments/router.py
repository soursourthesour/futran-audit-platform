"""Comment endpoints (spec §21 F18). Every endpoint resolves the object through `authorize` (app.comments.service.resolve)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor, get_settings_dep
from app.comments import service as svc
from app.core.db import get_db
from app.core.errors import Invalid

router = APIRouter(tags=["comments"])


class CommentIn(BaseModel):
    object_type: str
    object_id: str
    body: str | None = None
    visibility: str | None = None
    parent_id: str | None = None
    mention_ids: list[str] = Field(default_factory=list)


class EditIn(BaseModel):
    body: str | None = None
    mention_ids: list[str] | None = None


class WithdrawIn(BaseModel):
    reason: str | None = None


def _out(db: Session, actor: Actor, c) -> dict:
    return svc.comment_out(db, c, actor, svc._names(db, [c]))


@router.get("/comments")
def list_comments(object_type: str, object_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.threads(db, actor, svc.resolve(db, actor, object_type, object_id))


@router.get("/comments/counts")
def comment_counts(object_type: str, ids: str = "", actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if object_type not in svc.OBJECT_TYPES:
        raise Invalid(errors=[{"field": "object_type", "message": "Unknown object type."}])
    return {"counts": svc.counts(db, actor, object_type, ids.split(","))}


@router.get("/comments/mentionable")
def mentionable(object_type: str, object_id: str, visibility: str = "internal", actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = svc.resolve(db, actor, object_type, object_id)
    if not actor.is_futran or visibility not in ("internal", "shared") or (visibility == "shared" and not t.shared_allowed):
        visibility = "shared" if not actor.is_futran else "internal"
    return {"people": [{"id": u.id, "name": u.name, "job_title": u.job_title, "side": "futran" if u.organization_id != t.engagement.client_id else "client"}
                       for u in svc.mentionable(db, t, visibility)]}


@router.post("/comments")
def post_comment(body: CommentIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    t = svc.resolve(db, actor, body.object_type, body.object_id)
    return _out(db, actor, svc.post(db, settings, actor, t, body.body, body.visibility, body.parent_id, body.mention_ids))


@router.patch("/comments/{comment_id}")
def edit_comment(comment_id: str, body: EditIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    return _out(db, actor, svc.edit(db, settings, actor, comment_id, body.body, body.mention_ids))


@router.post("/comments/{comment_id}/withdraw")
def withdraw_comment(comment_id: str, body: WithdrawIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _out(db, actor, svc.withdraw(db, actor, comment_id, body.reason))
