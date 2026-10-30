"""Delivery channels. Every message is recorded as an OutboxMessage (Admin > Outbox shows it), then delivered through
one channel:

- outbox: test mode; nothing leaves the platform;
- smtp: the SMTP relay in .env (the fallback when no mailbox is connected);
- microsoft365 / google: the connected organisation mailbox, or a user's own mailbox (§26.1, §27.1).

A delivery failure is recorded on the message, never raised: a mail failure must not lose the business action.
"""
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.mail.models import MailConnection, OutboxMessage, UserMailConnection
from app.tenancy.models import Organization


@dataclass
class Sender:
    channel: str  # outbox | smtp | microsoft365 | google
    from_name: str
    from_address: str
    reply_to: str | None = None
    connection: MailConnection | None = None
    user_connection: UserMailConnection | None = None

    @property
    def label(self) -> str:
        return f"{self.from_name} · {self.from_address}" if self.from_address else self.from_name

    @property
    def is_provider(self) -> bool:
        return self.channel in ("microsoft365", "google")


@dataclass
class Envelope:
    to: list[str]
    subject: str
    html: str
    text: str
    bcc: list[str] = field(default_factory=list)
    thread_ref: str | None = None
    cc: list[str] = field(default_factory=list)


@dataclass
class Result:
    ok: bool
    provider_message_id: str | None = None
    provider_thread_id: str | None = None
    error: str | None = None


def one_line(value: str | None) -> str:
    """A header value on one line: line breaks and tabs become spaces and other control characters are dropped, so text
    from a template, a form or a merge field can never add a header (spec §26.4)."""
    folded = " ".join((value or "").split())
    return "".join(c for c in folded if c >= " " and c != "\x7f")


def fallback_sender(settings: Settings) -> Sender:
    name, addr = parseaddr(settings.smtp_from)
    return Sender(channel="smtp" if settings.email_mode == "smtp" else "outbox", from_name=name or "Futran Audit Platform", from_address=addr)


def futran_connection(db: Session) -> MailConnection | None:
    return db.scalar(select(MailConnection).where(MailConnection.owner == "futran", MailConnection.status == "connected", MailConnection.deleted_at.is_(None)).limit(1))


def org_connection(db: Session, org_id: str) -> MailConnection | None:
    return db.scalar(select(MailConnection).where(MailConnection.organization_id == org_id, MailConnection.deleted_at.is_(None)).limit(1))


def _usable(settings: Settings, conn: MailConnection | None) -> bool:
    if conn is None or conn.status != "connected" or not conn.provider or not conn.mailbox_address:
        return False
    from app.mail.providers import get_adapter

    return get_adapter(settings, conn.provider) is not None


def _from_connection(conn: MailConnection, name: str | None = None) -> Sender:
    return Sender(channel=conn.provider, from_name=name or conn.send_as_name or "Futran Audit Platform", from_address=conn.mailbox_address,
                  reply_to=conn.reply_to or conn.mailbox_address, connection=conn)


def resolve_sender(db: Session, settings: Settings, org_id: str, *, prefer: str = "organization", user_id: str | None = None) -> Sender:
    """Who an email comes from. `prefer`: organization (the client's own mailbox, else Futran on its behalf), futran, or
    me (the sending user's own mailbox). Falls back to the outbox or SMTP when nothing is connected."""
    org = db.get(Organization, org_id)
    if prefer == "me" and user_id:
        uc = db.scalar(select(UserMailConnection).where(UserMailConnection.user_id == user_id, UserMailConnection.status == "connected", UserMailConnection.deleted_at.is_(None)))
        from app.mail.providers import get_adapter

        if uc is not None and uc.mailbox and get_adapter(settings, uc.provider) is not None:
            from app.tenancy.models import User

            u = db.get(User, user_id)
            return Sender(channel=uc.provider, from_name=u.name if u else uc.mailbox, from_address=uc.mailbox, reply_to=uc.mailbox, user_connection=uc)
    if prefer in ("organization", "me") and org is not None and org.type == "client":  # client mail: own mailbox, else Futran for the client
        conn = org_connection(db, org_id)
        if conn is not None and conn.sender_mode == "own" and _usable(settings, conn):
            return _from_connection(conn)
        futran = futran_connection(db)
        if _usable(settings, futran):
            return _from_connection(futran, f"{org.name} via Futran Audit Platform")
        fb = fallback_sender(settings)
        fb.from_name = f"{org.name} via Futran Audit Platform"
        return fb
    futran = futran_connection(db)
    if _usable(settings, futran):
        return _from_connection(futran)
    return fallback_sender(settings)


def record(db: Session, *, organization_id: str, env: Envelope, stored: Envelope | None, template_key: str, related=None, actor_id: str | None = None,
           mail_send_id: str | None = None, channel: str = "outbox") -> OutboxMessage:
    """The outbox row. `stored` is the copy kept readable; with real email it has one-time links redacted."""
    keep = stored or env
    msg = OutboxMessage(organization_id=organization_id, to=list(keep.to), cc=list(keep.cc) or None, bcc=list(keep.bcc) or None, subject=keep.subject[:300], body_html=keep.html,
                        body_text=keep.text, template_key=template_key[:80], related_type=type(related).__name__ if related is not None else None,
                        related_id=getattr(related, "id", None), attachments=[], created_by=actor_id, mail_send_id=mail_send_id, channel=channel)
    db.add(msg)
    return msg


def deliver(db: Session, settings: Settings, sender: Sender, env: Envelope, msg: OutboxMessage) -> Result:
    env.subject = one_line(env.subject)
    if sender.channel == "outbox":
        res = Result(ok=True)
    elif sender.channel == "smtp":
        res = _smtp(settings, sender, env)
    else:
        res = _provider(db, settings, sender, env)
    msg.status = "sent" if res.ok else "failed"
    msg.sent_at = utcnow() if res.ok else None
    msg.error = None if res.ok else (res.error or "Delivery failed.")[:500]
    db.flush()
    return res


def _smtp(settings: Settings, sender: Sender, env: Envelope) -> Result:
    try:  # building the headers can fail on bad input too: recorded on the message, never raised
        em = EmailMessage()
        em["From"] = formataddr((sender.from_name, sender.from_address)) if sender.from_address else settings.smtp_from
        if env.to:
            em["To"] = ", ".join(env.to)
        if env.cc:
            em["Cc"] = ", ".join(env.cc)
        if sender.reply_to:
            em["Reply-To"] = sender.reply_to
        em["Subject"] = env.subject
        em.set_content(env.text)
        em.add_alternative(env.html, subtype="html")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
            if settings.smtp_starttls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password or "")
            if env.bcc:
                s.send_message(em, to_addrs=list(env.to) + list(env.cc) + list(env.bcc))
            else:
                s.send_message(em)
        return Result(ok=True)
    except Exception as exc:  # recorded, never raised
        return Result(ok=False, error=str(exc)[:500])


def _provider(db: Session, settings: Settings, sender: Sender, env: Envelope) -> Result:
    from app.mail import tokens
    from app.mail.providers import OutgoingMessage, ProviderError, get_adapter

    adapter = get_adapter(settings, sender.channel)
    holder = sender.user_connection or sender.connection
    if adapter is None or holder is None:
        return Result(ok=False, error="The mailbox is not connected.")
    try:
        grant = tokens.load(settings, holder)
        out = OutgoingMessage(from_address=sender.from_address, from_name=sender.from_name, reply_to=sender.reply_to, to=env.to, bcc=env.bcc,
                              subject=env.subject, html=env.html, text=env.text, cc=env.cc)
        sent = adapter.send(grant, out)
        tokens.save_if_refreshed(settings, holder, grant)
        return Result(ok=True, provider_message_id=sent.message_id, provider_thread_id=sent.thread_id)
    except ProviderError as exc:
        return Result(ok=False, error=str(exc)[:500])
