from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import NotFound
from app.notifications.models import Notification

router = APIRouter(tags=["notifications"])


@router.get("/me/notifications")
def mine(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Your own notifications only; no permission beyond being signed in is needed."""
    rows = db.scalars(select(Notification).where(Notification.user_id == actor.id, Notification.deleted_at.is_(None)).order_by(Notification.created_at.desc()).limit(30))
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == actor.id, Notification.read_at.is_(None), Notification.deleted_at.is_(None))) or 0
    return {"unread": unread, "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "at": n.created_at.isoformat(), "read": n.read_at is not None} for n in rows]}


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
