"""Training by email (spec §21 F12): each person gets a personal link (campaign type "training"). The link opens the
module player without sign-in; it resolves to that person's assignment only."""
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.mail import sending
from app.mail.models import MailRecipient, MailSend
from app.tenancy.models import Organization
from app.training import modules as M
from app.training import service as svc


def assignment_for(db: Session, r: MailRecipient, s: MailSend):
    if s.campaign_type != svc.CAMPAIGN or not s.campaign_id:
        raise NotFound("This link is not valid.")
    return svc.by_email(db, s.organization_id, s.campaign_id, r.email)


def link_form(db: Session, r: MailRecipient | None, s: MailSend) -> dict:
    if r is None:  # training links are personal only
        raise NotFound("This link is not valid.")
    a = assignment_for(db, r, s)
    org = db.get(Organization, a.organization_id)
    return {"kind": "training", "organization": org.name if org else "", "module": M.card(svc.module_of(db, a), org.name if org else ""), "status": a.status}


def submit_link(db: Session, r: MailRecipient, s: MailSend, payload: dict):
    raise NotFound()  # the player uses /public/training/{token}/…


sending.RESPONDED[svc.CAMPAIGN] = svc.responded
sending.LINK_PURPOSES[svc.CAMPAIGN] = {"form": link_form, "submit": submit_link}
