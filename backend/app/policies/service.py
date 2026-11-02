"""Policy builder (spec §21 F7, screen 27).

From a governance commitment of kind "Will create" (§10.5) the client starts from a Futran template, answers the guided
questions, edits the generated draft (headings, paragraphs and lists only) and sends it to the Chief AI Compliance
Officer. The CAICO's approval publishes it: the PDF is stored as the commitment's evidence, the commitment closes, an
earlier version is retired and, when asked, a staff acknowledgment campaign goes out through the email service with
personal links (the attestation pattern, campaign type "policy_ack").

"Request Futran review" opens a Sales opportunity (§27.5). When Futran tailors a policy, the Chief Auditor records the
team on the document; `app.engagements.team.check_lead_independence` then refuses any of those people as Lead Auditor on a
later engagement for the client.
"""
from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.governance.models import Commitment, GovernanceItem
from app.policies import templates as T
from app.policies.models import PolicyAcknowledgment, PolicyDocument, PolicyTemplate
from app.tenancy.models import Organization, RoleAssignment, User

CAMPAIGN = "policy_ack"
OPEN_COMMITMENT = ("open", "in_progress", "reopened")
STATUS_LABELS = {"draft": "Draft", "awaiting_approval": "Awaiting approval", "published": "Published", "retired": "Retired"}


# ---- templates
def ensure_templates(db: Session) -> dict[str, PolicyTemplate]:
    """Record each template version the first time it is used. Returns the current version of each code."""
    out = {}
    for t in T.library().values():
        row = db.scalar(select(PolicyTemplate).where(PolicyTemplate.code == t.code, PolicyTemplate.version == t.version))
        if row is None:
            row = PolicyTemplate(code=t.code, version=t.version, title=t.title, summary=t.summary, catalog_codes=list(t.catalog_codes), questions=t.questions,
                                 body=t.body, content_sha256=hashlib.sha256(t.body.encode()).hexdigest())
            db.add(row)
            db.flush()
        out[t.code] = row
    return out


def template_def(p: PolicyDocument) -> T.TemplateDef:
    t = T.library().get(p.template_code)
    if t is None:
        raise NotFound("The template for this policy is no longer available.")
    return t


def template_out(t: T.TemplateDef) -> dict:
    return {"code": t.code, "version": t.version, "title": t.title, "name": t.name, "summary": t.summary, "catalog_codes": list(t.catalog_codes)}


# ---- commitments
def open_commitments(db: Session, org_id: str) -> list[dict]:
    """"Will create" commitments a policy can still answer: open, and not yet linked to a live policy."""
    taken = set(db.scalars(select(PolicyDocument.commitment_id).where(PolicyDocument.organization_id == org_id, PolicyDocument.deleted_at.is_(None),
                                                                      PolicyDocument.status != "retired", PolicyDocument.commitment_id.is_not(None))))
    out = []
    rows = db.scalars(select(Commitment).where(Commitment.organization_id == org_id, Commitment.deleted_at.is_(None), Commitment.status.in_(OPEN_COMMITMENT))
                      .order_by(Commitment.target_date))
    for c in rows:
        if c.id in taken:
            continue
        item = db.get(GovernanceItem, c.source_id)
        out.append({"id": c.id, "description": c.description, "target_date": c.target_date.isoformat(), "owner": c.owner, "status": c.status,
                    "catalog_code": item.catalog_code if item else None, "suggested_template": T.for_catalog_code(item.catalog_code) if item else None})
    return out


def _commitment(db: Session, org_id: str, commitment_id: str | None) -> Commitment | None:
    if not commitment_id:
        return None
    c = db.get(Commitment, commitment_id)
    if c is None or c.deleted_at is not None or c.organization_id != org_id:
        raise NotFound("That commitment no longer exists.")
    if c.status not in OPEN_COMMITMENT:
        raise Conflict("That commitment is already closed.")
    if db.scalar(select(PolicyDocument.id).where(PolicyDocument.commitment_id == c.id, PolicyDocument.deleted_at.is_(None), PolicyDocument.status != "retired")):
        raise Conflict("A policy is already being built for that commitment. Open it from the policy list.")
    return c


# ---- lifecycle
def get(db: Session, org_id: str, policy_id: str) -> PolicyDocument:
    p = db.get(PolicyDocument, policy_id)
    if p is None or p.deleted_at is not None or p.organization_id != org_id:
        raise NotFound()
    return p


def start(db: Session, actor: User, org: Organization, template_code: str, commitment_id: str | None = None) -> PolicyDocument:
    t = T.library().get(template_code or "")
    if t is None:
        raise Invalid(errors=[{"field": "template_code", "message": "Choose a template."}])
    c = _commitment(db, org.id, commitment_id)
    row = ensure_templates(db)[t.code]
    answers = T.defaults(t, org.name)
    p = PolicyDocument(organization_id=org.id, template_id=row.id, template_code=t.code, template_version=t.version, title=t.name, commitment_id=c.id if c else None,
                       answers=answers, blocks=T.render(t, answers), status="draft", created_by=actor.id)
    db.add(p)
    db.flush()
    if c is not None and c.status == "open":
        c.status = "in_progress"
    audit.record(db, actor_id=actor.id, action="policy.start", obj=p, after={"template": f"{t.code} v{t.version}", "commitment_id": p.commitment_id},
                 summary=f"Started {t.name} from the Futran template v{t.version}")
    return p


def _editable(p: PolicyDocument) -> None:
    if p.status != "draft":
        raise Conflict("Only a draft can be changed. " + ("Ask the Chief AI Compliance Officer to return it first." if p.status == "awaiting_approval" else "Start a new version to change a published policy."))


def save_answers(db: Session, actor: User, p: PolicyDocument, raw: dict, regenerate: bool) -> PolicyDocument:
    _editable(p)
    t = template_def(p)
    answers, _ = T.clean_answers(t, raw)  # incomplete answers are kept while the draft is worked on; submit checks them
    p.answers = answers
    if regenerate:
        p.blocks, p.edited = T.render(t, answers), False
    p.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="policy.answers", obj=p, after={"regenerated": regenerate}, summary=f"Updated the answers for {p.title}" + (" and regenerated the draft" if regenerate else ""))
    return p


def save_text(db: Session, actor: User, p: PolicyDocument, raw) -> PolicyDocument:
    _editable(p)
    blocks, errs = T.clean_blocks(raw)
    if errs:
        raise Invalid("The policy text could not be saved.", errs)
    p.blocks, p.edited, p.updated_by = blocks, True, actor.id
    audit.record(db, actor_id=actor.id, action="policy.edit", obj=p, summary=f"Edited the text of {p.title}")
    return p


def caicos(db: Session, org_id: str) -> list[User]:
    return list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(
        User.organization_id == org_id, User.deleted_at.is_(None), User.status == "active", RoleAssignment.role == "caico", RoleAssignment.deleted_at.is_(None))))


def submit(db: Session, settings, actor: User, p: PolicyDocument) -> PolicyDocument:
    from app.notifications.service import notify

    _editable(p)
    t = template_def(p)
    _, errs = T.clean_answers(t, p.answers)
    if errs:
        raise Invalid("Answer every question before sending the policy for approval.", errs)
    _, errs = T.clean_blocks(p.blocks)
    if errs:
        raise Invalid("The policy text has a problem.", errs)
    p.status, p.submitted_by, p.submitted_at, p.return_note = "awaiting_approval", actor.id, utcnow(), None
    notify(db, [u for u in caicos(db, p.organization_id) if u.id != actor.id], "policy_awaiting_approval", f"{p.title} is waiting for your approval",
           f"Sent by {actor.name}.", f"/policies/{p.id}", settings=settings)
    audit.record(db, actor_id=actor.id, action="policy.submit", obj=p, summary=f"Sent {p.title} for approval")
    return p


def return_to_draft(db: Session, actor: User, p: PolicyDocument, note: str | None) -> PolicyDocument:
    from app.notifications.service import notify

    if p.status != "awaiting_approval":
        raise Conflict("Only a policy waiting for approval can be returned.")
    note = " ".join(str(note or "").split())[:2000]
    if not note:
        raise Invalid(errors=[{"field": "note", "message": "Say what needs to change."}])
    p.status, p.return_note = "draft", note
    who = db.get(User, p.submitted_by) if p.submitted_by else None
    if who is not None and who.id != actor.id:
        notify(db, [who], "policy_returned", f"{p.title} was returned", note, f"/policies/{p.id}")
    audit.record(db, actor_id=actor.id, action="policy.return", obj=p, after={"note": note}, summary=f"Returned {p.title}: {note[:120]}")
    return p


def _add_months(d: date, months: int) -> date:
    import calendar

    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def render_pdf(db: Session, p: PolicyDocument) -> bytes:
    from app.documents.pdf import to_pdf

    org = db.get(Organization, p.organization_id)
    t = T.library().get(p.template_code)
    status = f"Version {p.version_no}" + (f", approved {p.approved_at:%d %B %Y}" if p.approved_at else ", draft")
    meta_line = f"{status}. Built from the Futran {t.name if t else 'policy'} template v{p.template_version}."
    if p.review_due:
        meta_line += f" Next review by {p.review_due:%d %B %Y}."
    md = T.blocks_to_markdown(p.blocks)
    head, _, rest = md.partition("\n\n")
    return to_pdf(f"{head}\n\n*{meta_line}*\n\n{rest}", p.title, {"audit_ref": org.name if org else ""})


def approve(db: Session, settings, actor: User, p: PolicyDocument, acknowledgment: dict | None) -> PolicyDocument:
    """Approval publishes: PDF stored, commitment closed with it as evidence, the previous version retired, and the
    acknowledgment campaign sent when asked."""
    from app.files.service import upload

    if p.status != "awaiting_approval":
        raise Conflict("Send the policy for approval first.")
    now = utcnow()
    months = T.REVIEW_MONTHS.get(p.answers.get("review_cycle"), 12)
    p.status, p.approved_by, p.approved_at, p.published_at = "published", actor.id, now, now
    p.review_months, p.review_due = months, _add_months(now.date(), months)
    org = db.get(Organization, p.organization_id)
    f = upload(db, settings, actor, data=render_pdf(db, p), filename=f"{org.name} {p.title} v{p.version_no}.pdf", content_type="application/pdf",
               organization_id=p.organization_id, linked_type="policy_document", linked_id=p.id)
    p.published_file_id = f.id
    if p.supersedes_id:
        old = db.get(PolicyDocument, p.supersedes_id)
        if old is not None and old.status == "published":
            old.status, old.retired_at = "retired", now
    audit.record(db, actor_id=actor.id, action="policy.publish", obj=p, after={"version_no": p.version_no, "review_due": p.review_due.isoformat(), "file_id": f.id},
                 summary=f"Approved and published {p.title} version {p.version_no}")
    _close_commitment(db, actor, p)
    if acknowledgment is not None:
        send_acknowledgments(db, settings, actor, p, acknowledgment)
    return p


def _close_commitment(db: Session, actor: User, p: PolicyDocument) -> None:
    """The commitment closes with the published policy as its evidence (§21 F7). When the engagement already tracks it as a
    remediation item, that item goes to the auditor as done, so Futran still verifies it (§9.6)."""
    from app.remediation.models import RemediationItem

    c = db.get(Commitment, p.commitment_id) if p.commitment_id else None
    if c is None or c.status == "closed":
        return
    before = c.status
    c.status = "closed"
    item = db.scalar(select(RemediationItem).where(RemediationItem.commitment_id == c.id, RemediationItem.deleted_at.is_(None)))
    if item is not None and item.status in ("open", "in_progress", "reopened"):
        item.status = "awaiting_verification"
        item.done_note = f"Published {p.title} version {p.version_no} on {p.published_at:%d %B %Y}. The published policy is the evidence."
        item.marked_done_by, item.marked_done_at = actor.id, utcnow()
    audit.record(db, actor_id=actor.id, action="commitment.close", obj=c, before={"status": before}, after={"status": "closed", "policy_id": p.id, "file_id": p.published_file_id},
                 summary=f"Closed the commitment '{c.description}' with the published {p.title}")


def new_version(db: Session, actor: User, p: PolicyDocument) -> PolicyDocument:
    if p.status != "published":
        raise Conflict("Only a published policy can have a new version.")
    if db.scalar(select(PolicyDocument.id).where(PolicyDocument.supersedes_id == p.id, PolicyDocument.deleted_at.is_(None), PolicyDocument.status != "retired")):
        raise Conflict("A new version of this policy is already being worked on.")
    n = PolicyDocument(organization_id=p.organization_id, template_id=p.template_id, template_code=p.template_code, template_version=p.template_version, title=p.title,
                       answers=dict(p.answers), blocks=list(p.blocks), edited=p.edited, status="draft", version_no=p.version_no + 1, supersedes_id=p.id,
                       authored_by_futran_team=list(p.authored_by_futran_team or []), created_by=actor.id)
    db.add(n)
    db.flush()
    audit.record(db, actor_id=actor.id, action="policy.new_version", obj=n, summary=f"Started version {n.version_no} of {p.title}")
    return n


# ---- acknowledgments (personal links through the email service)
def acknowledged_emails(db: Session, policy_id: str) -> set[str]:
    return {e.lower() for e in db.scalars(select(PolicyAcknowledgment.email).where(PolicyAcknowledgment.policy_id == policy_id, PolicyAcknowledgment.deleted_at.is_(None)))}


def send_acknowledgments(db: Session, settings, actor: User, p: PolicyDocument, body: dict):
    from app.mail.groups import default_group
    from app.mail.sending import send_to_groups

    if p.status != "published":
        raise Conflict("Only a published policy can be sent for acknowledgment.")
    group_ids = [g for g in body.get("group_ids") or [] if isinstance(g, str)] or [default_group(db, p.organization_id, "all_employees").id]
    days = body.get("reminder_days")
    plan = [3, 7] if days is None else [int(d) for d in days if str(d).isdigit()]
    s = send_to_groups(db, settings, actor, organization_id=p.organization_id, group_ids=group_ids, template_key="policy_acknowledgment", exclude_responded=True,
                       campaign=(CAMPAIGN, p.id), department_ids=[d for d in body.get("department_ids") or [] if isinstance(d, str)] or None, mode="personal",
                       reminder_days=plan or None, link_days=int(body.get("link_days") or 21), context={"Policy": p.title}, related=p)
    audit.record(db, actor_id=actor.id, action="policy.acknowledgment_send", obj=p, after={"send_id": s.id, "recipients": s.recipient_count},
                 summary=f"Asked {s.recipient_count} people to acknowledge {p.title}")
    return s


def ack_stats(db: Session, p: PolicyDocument) -> dict:
    from app.mail.models import MailRecipient, MailSend

    sent = {e.lower() for e in db.scalars(select(MailRecipient.email).join(MailSend, MailSend.id == MailRecipient.send_id)
                                          .where(MailSend.campaign_type == CAMPAIGN, MailSend.campaign_id == p.id))}
    done = acknowledged_emails(db, p.id)
    return {"sent": len(sent), "acknowledged": len(done), "outstanding": len(sent - done)}


def ack_rows(db: Session, p: PolicyDocument) -> list[dict]:
    from app.mail.models import MailRecipient, MailSend
    from app.tenancy.models import Department

    acks = {a.email.lower(): a for a in db.scalars(select(PolicyAcknowledgment).where(PolicyAcknowledgment.policy_id == p.id, PolicyAcknowledgment.deleted_at.is_(None)))}
    people: dict[str, dict] = {}
    for r in db.scalars(select(MailRecipient).join(MailSend, MailSend.id == MailRecipient.send_id).where(MailSend.campaign_type == CAMPAIGN, MailSend.campaign_id == p.id)):
        people.setdefault(r.email.lower(), {"email": r.email.lower(), "name": r.name, "status": r.status})
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == p.organization_id))}
    out = []
    for email in sorted(set(people) | set(acks)):
        a = acks.get(email)
        row = people.get(email, {"email": email, "name": a.name if a else None, "status": None})
        out.append(row | {"department": depts.get(a.department_id) if a and a.department_id else None, "acknowledged_at": a.acknowledged_at.isoformat() if a else None})
    return out


def record_acknowledgment(db: Session, p: PolicyDocument, email: str, name: str | None, person=None, recipient_id: str | None = None) -> PolicyAcknowledgment:
    email = email.lower()
    a = db.scalar(select(PolicyAcknowledgment).where(PolicyAcknowledgment.policy_id == p.id, PolicyAcknowledgment.email == email))
    if a is not None:
        return a
    user = db.scalar(select(User).where(User.organization_id == p.organization_id, func.lower(User.email) == email, User.deleted_at.is_(None)))
    a = PolicyAcknowledgment(organization_id=p.organization_id, policy_id=p.id, email=email, name=name, user_id=user.id if user else None,
                             department_id=getattr(person, "department_id", None), acknowledged_at=utcnow(), source="link", recipient_id=recipient_id)
    db.add(a)
    db.flush()
    audit.record(db, actor_id=user.id if user else None, actor_name=name or email, action="policy.acknowledge", obj=a, organization_id=p.organization_id,
                 summary=f"{name or email} acknowledged {p.title} version {p.version_no}")
    return a


# ---- Futran review and the independence rule
def request_futran_review(db: Session, actor: User, p: PolicyDocument, note: str | None) -> PolicyDocument:
    from app.sales.service import open_from_trigger

    if p.futran_opportunity_id:
        raise Conflict("Futran has already been asked to review this policy.")
    note = " ".join(str(note or "").split())[:1000] or None
    o = open_from_trigger(db, p.organization_id, "policy_review", f"policy:{p.id}", service=f"Policy tailoring: {p.title}", service_kind="advisory",
                          why_now=f"{actor.name} asked Futran to review the {p.title}" + (f": {note}" if note else ""), created_by=actor.id)
    p.futran_review_requested_at, p.futran_review_note, p.futran_opportunity_id = utcnow(), note, o.id
    audit.record(db, actor_id=actor.id, action="policy.futran_review", obj=p, after={"opportunity_id": o.id}, summary=f"Asked Futran to review {p.title}")
    return p


def record_futran_team(db: Session, actor: User, p: PolicyDocument, user_ids: list[str]) -> PolicyDocument:
    """The Futran people who wrote or tailored this policy. They may not later be Lead Auditor for this client."""
    from app.tenancy.models import Organization as Org

    ids = []
    for uid in dict.fromkeys(u for u in user_ids or [] if isinstance(u, str)):
        u = db.get(User, uid)
        org = db.get(Org, u.organization_id) if u else None
        if u is None or org is None or org.type != "futran":
            raise Invalid(errors=[{"field": "user_ids", "message": "Choose Futran team members."}])
        ids.append(uid)
    before = list(p.authored_by_futran_team or [])
    p.authored_by_futran_team, p.futran_team_recorded_by, p.futran_team_recorded_at = ids, actor.id, utcnow()
    names = [db.get(User, i).name for i in ids]
    audit.record(db, actor_id=actor.id, action="policy.futran_team", obj=p, before={"team": before}, after={"team": ids},
                 summary=f"Recorded the Futran team that tailored {p.title}: {', '.join(names) or 'nobody'}")
    return p


def tailored_by(db: Session, client_id: str, user_id: str) -> list[PolicyDocument]:
    """Live policies of this client that `user_id` helped write (SQLite and Postgres both store the list as JSON text)."""
    rows = db.scalars(select(PolicyDocument).where(PolicyDocument.organization_id == client_id, PolicyDocument.deleted_at.is_(None)))
    return [p for p in rows if user_id in (p.authored_by_futran_team or [])]


# ---- output
def doc_out(db: Session, p: PolicyDocument, *, full: bool = True) -> dict:
    from app.files.models import FileObject

    c = db.get(Commitment, p.commitment_id) if p.commitment_id else None
    t = T.library().get(p.template_code)
    name = lambda uid: (db.get(User, uid).name if uid and db.get(User, uid) else None)  # noqa: E731
    f = db.get(FileObject, p.published_file_id) if p.published_file_id else None
    out = {
        "id": p.id, "title": p.title, "status": p.status, "status_label": STATUS_LABELS.get(p.status, p.status), "version_no": p.version_no,
        "template": {"code": p.template_code, "version": p.template_version, "name": t.name if t else p.title, "current_version": t.version if t else None},
        "commitment": {"id": c.id, "description": c.description, "target_date": c.target_date.isoformat(), "status": c.status} if c else None,
        "submitted_by": name(p.submitted_by), "submitted_at": p.submitted_at.isoformat() if p.submitted_at else None, "return_note": p.return_note,
        "approved_by": name(p.approved_by), "approved_at": p.approved_at.isoformat() if p.approved_at else None,
        "published_at": p.published_at.isoformat() if p.published_at else None, "review_due": p.review_due.isoformat() if p.review_due else None,
        "review_overdue": p.status == "published" and p.review_due is not None and p.review_due < today(),
        "published_file": {"id": f.id, "filename": f.filename} if f else None, "edited": p.edited,
        "futran_review_requested_at": p.futran_review_requested_at.isoformat() if p.futran_review_requested_at else None,
        "futran_team": [{"id": i, "name": name(i)} for i in p.authored_by_futran_team or []],
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if p.status in ("published", "retired"):
        out["acknowledgments"] = ack_stats(db, p)
    if full:
        out |= {"answers": p.answers, "blocks": p.blocks, "questions": t.questions if t else []}
    return out
