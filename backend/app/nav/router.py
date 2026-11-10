"""Counts shown on navigation entries (F6). Each badge is computed only for people who may act on it."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(tags=["navigation"])


def _can(db: Session, actor: Actor, action: Action) -> bool:
    try:
        authorize(db, actor, action)
        return True
    except (Forbidden, NotFound):
        return False


@router.get("/nav/badges")
def badges(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    out: dict[str, int] = {}
    if _can(db, actor, Action.APPROVE_OBLIGATIONS):
        from app.ai.models import Obligation

        out["obligations_to_review"] = db.scalar(select(func.count()).select_from(Obligation).where(
            Obligation.status.in_(("suggested", "unsupported")), Obligation.deleted_at.is_(None))) or 0
    return out
