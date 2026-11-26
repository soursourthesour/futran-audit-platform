"""No-login links (spec §26.5).

Personal link: a random 256-bit token, stored only as its SHA-256 hash, bound to one recipient (one person in one
send), expiring (default 14 days). Sending again to the same person for the same campaign replaces the old link.

Shared (BCC) link: one per send. Before answering, the person types their work email; it must be one of that send's
recipients, and an 8-digit code (10 minutes, 5 tries, 3 codes per 10 minutes per address) is sent to it. Any address
gets the same answer, so the page doesn't reveal who was sent the message, and the link as a whole stops taking codes
after LINK_WRONG_PER_HOUR wrong ones (review 11-25 H09).
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
LINK_WRONG_PER_HOUR = 50  # wrong codes on one shared link, across every recipient, before it pauses for an hour
PROOF_MINUTES = 60

# (send id, address) -> times a code was asked for an address that was not sent the message. In memory, like the
# other rate limits (the platform runs as one process), so a stranger meets the same limit as a recipient.
_STRANGERS: dict[tuple[str, str], list] = {}


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


def request_code(db: Session, settings: Settings, raw: str, email: str) -> str | None:
    """Send a code if the address was sent this message. The caller answers the same way either way; None means no
    code was sent."""
    s = shared_send(db, raw)
    email = (email or "").strip().lower()
    if "@" not in email:
        raise Invalid(errors=[{"field": "email", "message": "Enter your work email."}])
    now = utcnow()
    r = _recipient(db, s, email)
    if r is None:
        since = now - timedelta(minutes=CODE_MINUTES)
        for k in [k for k, v in _STRANGERS.items() if not v or v[-1] <= since]:
            _STRANGERS.pop(k, None)
        times = [t for t in _STRANGERS.get((s.id, email), []) if t > since]
        _too_many(len(times))
        _STRANGERS[(s.id, email)] = [*times, now]
        return None
    recent = db.scalar(select(func.count(MailOneTimeCode.id)).where(MailOneTimeCode.send_id == s.id, MailOneTimeCode.email == email,
                                                                     MailOneTimeCode.created_at > now - timedelta(minutes=CODE_MINUTES)))
    _too_many(recent)
    code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
    db.add(MailOneTimeCode(organization_id=s.organization_id, send_id=s.id, recipient_id=r.id, email=email, code_hash=_code_hash(s.id, email, code),
                           expires_at=now + timedelta(minutes=CODE_MINUTES), attempts=0, created_at=now))
    from app.mail.service import send as send_mail
    from app.tenancy.models import Organization

    org = db.get(Organization, s.organization_id)
    send_mail(db, settings, "one_time_code", to=[email], organization_id=s.organization_id, context={"code": code, "organization": org.name if org else "", "minutes": CODE_MINUTES},
              redact={"code": "(code sent to the recipient, not stored)"})
    db.flush()
    return code


def verify_code(db: Session, raw: str, email: str, code: str) -> str:
    """Check the code and return a short-lived proof the answer form sends back. A wrong code counts as a try; the
    caller commits before re-raising so the count is kept."""
    s = shared_send(db, raw)
    email = (email or "").strip().lower()
    now = utcnow()
    row = db.scalar(select(MailOneTimeCode).where(MailOneTimeCode.send_id == s.id, MailOneTimeCode.email == email, MailOneTimeCode.used_at.is_(None))
                    .order_by(MailOneTimeCode.created_at.desc()).limit(1))
    wrong_recently = db.scalar(select(func.coalesce(func.sum(MailOneTimeCode.attempts), 0)).where(
        MailOneTimeCode.send_id == s.id, MailOneTimeCode.created_at > now - timedelta(minutes=60 + CODE_MINUTES)))
    if wrong_recently >= LINK_WRONG_PER_HOUR:
        raise TooManyRequests("This link has had too many wrong codes. Try again in an hour, or use a personal link if you have one.")
    bad = Invalid(errors=[{"field": "code", "message": "That code is not right, or it has expired. Check the latest email or ask for a new code."}])
    if row is None or row.expires_at <= now:
        raise bad
    if row.attempts >= CODE_TRIES:
        raise Invalid(errors=[{"field": "code", "message": "Too many wrong codes. Ask for a new code."}])
    if not hmac.compare_digest(row.code_hash, _code_hash(s.id, email, (code or "").strip())):
        row.attempts += 1
        db.flush()
        raise bad
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
