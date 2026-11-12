"""G-06 service templates and engagement types (Release 2 B6). Every endpoint calls `authorize`."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.servicetemplates.types import ENGAGEMENT_TYPES, NEW_ENGAGEMENT_TYPES

router = APIRouter(tags=["service-templates"])


@router.get("/engagement-types")
def engagement_types(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_ENGAGEMENT, list_view=True)
    return {"types": [{"value": k, "label": v, "new": k in NEW_ENGAGEMENT_TYPES} for k, v in ENGAGEMENT_TYPES.items()]}
