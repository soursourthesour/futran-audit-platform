from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Invalid, NotFound
from app.notifications.models import Notification

router = APIRouter(tags=["notifications"])


MENTION_KINDS = ("comment_mention",)  # F18: the bell's "Mentions" filter
FILTERS = ("all", "mentions", "unread")


@router.get("/me/notifications")
def mine(filter: str = "all", actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Your own notifications only; no permission beyond being signed in is needed. `filter`: all, mentions or unread (F18)."""
    if filter not in FILTERS:
        raise Invalid(errors=[{"field": "filter", "message": "Choose all, mentions or unread."}])
    mine_ = (Notification.user_id == actor.id, Notification.deleted_at.is_(None))
    stmt = select(Notification).where(*mine_)
    if filter == "mentions":
        stmt = stmt.where(Notification.kind.in_(MENTION_KINDS))
    elif filter == "unread":
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc()).limit(30))
    unread = db.scalar(select(func.count()).select_from(Notification).where(*mine_, Notification.read_at.is_(None))) or 0
    mentions_unread = db.scalar(select(func.count()).select_from(Notification).where(*mine_, Notification.read_at.is_(None), Notification.kind.in_(MENTION_KINDS))) or 0
    return {"unread": unread, "mentions_unread": mentions_unread, "filter": filter,
            "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "at": n.created_at.isoformat(), "read": n.read_at is not None} for n in rows]}


@router.post("/notifications/{notification_id}/read")
def read(notification_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != actor.id:
        raise NotFound()
    n.read_at = n.read_at or utcnow()
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    for n in db.scalars(select(Notification).where(Notification.user_id == actor.id, Notification.read_at.is_(None))):
        n.read_at = utcnow()
    return {"ok": True}
