"""SM-07: the client's no-login scoping questions behind a personal link (`/q/:token`). The link resolves to exactly one
send: its questions (never an internal-only one), this contact's own answers, save, forward, submit. Rate limited."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.ratelimit import client_ip, limiter
from app.scoping import sending

router = APIRouter(prefix="/public/q", tags=["public"])


def _limit(request: Request, token: str, kind: str, n: int) -> None:
    limiter(request, f"scoping_link_{kind}", n).check(f"{token[:64]}:{client_ip(request)}")


@router.get("/{token}")
def view(token: str, request: Request, db: Session = Depends(get_db, scope="function")):
    _limit(request, token, "view", 60)
    s = sending.resolve(db, token)
    out = sending.view(db, s)
    db.commit()
    return out


class AnswersIn(BaseModel):
    answers: list[dict] = Field(default_factory=list, max_length=200)


@router.put("/{token}/answers")
def save(token: str, body: AnswersIn, request: Request, db: Session = Depends(get_db, scope="function")):
    _limit(request, token, "write", 30)
    s = sending.resolve(db, token)
    n = sending.save(db, s, body.answers)
    db.commit()
    return {"saved": n}


class ForwardIn(BaseModel):
    name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=254)


@router.post("/{token}/forward")
def forward(token: str, body: ForwardIn, request: Request, db: Session = Depends(get_db, scope="function")):
    _limit(request, token, "forward", 5)
    s = sending.resolve(db, token)
    f = sending.forward(db, request.app.state.settings, s, body.name, body.email)
    db.commit()
    return {"sent_to": f.contact_email}


@router.post("/{token}/submit")
def submit(token: str, request: Request, db: Session = Depends(get_db, scope="function")):
    _limit(request, token, "write", 30)
    s = sending.resolve(db, token)
    out = sending.submit(db, request.app.state.settings, s)
    db.commit()
    return out
