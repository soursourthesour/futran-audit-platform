"""Email templates for group sends (spec §26.6). Futran ships the defaults; a client can copy one and edit its copy.
Every edit adds a version; a send records the version it used.

Merge fields: [First name], [Name], [Department], [Link], [Due date], [Sender name], [Organization]. Any other value the
caller passes in `context` is available as [Key] too, for example [Changes] for a regulatory change alert.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import Invalid, NotFound
from app.core.ids import new_id
from app.mail.models import FUTRAN_OWNER, MailTemplate

MERGE_FIELDS = ["First name", "Name", "Department", "Link", "Due date", "Sender name", "Organization"]
PURPOSES = ("attestation", "approval", "evidence", "notice", "training", "alert", "initiation", "general")

DEFAULTS = [
    {
        "key": "attestation_request", "name": "Attestation: tell us which AI tools you use", "purpose": "attestation", "default_mode": "personal",
        "subject": "2 minutes: which AI tools do you use at work?", "button_label": "Fill in my AI tools",
        "body": "Hi [First name],\n\n[Organization] is reviewing how AI is used across the company, with our independent auditor Futran Solutions. "
                "Please tell us which AI tools you use for work, including free ones like ChatGPT.\n\nIt takes about 2 minutes. You don't need to sign in, "
                "and there are no wrong answers.\n\n[Link]\n\nThis link is just for you and expires on [Due date]. Questions? Reply to this email.\n\n[Sender name]",
    },
    {
        "key": "dept_head_approval", "name": "Department head: approve your department's AI inventory", "purpose": "approval", "default_mode": "personal",
        "subject": "Please approve the AI inventory for [Department]", "button_label": "Review the inventory",
        "body": "Hi [First name],\n\nThe AI inventory for [Department] is ready for your review. Check the tools and use cases listed, correct anything "
                "that is wrong and approve it by [Due date].\n\n[Link]\n\n[Sender name]",
    },
    {
        "key": "ll144_notice", "name": "Notice: AI use in hiring (NYC LL144)", "purpose": "notice", "default_mode": "bcc",
        "subject": "Notice: use of automated employment decision tools", "button_label": "Read the notice",
        "body": "Hello,\n\n[Organization] uses automated employment decision tools in hiring and promotion decisions for roles in New York City. "
                "This notice explains what the tools assess, the data they use and how to ask for an alternative process.\n\n[Link]\n\n[Sender name]",
    },
    {
        "key": "training_ai_literacy", "name": "Training: AI literacy module", "purpose": "training", "default_mode": "personal",
        "subject": "AI literacy training to complete by [Due date]", "button_label": "Start the module",
        "body": "Hi [First name],\n\nPlease complete the AI literacy module by [Due date]. It takes about 20 minutes and covers the company's AI use policy.\n\n[Link]\n\n[Sender name]",
    },
    {
        "key": "regulatory_change_alert", "name": "Regulatory change alert", "purpose": "alert", "default_mode": "personal",
        "subject": "AI regulation update for [Organization]", "button_label": "See what changes",
        "body": "Hi [First name],\n\nA law that applies to [Organization] has changed. The AI systems affected and the actions to take are listed on the platform.\n\n"
                "[Changes]\n\n[Link]\n\n[Sender name]",
    },
    {
        "key": "evidence_request", "name": "Evidence request", "purpose": "evidence", "default_mode": "personal",
        "subject": "Evidence requested for the AI governance audit", "button_label": "Upload the evidence",
        "body": "Hi [First name],\n\nFutran's auditors need evidence from you for the AI governance audit. Please upload it by [Due date].\n\n[Link]\n\n[Sender name]",
    },
    {
        "key": "initiation_package", "name": "Initiation package", "purpose": "initiation", "default_mode": "personal",
        "subject": "Your AI governance assessment: initiation package", "button_label": "Open the initiation package",
        "body": "Hi [First name],\n\nThe initiation package for [Organization]'s AI governance assessment is ready. Please work through the items by [Due date].\n\n[Link]\n\n[Sender name]",
    },
]
DEFAULT_KEYS = {d["key"] for d in DEFAULTS}


def ensure_defaults(db: Session) -> None:
    have = set(db.scalars(select(MailTemplate.key).where(MailTemplate.organization_id == FUTRAN_OWNER)))
    for d in DEFAULTS:
        if d["key"] not in have:
            db.add(MailTemplate(organization_id=FUTRAN_OWNER, owner="futran", family_id=new_id(), version=1, language="en", merge_fields=MERGE_FIELDS, **d))
    db.flush()


def current(db: Session, owner_org_id: str, key: str) -> MailTemplate | None:
    return db.scalar(select(MailTemplate).where(MailTemplate.organization_id == owner_org_id, MailTemplate.key == key, MailTemplate.superseded_at.is_(None),
                                                MailTemplate.deleted_at.is_(None)).order_by(MailTemplate.version.desc()).limit(1))


def for_send(db: Session, org_id: str, key: str) -> MailTemplate:
    """The client's own copy when it has one, else Futran's default."""
    ensure_defaults(db)
    t = current(db, org_id, key) or current(db, FUTRAN_OWNER, key)
    if t is None:
        raise Invalid(errors=[{"field": "template", "message": "Choose a template."}])
    return t


def available(db: Session, org_id: str | None) -> list[MailTemplate]:
    """Current templates a sender can choose: the client's copies, and Futran's defaults it has not copied."""
    ensure_defaults(db)
    futran = list(db.scalars(select(MailTemplate).where(MailTemplate.organization_id == FUTRAN_OWNER, MailTemplate.superseded_at.is_(None), MailTemplate.deleted_at.is_(None))))
    own = list(db.scalars(select(MailTemplate).where(MailTemplate.organization_id == org_id, MailTemplate.superseded_at.is_(None), MailTemplate.deleted_at.is_(None)))) if org_id else []
    copied = {t.key for t in own}
    return sorted(own + [t for t in futran if t.key not in copied], key=lambda t: t.name.lower())


def copy_for_client(db: Session, actor_id: str, org_id: str, key: str) -> MailTemplate:
    base = for_send(db, org_id, key)
    if base.organization_id == org_id:
        return base
    t = MailTemplate(organization_id=org_id, owner="client", key=base.key, family_id=new_id(), name=base.name, purpose=base.purpose, default_mode=base.default_mode,
                     subject=base.subject, body=base.body, button_label=base.button_label, merge_fields=base.merge_fields, version=1, language=base.language,
                     copied_from_id=base.id, created_by=actor_id)
    db.add(t)
    db.flush()
    return t


def edit(db: Session, actor_id: str, t: MailTemplate, data: dict) -> MailTemplate:
    """Save a new version. The old version stays, so earlier sends still show what they used."""
    if t.superseded_at is not None:
        raise NotFound()
    subject = " ".join(str(data.get("subject", t.subject)).split())[:300]
    body = str(data.get("body", t.body)).strip()[:20000]
    if not subject or not body:
        raise Invalid(errors=[{"field": "subject" if not subject else "body", "message": "A template needs a subject and a message."}])
    mode = data.get("default_mode", t.default_mode)
    if mode not in ("personal", "bcc"):
        raise Invalid(errors=[{"field": "default_mode", "message": "Choose personal link or BCC."}])
    new = MailTemplate(organization_id=t.organization_id, owner=t.owner, key=t.key, family_id=t.family_id, name=" ".join(str(data.get("name", t.name)).split())[:160] or t.name,
                       purpose=t.purpose, default_mode=mode, subject=subject, body=body, button_label=t.button_label, merge_fields=t.merge_fields,
                       version=t.version + 1, language=t.language, copied_from_id=t.copied_from_id, created_by=actor_id)
    t.superseded_at = utcnow()
    db.add(new)
    db.flush()
    return new


_FIELD = re.compile(r"\[([A-Za-z][A-Za-z ]{0,40})\]")


def merge(text: str, values: dict[str, str]) -> str:
    """Replace [Field] with its value. Unknown fields are left as typed so the sender sees them in the preview."""
    lookup = {k.lower(): v for k, v in values.items()}
    return _FIELD.sub(lambda m: str(lookup.get(m.group(1).lower(), m.group(0))), text)


def template_out(t: MailTemplate) -> dict:
    return {"id": t.id, "key": t.key, "name": t.name, "purpose": t.purpose, "default_mode": t.default_mode, "subject": t.subject, "body": t.body,
            "button_label": t.button_label, "version": t.version, "owner": t.owner, "language": t.language, "merge_fields": t.merge_fields or MERGE_FIELDS}
