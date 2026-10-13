from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.engagements.gates import STAGE_NAMES, advance_stage, gate_status
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(prefix="/engagements", tags=["engagements"])


def gate_out(db: Session, e) -> dict:
    r = gate_status(db, e)
    return {"stage": e.stage, "stage_name": STAGE_NAMES.get(e.stage), "ready": r.ready, "unmet": r.unmet}


@router.get("/{engagement_id}/gate")
def get_gate(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=engagement_id)
    return gate_out(db, e)


@router.post("/{engagement_id}/advance")
def advance(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = authorize(db, actor, Action.ADVANCE_STAGE, engagement_id=engagement_id)
    advance_stage(db, actor.user, e)
    return gate_out(db, e)
