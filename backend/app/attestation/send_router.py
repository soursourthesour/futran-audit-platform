"""Send to all employees from the attestation tracker (spec §27.1). Client Admin and CAICO (SEND_ATTESTATION)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.attestation import mail_links
from app.attestation.router import _campaign, _engagement
from app.auth.deps import Actor, current_actor, get_settings_dep
from app.core.db import get_db
from app.policy.actions import Action

router = APIRouter(tags=["attestation"])


@router.post("/clients/{client_id}/attestation/send-all/preview")
def preview(client_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.SEND_ATTESTATION)
    return mail_links.preview_all(db, _campaign(db, e), body)


@router.post("/clients/{client_id}/attestation/send-all")
def send_all(client_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    e = _engagement(db, actor, client_id, Action.SEND_ATTESTATION)
    s = mail_links.send_all(db, settings, actor.user, _campaign(db, e), body)
    return {"send_id": s.id, "recipients": s.recipient_count, "status": s.status, "steps": s.expansion}
