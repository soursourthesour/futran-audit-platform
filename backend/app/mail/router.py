from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden
from app.mail.models import OutboxMessage
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(prefix="/admin/outbox", tags=["admin"])


@router.get("")
def list_outbox(limit: int = 200, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:  # every tenant's messages: Futran only, whatever a client role might be granted
        raise Forbidden()
    authorize(db, actor, Action.VIEW_OUTBOX)
    rows = db.scalars(select(OutboxMessage).order_by(OutboxMessage.created_at.desc()).limit(min(limit, 1000)))
    return [
        {
            "id": m.id,
            "to": m.to,
            "cc": m.cc,
            "subject": m.subject,
            "body_html": m.body_html,
            "template_key": m.template_key,
            "status": m.status,
            "error": m.error,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]
