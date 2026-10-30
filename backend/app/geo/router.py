"""Address suggestions for staff entering a client's addresses in the new-client wizard."""
import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.geo import service
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(prefix="/geo", tags=["address suggestions"])


def _staff(db: Session, actor: Actor) -> None:
    authorize(db, actor, Action.CREATE_CLIENT_ENGAGEMENT)  # the same people who can set up a client
    if not actor.is_futran:
        raise NotFound()


@router.get("/suggest")
def suggest(request: Request, q: str = "", session: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _staff(db, actor)
    return service.suggest(db, request.app.state.settings, q, (session or "")[:80] or None)


@router.get("/place")
def place(request: Request, id: str, session: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The parts of a Google suggestion, fetched when the user picks it."""
    _staff(db, actor)
    try:
        return service.google_place(db, request.app.state.settings, id[:300], (session or "")[:80] or None)
    except (httpx.HTTPError, ValueError, service.Unavailable):
        raise NotFound("Address details are unavailable. Type the address instead.") from None
