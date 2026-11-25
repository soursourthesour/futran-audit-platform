import smtplib  # noqa: F401  (delivery uses it; tests patch app.mail.service.smtplib.SMTP)
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.mail.models import MailRecipient, MailSend, MailThread, OutboxMessage

TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_key: str, context: dict) -> tuple[str, str, str]:
    subject = _env.get_template(f"{template_key}.subject.j2").render(**context).strip()
    html = _env.get_template(f"{template_key}.html.j2").render(**context)
    text = _env.get_template(f"{template_key}.txt.j2").render(**context)
    return subject, html, text


def render_layout(body_html: str) -> str:
    """Wrap already-escaped HTML paragraphs in the standard email layout (group sends)."""
    return _env.get_template("group_message.html.j2").render(body=body_html)


# Emails a client sends to its own people come from the client's mailbox when it has connected one (spec §26.1);
# everything else comes from Futran's.
CLIENT_ORIGIN = {"employee_data_notice", "attestation_sent", "named_user_confirm", "one_time_code"}
SYSTEM_NAMES = {
    "invitation": "Invitation", "client_invitation": "Initiation package", "invitation_expiring": "Invitation expiring", "attestation_sent": "Attestation request (in the app)",
    "employee_data_notice": "Employee data notice", "named_user_confirm": "Named user confirmation", "document_request": "Document request",
    "engagement_submitted": "Engagement awaiting approval", "engagement_returned": "Engagement returned", "notification": "Notification",
    "overdue_digest": "Overdue items digest", "test_message": "Test email", "one_time_code": "One-time code",
}


def send(
    db: Session,
    settings: Settings,
    template_key: str,
    *,
    to: list[str],
    context: dict,
    organization_id: str,
    cc: list[str] | None = None,
    related=None,
    actor_id: str | None = None,
    redact: dict[str, str] | None = None,
) -> OutboxMessage:
    """Render and deliver one email. It is recorded as a MailSend (kind "system") with one MailRecipient per address and
    shown in Admin > Outbox. It goes out through the connected Futran or client mailbox, else SMTP, else (test mode)
    nowhere.

    `redact` names context values (such as one-time links) that are sent to the recipient but never
    stored readable when real email is on, so nobody at Futran can read them back from the outbox.
    """
    from app.mail import adminlog, delivery
    from app.mail.sending import next_subject_ref

    ctx = {"base_url": settings.base_url, **context}
    subject, html, text = render(template_key, ctx)
    stored_parts = None
    if redact and settings.email_mode != "outbox":
        stored_parts = render(template_key, {**ctx, **redact})
    sender = delivery.resolve_sender(db, settings, organization_id, prefer="organization" if template_key in CLIENT_ORIGIN else "futran")
    from app.core.clock import utcnow

    now = utcnow()
    engagement_id = getattr(related, "engagement_id", None) or (related.id if type(related).__name__ == "Engagement" else None)
    ms = MailSend(organization_id=organization_id, engagement_id=engagement_id, kind="system", mode="direct", template_key=template_key,
                  template_name=SYSTEM_NAMES.get(template_key, template_key.replace("_", " ").capitalize()), subject=subject[:300], channel=sender.channel,
                  sender_label=sender.label, sender_connection_id=sender.connection.id if sender.connection else None, recipient_count=len(to) + len(cc or []),
                  groups=None, sent_by=actor_id, related_type=type(related).__name__ if related is not None else None, related_id=getattr(related, "id", None),
                  status="queued", retain_until=adminlog.retain_until(now), created_by=actor_id)
    db.add(ms)
    db.flush()
    if sender.is_provider:  # replies can come back, so the subject carries the thread reference
        ref = next_subject_ref(db)
        db.add(MailThread(organization_id=organization_id, send_id=ms.id, engagement_id=engagement_id, connection_id=ms.sender_connection_id, subject_ref=ref))
        subject = f"{subject} [{ref}]"
        if stored_parts:
            stored_parts = (f"{stored_parts[0]} [{ref}]", stored_parts[1], stored_parts[2])
    env = delivery.Envelope(to=list(to), cc=list(cc or []), subject=subject, html=html, text=text)
    stored = delivery.Envelope(to=list(to), cc=list(cc or []), subject=stored_parts[0], html=stored_parts[1], text=stored_parts[2]) if stored_parts else None
    msg = delivery.record(db, organization_id=organization_id, env=env, stored=stored, template_key=template_key, related=related, actor_id=actor_id,
                          mail_send_id=ms.id, channel=sender.channel)
    res = delivery.deliver(db, settings, sender, env, msg)
    for addr in list(to) + list(cc or []):
        db.add(MailRecipient(organization_id=organization_id, send_id=ms.id, email=addr.lower(), status="sent" if res.ok else "bounced", error=None if res.ok else res.error,
                             provider_message_id=res.provider_message_id, provider_thread_id=res.provider_thread_id, last_event_at=now, attempts=1))
    ms.status, ms.sent_at = "sent", now
    if actor_id:
        from app.tenancy.models import User

        u = db.get(User, actor_id)
        ms.sent_by_name = u.name if u else None
    adminlog.write(db, organization_id=organization_id, category="send", action="system_send", actor_name=ms.sent_by_name or "System", engagement_id=engagement_id, send_id=ms.id,
                   summary=f"{ms.template_name} to {', '.join(to)[:300]}" + ("" if res.ok else " (not delivered)"))
    db.flush()
    return msg


# ---- one system email to many people, delivered outside the request (load test BUG-V01, gap G1)
BULK_TICK = 500  # most messages the mail tick sends for one bulk send when it resumes one (after a restart, or retries)


def queue_bulk(db: Session, settings: Settings, template_key: str, *, recipients: list[dict], context: dict, organization_id: str, related=None,
               actor_id: str | None = None) -> MailSend:
    """Queue one system email to many people: one MailSend (kind "system") with a queued MailRecipient per person, each
    with their own merge values (`recipients`: [{"email", "name", "context"}]), and one thread reference for replies.
    Nothing is sent here: `deliver_in_background` sends it after the response, committing after each message, and the
    mail tick finishes whatever a restart left queued. Returns the MailSend."""
    from app.core.clock import utcnow
    from app.mail import adminlog, delivery
    from app.mail.sending import next_subject_ref

    now = utcnow()
    sender = delivery.resolve_sender(db, settings, organization_id, prefer="organization" if template_key in CLIENT_ORIGIN else "futran")
    first = recipients[0] if recipients else {"context": {}}
    subject = render(template_key, {"base_url": settings.base_url, **context, **(first.get("context") or {})})[0]
    engagement_id = getattr(related, "engagement_id", None) or (related.id if type(related).__name__ == "Engagement" else None)
    sent_by_name = None
    if actor_id:
        from app.tenancy.models import User

        u = db.get(User, actor_id)
        sent_by_name = u.name if u else None
    name = SYSTEM_NAMES.get(template_key, template_key.replace("_", " ").capitalize())
    ms = MailSend(organization_id=organization_id, engagement_id=engagement_id, kind="system", mode="direct", template_key=template_key, template_name=name,
                  subject=subject[:300], channel=sender.channel, sender_label=sender.label, sender_connection_id=sender.connection.id if sender.connection else None,
                  recipient_count=len(recipients), groups=None, sent_by=actor_id, sent_by_name=sent_by_name, context=context,
                  related_type=type(related).__name__ if related is not None else None, related_id=getattr(related, "id", None),
                  status="queued", retain_until=adminlog.retain_until(now), created_by=actor_id)
    db.add(ms)
    db.flush()
    if sender.is_provider:  # replies can come back, so the subject carries the thread reference
        db.add(MailThread(organization_id=organization_id, send_id=ms.id, engagement_id=engagement_id, connection_id=ms.sender_connection_id, subject_ref=next_subject_ref(db)))
    db.add_all([MailRecipient(organization_id=organization_id, send_id=ms.id, email=r["email"].strip().lower(), name=r.get("name"), context=r.get("context") or None,
                              status="queued", attempts=0) for r in recipients])
    adminlog.write(db, organization_id=organization_id, category="send", action="system_send", actor_name=sent_by_name or "System", engagement_id=engagement_id, send_id=ms.id,
                   summary=f"{name} to {len(recipients):,} {'person' if len(recipients) == 1 else 'people'}")
    db.flush()
    return ms


def dispatch_bulk(db: Session, settings: Settings, ms: MailSend, now=None, limit: int | None = None, after_each=None) -> int:
    """Send the due queued recipients of a bulk system send (at most `limit`). Each recipient is claimed before the
    provider is called, so two runs never send the same message; `after_each` (a commit) runs after every message, so a
    restart resumes from where delivery stopped. Failures are retried as for group sends. Returns the number sent."""
    from sqlalchemy import select

    from app.core.clock import utcnow
    from app.mail import delivery
    from app.mail.sending import _apply, _claim, _finish

    now = now or utcnow()
    sender = delivery.resolve_sender(db, settings, ms.organization_id, prefer="organization" if ms.template_key in CLIENT_ORIGIN else "futran")
    ref = db.scalar(select(MailThread.subject_ref).where(MailThread.send_id == ms.id).limit(1))
    stmt = select(MailRecipient).where(MailRecipient.send_id == ms.id, MailRecipient.status == "queued",
                                       (MailRecipient.next_attempt_at.is_(None)) | (MailRecipient.next_attempt_at <= now)).order_by(MailRecipient.name, MailRecipient.email)
    if limit is not None:
        stmt = stmt.limit(limit)
    sent = 0
    rows = list(db.scalars(stmt))
    if rows and ms.status == "queued":
        ms.status = "sending"
    for r in rows:
        if not _claim(db, r):
            continue
        subject, html, text = render(ms.template_key, {"base_url": settings.base_url, **(ms.context or {}), **(r.context or {})})
        if ref:
            subject = f"{subject} [{ref}]"
        env = delivery.Envelope(to=[r.email], subject=subject, html=html, text=text)
        msg = delivery.record(db, organization_id=ms.organization_id, env=env, stored=None, template_key=ms.template_key, actor_id=ms.sent_by, mail_send_id=ms.id,
                              channel=sender.channel)
        msg.related_type, msg.related_id = ms.related_type, ms.related_id
        res = delivery.deliver(db, settings, sender, env, msg)
        _apply(r, res, now)
        r.attempts = max(r.attempts or 0, 1) if res.ok else r.attempts
        sent += 1
        if after_each is not None:
            after_each()
    _finish(db, ms, now)
    return sent


def deliver_in_background(app, send_id: str, chunk: int = 500) -> None:
    """Run after the response (FastAPI background task) with its own session: send every due recipient of the bulk
    send, committing after each message. If the process stops part way, the mail tick resumes from the next queued
    recipient; nobody already sent is sent again."""
    import logging

    db = app.state.sessionmaker()
    try:
        while True:
            ms = db.get(MailSend, send_id)
            if ms is None or ms.status not in ("queued", "sending"):
                return
            n = dispatch_bulk(db, app.state.settings, ms, limit=chunk, after_each=db.commit)
            db.commit()
            if not n:
                return
    except Exception:  # noqa: BLE001 (logged; the mail tick retries what is still queued)
        db.rollback()
        logging.getLogger(__name__).exception("Bulk email %s stopped; the mail tick sends the rest", send_id)
    finally:
        db.close()
