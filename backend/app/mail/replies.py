"""Reply sync (spec §26.2, §27.1): read back only the threads the platform started, and only messages whose subject
carries the send's reference ([FAP-1042]). Replies are attached to the engagement's activity; out-of-office replies
are marked; bounces set the recipient to bounced. Nothing else in the mailbox is read."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.config import Settings
from app.mail import tokens
from app.mail.models import MailConnection, MailRecipient, MailReply, MailSend, MailThread, UserMailConnection
from app.mail.providers import IncomingMessage, ProviderError, get_adapter

LOOKBACK_DAYS = 60
BOUNCE_SENDERS = ("mailer-daemon@", "postmaster@", "microsoftexchange")
BOUNCE_SUBJECTS = ("undeliverable", "delivery status notification", "mail delivery failed", "returned mail", "delivery has failed", "message not delivered")
OOO_SUBJECTS = ("automatic reply", "auto reply", "autoreply", "out of office", "out of the office")


def classify(m: IncomingMessage) -> str:
    subj = (m.subject or "").strip().lower()
    if m.from_address.startswith(BOUNCE_SENDERS) or any(subj.startswith(b) for b in BOUNCE_SUBJECTS):
        return "bounce"
    if m.auto_reply or any(subj.startswith(o) for o in OOO_SUBJECTS):
        return "out_of_office"
    return "reply"


def _holder(db: Session, s: MailSend):
    if s.sender_user_id:
        uc = db.scalar(select(UserMailConnection).where(UserMailConnection.user_id == s.sender_user_id, UserMailConnection.status == "connected"))
        return uc, (uc.mailbox if uc else None), (uc.provider if uc else None)
    c = db.get(MailConnection, s.sender_connection_id) if s.sender_connection_id else None
    if c is None or c.status != "connected":
        return None, None, None
    return c, c.mailbox_address, c.provider


def run_reply_sync(db: Session, settings: Settings, now: datetime | None = None) -> int:
    """Store new replies on platform threads; returns how many were stored."""
    now = now or utcnow()
    stored = 0
    sends = db.scalars(select(MailSend).where(MailSend.channel.in_(["microsoft365", "google"]), MailSend.created_at >= now - timedelta(days=LOOKBACK_DAYS)))
    for s in list(sends):
        holder, mailbox, provider = _holder(db, s)
        adapter = get_adapter(settings, provider)
        thread = db.scalar(select(MailThread).where(MailThread.send_id == s.id).limit(1))
        if holder is None or adapter is None or thread is None:
            continue
        marker = f"[{thread.subject_ref}]".lower()
        recipients: dict[str, list[MailRecipient]] = {}
        for r in db.scalars(select(MailRecipient).where(MailRecipient.send_id == s.id, MailRecipient.provider_thread_id.is_not(None))):
            recipients.setdefault(r.provider_thread_id, []).append(r)
        try:
            grant = tokens.load(settings, holder)
            for thread_id, rows in recipients.items():
                for m in adapter.thread_messages(grant, mailbox, thread_id):
                    kind = classify(m)
                    if marker not in (m.subject or "").lower():
                        continue  # not a reply to the platform's message
                    if db.scalar(select(MailReply.id).where(MailReply.thread_id == thread.id, MailReply.provider_message_id == m.message_id)):
                        continue
                    r = next((x for x in rows if x.email.lower() == m.from_address), rows[0] if len(rows) == 1 else None)
                    db.add(MailReply(organization_id=s.organization_id, thread_id=thread.id, recipient_id=r.id if r else None, provider_message_id=m.message_id,
                                     from_address=m.from_address, received_at=m.received_at, subject=(m.subject or "")[:300], snippet=m.snippet[:500], attachment_ids=[],
                                     kind=kind, linked_entity=f"engagement:{s.engagement_id}" if s.engagement_id else None))
                    stored += 1
                    if kind == "bounce" and r is not None:
                        r.status, r.error, r.last_event_at = "bounced", f"Bounced: {m.snippet[:200]}", now
                    elif kind == "out_of_office" and r is not None:
                        r.out_of_office, r.last_event_at = True, now
                    elif kind == "reply":
                        thread.last_reply_at = max(thread.last_reply_at or m.received_at, m.received_at)
                        audit.record(db, actor_id=None, actor_name=m.from_address, action="mail.reply", organization_id=s.organization_id, object_type="MailThread",
                                     object_id=thread.id, engagement_id=s.engagement_id, summary=f"Reply to “{(s.template_name or s.subject or 'an email')[:80]}” from {m.from_address}")
            tokens.save_if_refreshed(settings, holder, grant)
            holder.last_sync_at = now
        except (ProviderError, tokens.TokenError):
            continue  # tried again at the next sync
    db.flush()
    return stored
