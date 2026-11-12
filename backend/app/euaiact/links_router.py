"""Which delivery workspaces an engagement opens (Release 2 R6b): Copilot readiness on a `copilot_readiness`
engagement, EU AI Act conformity on an `eu_ai_act_readiness` engagement, and how many of the client's systems have EU
geography (the client-level EU AI Act view), plus the workspaces on the client's other engagements the person may open.
The engagement screen shows its links from this."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import AppError, NotFound
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
    return {"copilot": e.type == COPILOT_TYPE, "eu_ai_act": e.type == EU_TYPE, "eu_systems": len(eu.systems_for(db, e.client_id, everything=False)),
            "elsewhere": _elsewhere(db, actor, e)}


def _elsewhere(db: Session, actor: Actor, e) -> list[dict]:
    """The workspaces on the client's other engagements that this person may open. The client page shows only the
    latest engagement, so without these a newer engagement (a hand-off's draft, say) would hide an earlier one's workspace."""
    from app.engagements.models import Engagement

    kinds = {COPILOT_TYPE: "copilot", EU_TYPE: "eu_ai_act"}
    out = []
    for o in db.scalars(select(Engagement).where(Engagement.client_id == e.client_id, Engagement.id != e.id, Engagement.type.in_(list(kinds)),
                                                 Engagement.deleted_at.is_(None)).order_by(Engagement.created_at.desc())):
        try:
            authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=o.id)
        except AppError:  # not on that engagement's team
            continue
        out.append({"engagement_id": o.id, "workspace": kinds[o.type], "name": o.name, "audit_ref": o.audit_ref})
    return out
