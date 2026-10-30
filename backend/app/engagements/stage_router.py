"""Stage detail behind the stage tracker on the client page. Futran staff only: the client portal has no stage tracker."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.engagements.gates import STAGE_NAMES
from app.engagements.stages import stage_detail
from app.engagements.wizard_router import _load
from app.policy.actions import Action

router = APIRouter(tags=["clients"])


@router.get("/clients/{client_id}/stages/{number}")
def get_stage(client_id: str, number: int, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _, e = _load(db, actor, client_id, Action.VIEW_ENGAGEMENT)
    if not actor.is_futran or number not in STAGE_NAMES:
        raise NotFound()
    return stage_detail(db, e, number)
