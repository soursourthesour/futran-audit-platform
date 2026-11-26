"""No-login links (spec §26.5).

Personal link: a random 256-bit token, stored only as its SHA-256 hash, bound to one recipient (one person in one
send), expiring (default 14 days). Sending again to the same person for the same campaign replaces the old link.

Shared (BCC) link: one per send. Before answering, the person types their work email; it must be one of that send's
recipients, and an 8-digit code (10 minutes, 5 tries, 3 codes per 10 minutes per address) is sent to it. Any address
gets the same answers, in the same time (the code email goes out after the response), so the page doesn't reveal who
was sent the message. Wrong codes are capped per link and network address, with a much higher backstop for the whole
link that tells the sender when it trips (review 11-25 H09 and its review).
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import AppError, Invalid, NotFound
from app.core.ratelimit import TooManyRequests
from app.mail.models import MailOneTimeCode, MailRecipient, MailSend
from app.mail.sending import token_hash

CODE_MINUTES = 10
CODE_TRIES = 5
CODES_PER_WINDOW = 3
CODE_DIGITS = 8
IP_WRONG_PER_HOUR = 50  # wrong codes on one shared link from one network address before that address pauses for an hour
LINK_WRONG_PER_HOUR = 1000  # backstop for the whole link, across every address; the sender is told when it trips
MAX_EMAIL = 254
PROOF_MINUTES = 60

# (send id, address) -> times a code was asked for an address that was not sent the message. In memory, like the
# other rate limits (the platform runs as one process), so a stranger meets the same limit as a recipient.
_STRANGERS: dict[tuple[str, str], list] = {}
# (send id, network address) -> times of wrong codes in the last hour
_WRONG_BY_IP: dict[tuple[str, str], list] = {}


def _work_email(email: str | None) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > MAX_EMAIL:
        raise Invalid(errors=[{"field": "email", "message": "Enter your work email."}])
    return email


def _recent(store: dict, key, since) -> list:
    for k in [k for k, v in store.items() if not v or v[-1] <= since]:
        store.pop(k, None)
    return [t for t in store.get(key, []) if t > since]


class Gone(AppError):
    status_code = 410


def _personal(db: Session, raw: str) -> MailRecipient:
    r = db.scalar(select(MailRecipient).where(MailRecipient.link_token_hash == token_hash(raw or "")).limit(1)) if raw else None
    if r is None:
        raise NotFound("This link is not valid. Use the link in your most recent email.")
    if r.link_revoked_at is not None:
        raise Gone("This link has been replaced by a newer one. Use the link in your most recent email.")
    if r.link_expires_at is None or r.link_expires_at <= utcnow():
        raise Gone("This link has expired. Ask the sender for a new one.")
    return r


def mark_opened(db: Session, r: MailRecipient) -> None:
    """"Opened" means the link was opened; there are no tracking pixels."""
    now = utcnow()
    if r.status in ("queued", "sent", "delivered"):
        r.status = "opened"
    r.opened_at = r.opened_at or now
    r.last_event_at = now


def mark_completed(db: Session, r: MailRecipient) -> None:
    now = utcnow()
    r.status, r.completed_at, r.last_event_at = "completed", r.completed_at or now, now
    r.opened_at = r.opened_at or now
    s = db.get(MailSend, r.send_id)
    root = s.parent_send_id or s.id if s else None
    if root:  # the original send and its reminders count as one
        for other in db.scalars(select(MailRecipient).join(MailSend, MailSend.id == MailRecipient.send_id).where(
                (MailSend.id == root) | (MailSend.parent_send_id == root), func.lower(MailRecipient.email) == r.email.lower(), MailRecipient.id != r.id)):
            if other.status != "bounced":
                other.status, other.completed_at = "completed", other.completed_at or now
    db.flush()


def open_personal(db: Session, raw: str) -> tuple[MailRecipient, MailSend]:
    r = _personal(db, raw)
    mark_opened(db, r)
    db.flush()
    return r, db.get(MailSend, r.send_id)


def personal(db: Session, raw: str) -> tuple[MailRecipient, MailSend]:
    """Resolve without marking it opened (for the submit call)."""
    r = _personal(db, raw)
    return r, db.get(MailSend, r.send_id)


# ---- shared links
def shared_send(db: Session, raw: str) -> MailSend:
    s = db.scalar(select(MailSend).where(MailSend.shared_token_hash == token_hash(raw or "")).limit(1)) if raw else None
    if s is None:
        raise NotFound("This link is not valid.")
    if s.shared_link_expires_at is None or s.shared_link_expires_at <= utcnow():
        raise Gone("This link has expired. Ask the sender for a new one.")
    return s


def _code_hash(send_id: str, email: str, code: str) -> str:
    return hashlib.sha256(f"{send_id}:{email}:{code}".encode()).hexdigest()


def _recipient(db: Session, s: MailSend, email: str) -> MailRecipient | None:
    return db.scalar(select(MailRecipient).where(MailRecipient.send_id == s.id, func.lower(MailRecipient.email) == email).limit(1))


def _too_many(count: int) -> None:
    if count >= CODES_PER_WINDOW:
        raise TooManyRequests("Too many codes asked for. Wait ten minutes and try again.")


def request_code(db: Session, settings: Settings, raw: str, email: str, *, send: bool = True) -> str | None:
    """Make a code if the address was sent this message, and email it (send=False leaves the email to
    send_code_email, which the public route runs after the response). The caller answers the same way either way;
    None means no code was made."""
    s = shared_send(db, raw)
    email = _work_email(email)
    now = utcnow()
    r = _recipient(db, s, email)
    if r is None:
        times = _recent(_STRANGERS, (s.id, email), now - timedelta(minutes=CODE_MINUTES))
        _too_many(len(times))
        _STRANGERS[(s.id, email)] = [*times, now]
        return None
    recent = db.scalar(select(func.count(MailOneTimeCode.id)).where(MailOneTimeCode.send_id == s.id, MailOneTimeCode.email == email,
                                                                     MailOneTimeCode.created_at > now - timedelta(minutes=CODE_MINUTES)))
    _too_many(recent)
    code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
    db.add(MailOneTimeCode(organization_id=s.organization_id, send_id=s.id, recipient_id=r.id, email=email, code_hash=_code_hash(s.id, email, code),
                           expires_at=now + timedelta(minutes=CODE_MINUTES), attempts=0, created_at=now))
    db.flush()
    if send:
        send_code_email(db, settings, s.id, email, code)
    return code


def send_code_email(db: Session, settings: Settings, send_id: str, email: str, code: str) -> None:
    from app.mail.service import send as send_mail
    from app.tenancy.models import Organization

    s = db.get(MailSend, send_id)
    org = db.get(Organization, s.organization_id)
    send_mail(db, settings, "one_time_code", to=[email], organization_id=s.organization_id, context={"code": code, "organization": org.name if org else "", "minutes": CODE_MINUTES},
              redact={"code": "(code sent to the recipient, not stored)"})
    db.flush()


def send_code_in_background(app, send_id: str, email: str, code: str) -> None:
    """Run after the response (FastAPI background task) with its own session, so a recipient's answer takes as long
    as a stranger's."""
    import logging

    db = app.state.sessionmaker()
    try:
        send_code_email(db, app.state.settings, send_id, email, code)
        db.commit()
    except Exception:  # noqa: BLE001 (logged; the person can ask for a new code)
        db.rollback()
        logging.getLogger(__name__).exception("One-time code email for send %s failed", send_id)
    finally:
        db.close()


def _paused(message: str):
    return TooManyRequests(message)


def verify_code(db: Session, raw: str, email: str, code: str, *, ip: str | None = None) -> str:
    """Check the code and return a short-lived proof the answer form sends back. A wrong code counts as a try; the
    caller commits before re-raising so the count is kept."""
    s = shared_send(db, raw)
    email = _work_email(email)
    now = utcnow()
    ip_key = (s.id, ip or "unknown")
    ip_wrong = _recent(_WRONG_BY_IP, ip_key, now - timedelta(hours=1))
    if len(ip_wrong) >= IP_WRONG_PER_HOUR:
        raise _paused("Too many wrong codes have been tried from your network. Try again in an hour.")
    row = db.scalar(select(MailOneTimeCode).where(MailOneTimeCode.send_id == s.id, MailOneTimeCode.email == email, MailOneTimeCode.used_at.is_(None))
                    .order_by(MailOneTimeCode.created_at.desc()).limit(1))
    wrong_recently = db.scalar(select(func.coalesce(func.sum(MailOneTimeCode.attempts), 0)).where(
        MailOneTimeCode.send_id == s.id, MailOneTimeCode.created_at > now - timedelta(minutes=60 + CODE_MINUTES)))
    if wrong_recently >= LINK_WRONG_PER_HOUR:
        raise _paused("Too many wrong codes have been tried on this link. Try again in an hour.")
    bad = Invalid(errors=[{"field": "code", "message": "That code is not right, or it has expired. Check the latest email or ask for a new code."}])

    def wrong():
        _WRONG_BY_IP[ip_key] = [*ip_wrong, now]
        return bad

    if row is None or row.expires_at <= now or row.attempts >= CODE_TRIES:  # one answer, so a used-up code reads like no code
        raise wrong()
    if not hmac.compare_digest(row.code_hash, _code_hash(s.id, email, (code or "").strip())):
        row.attempts += 1
        db.flush()
        if wrong_recently + 1 == LINK_WRONG_PER_HOUR:
            from app.mail import adminlog

            adminlog.write(db, organization_id=s.organization_id, category="send", action="shared_link_paused", actor_name="System", send_id=s.id,
                           engagement_id=s.engagement_id,
                           summary=f"The shared link for \"{s.subject}\" was paused for an hour after {LINK_WRONG_PER_HOUR:,} wrong codes. Recipients with the code can try again after that.")
        raise wrong()
    proof = secrets.token_urlsafe(32)
    row.used_at, row.proof_hash, row.proof_expires_at = now, token_hash(proof), now + timedelta(minutes=PROOF_MINUTES)
    r = db.get(MailRecipient, row.recipient_id)
    mark_opened(db, r)
    db.flush()
    return proof


def recipient_for_proof(db: Session, raw: str, proof: str) -> MailRecipient:
    s = shared_send(db, raw)
    row = db.scalar(select(MailOneTimeCode).where(MailOneTimeCode.send_id == s.id, MailOneTimeCode.proof_hash == token_hash(proof or "")).limit(1)) if proof else None
    if row is None or row.proof_expires_at is None or row.proof_expires_at <= utcnow():
        raise Invalid(errors=[{"field": "code", "message": "Confirm your work email again before submitting."}])
    return db.get(MailRecipient, row.recipient_id)
