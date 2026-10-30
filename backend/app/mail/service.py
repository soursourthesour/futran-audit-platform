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
