from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.signoffs.models import SignOff
from app.signoffs.service import sign, sign_off_out

router = APIRouter(prefix="/signoffs", tags=["sign-offs"])


class SignIn(BaseModel):
    typed_name: str


def _load(db: Session, actor: Actor, so_id: str) -> SignOff:
    so = db.get(SignOff, so_id)
    if so is None or so.deleted_at:
        raise NotFound()
    authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=so.engagement_id)
    return so


@router.get("/{so_id}")
def get_sign_off(so_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return sign_off_out(db, actor, _load(db, actor, so_id))


@router.post("/{so_id}/sign")
def post_sign(so_id: str, body: SignIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    so = _load(db, actor, so_id)
    sign(db, request.app.state.settings, actor, so, body.typed_name, request)
    return sign_off_out(db, actor, so)
