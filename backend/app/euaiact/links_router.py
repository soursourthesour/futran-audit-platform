"""Which delivery workspaces an engagement opens (Release 2 R6b): Copilot readiness on a `copilot_readiness`
engagement, EU AI Act conformity on an `eu_ai_act_readiness` engagement, and how many of the client's systems have EU
geography (the client-level EU AI Act view). The engagement screen shows its links from this."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.euaiact import service as eu
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(tags=["delivery workspaces"])

COPILOT_TYPE = "copilot_readiness"
EU_TYPE = eu.ENGAGEMENT_TYPE

try:  # R6a defines the engagement types once (spec B6); until it lands, the strings above are the spec's names
    from app.servicetemplates.types import ENGAGEMENT_TYPES as _TYPES  # type: ignore
except ImportError:  # pragma: no cover - depends on the other workstream
    _TYPES = None


def known_types() -> set[str] | None:
    if _TYPES is None:
        return None
    return set(_TYPES) if not isinstance(_TYPES, dict) else set(_TYPES.keys())


@router.get("/e/{engagement_id}/workspaces")
def workspaces(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:
        raise NotFound()
    e = authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=engagement_id)
    return {"copilot": e.type == COPILOT_TYPE, "eu_ai_act": e.type == EU_TYPE, "eu_systems": len(eu.systems_for(db, e.client_id, everything=False))}
