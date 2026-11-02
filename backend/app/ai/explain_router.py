"""Client Q&A helper endpoints: "Explain this question" on the client's question screens (spec §21 F1)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.explain import explain
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.questionnaire.router import _engagement_target, _system_target

router = APIRouter(tags=["ai"])


@router.post("/systems/{system_id}/questions/{code}/explain")
def explain_system_question(system_id: str, code: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return explain(db, request.app.state, request.app.state.settings, actor.user, _system_target(db, actor, system_id), code)


@router.post("/clients/{client_id}/questions/{code}/explain")
def explain_engagement_question(client_id: str, code: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return explain(db, request.app.state, request.app.state.settings, actor.user, _engagement_target(db, actor, client_id), code)
