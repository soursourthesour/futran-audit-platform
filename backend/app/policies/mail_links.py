"""Staff acknowledgment of a published policy by email (spec §21 F7 "reuses attestation"): personal links from the email
service, campaign type "policy_ack". The person reads the policy on their phone and confirms; nothing else is visible."""
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Invalid, NotFound
from app.mail import library, links, sending
from app.mail.models import DirectoryPerson, MailRecipient, MailSend
from app.policies import service as svc
from app.policies.models import PolicyDocument
from app.tenancy.models import Organization

TEMPLATE = {
    "key": "policy_acknowledgment", "name": "Policy: read and acknowledge", "purpose": "notice", "default_mode": "personal",
    "subject": "Please read and acknowledge the [Policy]", "button_label": "Read the policy",
    "body": "Hi [First name],\n\n[Organization] has approved the [Policy]. It applies to your work, so please read it and confirm that you have done so. "
            "It takes about 10 minutes.\n\n[Link]\n\nThis link is just for you and expires on [Due date]. Questions? Reply to this email.\n\n[Sender name]",
}
if TEMPLATE["key"] not in library.DEFAULT_KEYS:
    library.DEFAULTS.append(TEMPLATE)
    library.DEFAULT_KEYS.add(TEMPLATE["key"])


def responded(db: Session, policy_id: str) -> set[str]:
    return svc.acknowledged_emails(db, policy_id)


def _policy(db: Session, s: MailSend) -> PolicyDocument:
    p = db.get(PolicyDocument, s.campaign_id) if s.campaign_type == svc.CAMPAIGN else None
    if p is None or p.deleted_at is not None or p.organization_id != s.organization_id:
        raise NotFound("This link is not valid.")
    return p


def link_form(db: Session, r: MailRecipient | None, s: MailSend) -> dict:
    p = _policy(db, s)
    org = db.get(Organization, p.organization_id)
    out = {"kind": "policy_ack", "organization": org.name if org else "", "title": p.title, "version_no": p.version_no, "status": p.status,
           "approved_at": p.approved_at.isoformat() if p.approved_at else None, "blocks": p.blocks if p.status == "published" else []}
    if r is not None:
        out["already_acknowledged"] = r.email.lower() in svc.acknowledged_emails(db, p.id)
    return out


def submit_link(db: Session, r: MailRecipient, s: MailSend, payload: dict):
    p = _policy(db, s)
    if p.status != "published":
        raise Conflict("This version of the policy has been replaced. Use the link in your most recent email.")
    if payload.get("confirm") is not True:
        raise Invalid(errors=[{"field": "confirm", "message": "Confirm that you have read the policy."}])
    person = db.get(DirectoryPerson, r.person_id) if r.person_id else None
    a = svc.record_acknowledgment(db, p, r.email, (person.name if person else None) or r.name, person=person, recipient_id=r.id)
    links.mark_completed(db, r)
    return a


sending.RESPONDED[svc.CAMPAIGN] = responded
sending.LINK_PURPOSES[svc.CAMPAIGN] = {"form": link_form, "submit": submit_link}
