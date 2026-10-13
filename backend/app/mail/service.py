import smtplib
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.mail.models import OutboxMessage

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
) -> OutboxMessage:
    """Render and deliver one email. In outbox mode it is only stored (Admin > Outbox)."""
    ctx = {"base_url": settings.base_url, **context}
    subject, html, text = render(template_key, ctx)
    msg = OutboxMessage(
        organization_id=organization_id,
        to=list(to),
        cc=list(cc) if cc else None,
        subject=subject,
        body_html=html,
        body_text=text,
        template_key=template_key,
        related_type=type(related).__name__ if related is not None else None,
        related_id=getattr(related, "id", None),
        attachments=[],
        created_by=actor_id,
    )
    db.add(msg)
    if settings.email_mode == "smtp":
        _deliver_smtp(settings, msg)
    else:
        msg.status = "sent"
        msg.sent_at = utcnow()
    db.flush()
    return msg


def _deliver_smtp(settings: Settings, msg: OutboxMessage) -> None:
    em = EmailMessage()
    em["From"] = settings.smtp_from
    em["To"] = ", ".join(msg.to)
    if msg.cc:
        em["Cc"] = ", ".join(msg.cc)
    em["Subject"] = msg.subject
    em.set_content(msg.body_text)
    em.add_alternative(msg.body_html, subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
            if settings.smtp_starttls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password or "")
            s.send_message(em)
        msg.status = "sent"
        msg.sent_at = utcnow()
    except Exception as exc:  # recorded, never raised: a mail failure must not lose the business action
        msg.status = "failed"
        msg.error = str(exc)[:500]
