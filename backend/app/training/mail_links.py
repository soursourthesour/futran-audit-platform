"""Training by email (spec §21 F12): each person gets a personal link (campaign type "training"). The link opens the
module player without sign-in; it resolves to that person's assignment only."""
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.mail import library, sending
from app.mail.models import MailRecipient, MailSend
from app.tenancy.models import Organization
from app.training import modules as M
from app.training import service as svc


TEMPLATE = {
    "key": svc.TEMPLATE_KEY, "name": "Training: assigned AI literacy module", "purpose": "training", "default_mode": "personal",
    "subject": "AI training to complete by [Due date]: [Module]", "button_label": "Start the module",
    "body": "Hi [First name],\n\n[Organization] has assigned you a short AI literacy module from Futran: [Module]. It works on a phone or a computer "
            "and ends with a short quiz. You don't need to sign in.\n\n[Link]\n\nThis link is just for you. Please finish by [Due date]. Questions? Reply to this email.\n\n[Sender name]",
}
if TEMPLATE["key"] not in library.DEFAULT_KEYS:
    library.DEFAULTS.append(TEMPLATE)
    library.DEFAULT_KEYS.add(TEMPLATE["key"])


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
