"""Obligation extraction endpoints (spec §21 F5): on the law record (M2) and the reviewers' queue."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import obligations as ob
from app.ai.models import Obligation
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.laws.models import Regulation
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(tags=["obligations"])


class ReasonIn(BaseModel):
    reason: str | None = None


def _can(db: Session, actor: Actor, action: Action) -> bool:
    try:
        authorize(db, actor, action)
        return True
    except (Forbidden, NotFound):
        return False


def _law(db: Session, law_id: str) -> Regulation:
    reg = db.get(Regulation, law_id)
    if reg is None:
        raise NotFound()
    return reg


def _obligation(db: Session, actor: Actor, obligation_id: str) -> Obligation:
    authorize(db, actor, Action.APPROVE_OBLIGATIONS)
    o = db.get(Obligation, obligation_id)
    if o is None or o.deleted_at is not None:
        raise NotFound()
    return o


@router.get("/reg/laws/{law_id}/obligations")
def law_obligations(law_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    reviewer = _can(db, actor, Action.APPROVE_OBLIGATIONS)
    if not reviewer:
        authorize(db, actor, Action.VIEW_REG_MASTER)
    reg = _law(db, law_id)
    rows = list(db.scalars(select(Obligation).where(Obligation.regulation_id == reg.id, Obligation.deleted_at.is_(None)).order_by(Obligation.created_at)))
    return {"law": {"id": reg.id, "short_name": reg.short_name, "citation": reg.citation},
            "approved": [ob.obligation_out(db, o) for o in rows if o.status == "approved"],
            "pending": [ob.obligation_out(db, o) for o in rows if o.status in ("suggested", "unsupported")] if reviewer else [],
            "can_extract": _can(db, actor, Action.EXTRACT_OBLIGATIONS), "can_approve": reviewer}


@router.post("/reg/laws/{law_id}/obligations/extract")
def extract(law_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.EXTRACT_OBLIGATIONS)
    rows, run = ob.extract(db, request.app.state, request.app.state.settings, actor.user, _law(db, law_id))
    return {"obligations": [ob.obligation_out(db, o) for o in rows]} | run


@router.get("/reg/obligations")
def queue(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.APPROVE_OBLIGATIONS)
    rows = db.scalars(select(Obligation).where(Obligation.status.in_(("suggested", "unsupported")), Obligation.deleted_at.is_(None)).order_by(Obligation.created_at))
    return {"rows": [ob.obligation_out(db, o) for o in rows], "can_extract": _can(db, actor, Action.EXTRACT_OBLIGATIONS)}


@router.post("/obligations/{obligation_id}/approve")
def approve(obligation_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return ob.obligation_out(db, ob.approve(db, actor.user, _obligation(db, actor, obligation_id), body))


@router.post("/obligations/{obligation_id}/reject")
def reject(obligation_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return ob.obligation_out(db, ob.reject(db, actor.user, _obligation(db, actor, obligation_id), body.reason))
