"""Public, no-sign-in endpoints behind the links in group emails (spec §26.5). Each link resolves to exactly one send
(and, for a personal link, one recipient); nothing else is visible through it."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Invalid, NotFound
from app.core.ratelimit import client_ip, limiter
from app.mail import library, links, sending
from app.mail.models import MailRecipient, MailSend, MailTemplate
from app.tenancy.models import Organization

router = APIRouter(prefix="/public/m", tags=["public"])
SIGN_IN_PURPOSES = {"approval", "evidence", "initiation"}


class EmailIn(BaseModel):
    email: str = ""


class CodeIn(EmailIn):
    code: str = ""


class ProofIn(BaseModel):
    proof: str = ""


def _message(db: Session, r: MailRecipient | None, s: MailSend) -> dict:
    t = db.get(MailTemplate, s.template_id) if s.template_id else None
    org = db.get(Organization, s.organization_id)
    values = {"First name": (r.name or "").split()[0] if r and r.name else "there", "Organization": org.name if org else "", "Link": ""}
    values.update({k: str(v) for k, v in (s.context or {}).items() if not k.startswith("_")})
    body = (s.context or {}).get("_body") or (t.body if t else "")
    paras = [library.merge(p.strip(), values) for p in body.split("\n\n") if p.strip() and p.strip() != "[Link]"]
    purpose = t.purpose if t else "general"
    return {"kind": "message", "title": t.name if t else (s.template_name or "Message"), "organization": org.name if org else "", "paragraphs": paras,
            "action": "sign_in" if purpose in SIGN_IN_PURPOSES else "acknowledge", "completed": bool(r and r.status == "completed")}


def _view(db: Session, r: MailRecipient | None, s: MailSend) -> dict:
    p = sending.LINK_PURPOSES.get(s.campaign_type or "")
    return p["form"](db, r, s) if p else _message(db, r, s)


def _submit(db: Session, r: MailRecipient, s: MailSend, payload: dict) -> dict:
    p = sending.LINK_PURPOSES.get(s.campaign_type or "")
    if p is None:
        raise NotFound()
    p["submit"](db, r, s, payload)
    return {"received": True}


# ---- personal links
@router.get("/{token}")
def personal_view(token: str, db: Session = Depends(get_db)):
    r, s = links.open_personal(db, token)
    return {"mode": "personal", **_view(db, r, s)}


@router.post("/{token}/attestation")
def personal_submit(token: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    limiter(request, "mail_link_submit", 30).check(f"{token}:{client_ip(request)}")
    r, s = links.personal(db, token)
    return _submit(db, r, s, payload)


@router.post("/{token}/done")
def personal_done(token: str, db: Session = Depends(get_db)):
    r, _ = links.personal(db, token)
    links.mark_completed(db, r)
    return {"done": True}


# ---- shared (BCC) links: work email and a one-time code first
@router.get("/s/{token}")
def shared_view(token: str, db: Session = Depends(get_db)):
    s = links.shared_send(db, token)
    return {"mode": "shared", **_view(db, None, s)}


@router.post("/s/{token}/code")
def shared_code(token: str, body: EmailIn, request: Request, db: Session = Depends(get_db)):
    limiter(request, "mail_code", 10).check(client_ip(request))
    links.request_code(db, request.app.state.settings, token, body.email)
    return {"sent": True}


@router.post("/s/{token}/verify")
def shared_verify(token: str, body: CodeIn, request: Request, db: Session = Depends(get_db)):
    limiter(request, "mail_verify", 20).check(client_ip(request))
    try:
        proof = links.verify_code(db, token, body.email, body.code)
    except Invalid:
        db.commit()  # keep the count of wrong tries
        raise
    return {"proof": proof}


@router.post("/s/{token}/attestation")
def shared_submit(token: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    limiter(request, "mail_link_submit", 30).check(f"{token}:{client_ip(request)}")
    r = links.recipient_for_proof(db, token, str(payload.pop("proof", "") or ""))
    return _submit(db, r, db.get(MailSend, r.send_id), payload)


@router.post("/s/{token}/done")
def shared_done(token: str, body: ProofIn, db: Session = Depends(get_db)):
    r = links.recipient_for_proof(db, token, body.proof)
    links.mark_completed(db, r)
    return {"done": True}
