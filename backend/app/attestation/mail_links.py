"""Attestation by email (spec §27.1): "Send to all employees" from the tracker, with personal links (or a shared BCC
link with a one-time code). A link answer goes through the same recording as the staff link: it supersedes the
person's earlier answer, is tied to their login when the email matches one, and feeds the inventory."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.attestation import service as att
from app.attestation.models import Attestation, AttestationCampaign
from app.core.errors import Invalid, NotFound
from app.engagements.models import Engagement
from app.mail import links, sending
from app.mail.groups import default_group
from app.mail.models import DirectoryPerson, MailRecipient, MailSend
from app.tenancy.models import User

CAMPAIGN = "attestation"


def responded(db: Session, campaign_id: str) -> set[str]:
    """Emails that have a current answer in the campaign (through any route)."""
    rows = att.current_answers(db, campaign_id)
    out = {r.respondent_email.lower() for r in rows if r.respondent_email}
    ids = {r.user_id for r in rows if r.user_id}
    if ids:
        out |= {e.lower() for e in db.scalars(select(User.email).where(User.id.in_(ids)))}
    return out


sending.RESPONDED[CAMPAIGN] = responded

CLOSED_MESSAGE = att.CLOSED_MESSAGE


def closed_reason(db: Session, campaign_id: str | None, at) -> str | None:
    """BUG-12: the attestation request goes out only while its campaign is open, from any screen (sending.CLOSED)."""
    c = db.get(AttestationCampaign, campaign_id) if campaign_id else None
    if campaign_id and c is None:
        return None  # not an attestation campaign row (a caller's own reference); nothing to judge
    if c is None or c.deleted_at is not None:
        return "There is no attestation campaign for this engagement, so the attestation can't be sent. Launch a campaign first."
    if not att.is_open(c):
        return att.closed_message(db, c)
    if at is not None and at >= c.closes_at:
        later = "" if att.discovery_finished(db.get(Engagement, c.engagement_id)) else " or launch a new campaign"
        return f"The campaign closes on {c.closes_at.day} {c.closes_at:%B %Y}, before this email would go out. Choose an earlier time{later}."
    return None


sending.CLOSED[CAMPAIGN] = closed_reason


def _options(body: dict) -> dict:
    mode = body.get("mode") or "personal"
    if mode not in ("personal", "bcc"):
        raise Invalid(errors=[{"field": "mode", "message": "Choose personal links or BCC."}])
    days = body.get("reminder_days")
    return {"department_ids": [d for d in body.get("department_ids") or [] if isinstance(d, str)] or None,
            "offices": [o for o in body.get("offices") or [] if isinstance(o, str) and o.strip()] or None,
            "exclude_responded": bool(body.get("exclude_responded", True)), "mode": mode,
            "reminder_days": [3, 7] if days is None else [int(d) for d in days if str(d).isdigit()],
            "link_days": int(body.get("link_days") or 14)}


def preview_all(db: Session, c: AttestationCampaign, body: dict) -> dict:
    o = _options(body)
    g = default_group(db, c.organization_id, "all_employees")
    ex = sending.preview_expansion(db, c.organization_id, [g.id], exclude_responded=o["exclude_responded"], campaign=(CAMPAIGN, c.id),
                                   department_ids=o["department_ids"], offices=o["offices"])
    return {"steps": ex.steps, "total": len(ex.people), "people": [{"name": p.name, "email": p.email} for p in ex.people[:2000]]}


def send_all(db: Session, settings, actor: User, c: AttestationCampaign, body: dict) -> MailSend:
    if not att.is_open(c):
        from app.core.errors import Conflict

        raise Conflict(att.closed_message(db, c))
    o = _options(body)
    g = default_group(db, c.organization_id, "all_employees")
    closes = f"{c.closes_at.day} {c.closes_at:%B %Y}"
    return sending.send_to_groups(db, settings, actor, organization_id=c.organization_id, group_ids=[g.id], template_key="attestation_request", engagement_id=c.engagement_id,
                                  exclude_responded=o["exclude_responded"], campaign=(CAMPAIGN, c.id), department_ids=o["department_ids"], offices=o["offices"],
                                  mode=o["mode"], reminder_days=o["reminder_days"] or None, link_days=o["link_days"], context={"Closes": closes}, related=c)


def _campaign(db: Session, s: MailSend) -> AttestationCampaign:
    c = db.get(AttestationCampaign, s.campaign_id) if s.campaign_type == CAMPAIGN else None
    if c is None or c.deleted_at is not None:
        raise NotFound("This link is not valid.")
    return c


def link_form(db: Session, r: MailRecipient | None, s: MailSend) -> dict:
    """What the employee sees: the screen 13 form, with name and department filled in from the directory."""
    c = _campaign(db, s)
    out = {"kind": "attestation", **att.public_view(db, c)}
    if r is not None:
        p = db.get(DirectoryPerson, r.person_id) if r.person_id else None
        dept = p.department_id if p is not None and p.department_id in (c.department_ids or []) else None
        out["prefill"] = {"respondent_name": (p.name if p else r.name) or "", "respondent_email": r.email, "department_id": dept}
        out["already_answered"] = r.email.lower() in responded(db, c.id)
    return out


def submit_link(db: Session, r: MailRecipient, s: MailSend, payload: dict) -> Attestation:
    """Record the answer as the person the link was sent to. Their email cannot be changed on a personal link."""
    c = _campaign(db, s)
    if not att.is_open(c):
        raise att.Gone("This check-in has closed. Thank you; no answer is needed now.")
    data = dict(payload) | {"respondent_email": r.email}
    values = att._clean(data, c)
    user = db.scalar(select(User).where(User.organization_id == c.organization_id, func.lower(User.email) == r.email.lower(), User.deleted_at.is_(None)))
    a = att._record(db, c, values, user=user, source="link")
    links.mark_completed(db, r)
    return a


sending.LINK_PURPOSES[CAMPAIGN] = {"form": link_form, "submit": submit_link}
