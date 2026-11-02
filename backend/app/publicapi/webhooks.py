"""Webhooks (spec §21 F17): events, signed deliveries, retries with backoff and the delivery log.

Signature: every delivery carries `X-Futran-Timestamp: <unix seconds>` and `X-Futran-Signature: t=<timestamp>,v1=<hex>`,
where hex = HMAC-SHA256(signing secret, "<timestamp>." + raw body). The receiver recomputes it and rejects old timestamps.

Events are found by a scan that runs every minute with the email tick: sign-offs completed since the hook was added,
remediation items past their due date, and regulatory updates published to the client. Each event goes to a hook once
(`event_key` is unique per hook). A failed delivery is tried again after 1 minute, 5 minutes, 30 minutes, 2 hours and
12 hours, then marked failed. The target is checked again before every attempt (app.publicapi.netguard), the connection
goes to the address that passed the check, redirects are not followed, and the request times out after 10 seconds. The
delivery log keeps a plain reason for a failure (could not connect, timed out, the receiver's status class), never the
exception text.

WEBHOOK_MODE: auto (the in-process fake while the platform is in test mode, else live), fake or live. The fake records the
delivery as sent and never touches the network.
"""
import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.publicapi import netguard
from app.publicapi.models import EVENTS, Webhook, WebhookDelivery

log = logging.getLogger(__name__)
BACKOFF = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2), timedelta(hours=12)]
MAX_ATTEMPTS = len(BACKOFF) + 1
TIMEOUT = 10.0
USER_AGENT = "FutranAuditPlatform-Webhooks/1"

Sender = Callable[[str, bytes, dict, float], int]


TEST_SENDS_PER_MINUTE = 5  # per webhook, from the admin screen


def http_sender(url: str, body: bytes, headers: dict, timeout: float) -> int:
    """Check the target again and connect to the address that passed the check. The name is not resolved a second time,
    so it cannot be switched to an internal address in between (DNS rebinding). The request still carries the host name
    (Host header and TLS server name), and the certificate is verified for that name. Environment proxies are not used."""
    from urllib.parse import urlsplit, urlunsplit

    import httpx

    host, addrs = netguard.vet(url)
    if not addrs:
        raise netguard.Unresolvable("The host name could not be found.")
    parts = urlsplit(url.strip())
    ip = addrs[0]
    netloc = (f"[{ip}]" if ":" in ip else ip) + (f":{parts.port}" if parts.port else "")
    pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    host_header = (f"[{host}]" if ":" in host else host) + (f":{parts.port}" if parts.port not in (None, 443) else "")
    with httpx.Client(follow_redirects=False, timeout=timeout, trust_env=False) as c:
        return c.post(pinned, content=body, headers={**headers, "Host": host_header}, extensions={"sni_hostname": host}).status_code


def fake_sender(url: str, body: bytes, headers: dict, timeout: float) -> int:
    return 200


def mode(settings) -> str:
    m = getattr(settings, "webhook_mode", "auto")
    if m in ("fake", "live"):
        return m
    return "fake" if settings.test_mode else "live"


def sender_for(settings, override: Sender | None = None) -> Sender:
    if override is not None:
        return override
    return fake_sender if mode(settings) == "fake" else http_sender


# ---------------------------------------------------------------- secrets and signatures
def seal_secret(settings, secret: str) -> tuple[str, str]:
    from app.mail.tokens import seal

    ref, enc = seal(settings, secret)
    return ref, enc


def open_secret(settings, hook: Webhook) -> str:
    from app.mail.tokens import unseal

    return unseal(settings, hook.secret_encrypted)


def signature(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- events
def envelope(event: str, event_key: str, data: dict, at: datetime | None = None) -> dict:
    return {"id": "evt_" + hashlib.sha256(event_key.encode()).hexdigest()[:24], "event": event, "created_at": (at or utcnow()).isoformat() + "Z", "data": data}


def enqueue(db: Session, org_id: str, event: str, data: dict, *, event_key: str, hooks: list[Webhook] | None = None, at: datetime | None = None) -> list[WebhookDelivery]:
    """One delivery per active hook of `org_id` that takes `event` ("ping" goes only to the hooks given)."""
    if event not in EVENTS and event != "ping":
        raise ValueError(event)
    if hooks is None:
        hooks = [h for h in db.scalars(select(Webhook).where(Webhook.organization_id == org_id, Webhook.deleted_at.is_(None), Webhook.status == "active")) if event in (h.events or [])]
    out = []
    for h in hooks:
        if h.organization_id != org_id:
            continue
        if db.scalar(select(WebhookDelivery.id).where(WebhookDelivery.webhook_id == h.id, WebhookDelivery.event_key == event_key)):
            continue
        d = WebhookDelivery(organization_id=org_id, webhook_id=h.id, event=event, event_key=event_key[:120], payload=envelope(event, event_key, data, at), status="pending",
                            next_attempt_at=utcnow(), created_at=utcnow())
        db.add(d)  # the scheduler runs one tick at a time (max_instances=1); the unique key backs that up
        out.append(d)
    db.flush()
    return out


def _hooks_for(db: Session, event: str) -> list[Webhook]:
    return [h for h in db.scalars(select(Webhook).where(Webhook.deleted_at.is_(None), Webhook.status == "active")) if event in (h.events or [])]


def scan_signoffs(db: Session) -> int:
    from app.engagements.models import Engagement
    from app.signoffs.models import SignOff

    n = 0
    for h in _hooks_for(db, "signoff.completed"):
        rows = db.scalars(select(SignOff).where(SignOff.organization_id == h.organization_id, SignOff.status == "approved", SignOff.approved_at.is_not(None),
                                                SignOff.approved_at >= h.created_at, SignOff.deleted_at.is_(None)))
        for so in rows:
            e = db.get(Engagement, so.engagement_id)
            if e is None or e.client_id != h.organization_id:
                continue
            data = {"engagement": e.audit_ref, "sign_off": so.number, "title": so.title, "version": so.version, "completed_at": so.approved_at.isoformat() + "Z"}
            n += len(enqueue(db, h.organization_id, "signoff.completed", data, event_key=f"signoff.completed:{so.id}", hooks=[h], at=so.approved_at))
    return n


def scan_overdue(db: Session, today: date) -> int:
    from app.engagements.models import Engagement
    from app.findings.models import Finding
    from app.remediation.models import RemediationItem

    n = 0
    for h in _hooks_for(db, "remediation.overdue"):
        rows = db.scalars(select(RemediationItem).where(RemediationItem.organization_id == h.organization_id, RemediationItem.deleted_at.is_(None),
                                                        RemediationItem.due_date < today, RemediationItem.status.in_(("open", "in_progress", "reopened"))))
        for it in rows:
            e = db.get(Engagement, it.engagement_id)
            f = db.get(Finding, it.finding_id) if it.finding_id else None
            if e is None or e.client_id != h.organization_id or e.stage < 7 or (f is not None and f.status != "approved"):
                continue  # only what the client already sees
            data = {"id": it.id, "engagement": e.audit_ref, "finding_ref": f.ref if f else None, "action": it.action, "due_date": it.due_date.isoformat(), "status": it.status}
            n += len(enqueue(db, h.organization_id, "remediation.overdue", data, event_key=f"remediation.overdue:{it.id}:{it.due_date.isoformat()}", hooks=[h]))
    return n


def scan_updates(db: Session) -> int:
    from app.publicapi.updates import published_updates

    n = 0
    for h in _hooks_for(db, "regulatory_update.published"):
        for u in published_updates(db, h.organization_id):
            at = u.get("published_at_dt")
            if at is None or at < h.created_at:
                continue
            data = {k: v for k, v in u.items() if not k.endswith("_dt")}
            n += len(enqueue(db, h.organization_id, "regulatory_update.published", data, event_key=f"regulatory_update.published:{u['id']}", hooks=[h], at=at))
    return n


def run_event_scan(db: Session, settings, now: datetime) -> int:
    return scan_signoffs(db) + scan_overdue(db, now.date()) + scan_updates(db)


# ---------------------------------------------------------------- delivery
# A delivery goes in three steps so no write transaction is open while a receiver answers (SQLite allows one writer at a
# time; a 10-second send inside a transaction would stop every other request from saving): claim it and work out what to
# send, commit; send with no transaction open; record the result in a short transaction of its own.
CLAIM = timedelta(minutes=2)  # a claimed delivery whose result was never recorded (the process stopped) is tried again after this


@dataclass
class Outgoing:
    delivery_id: str
    url: str
    body: bytes
    headers: dict


def claim(db: Session, settings, d: WebhookDelivery, now: datetime) -> Outgoing | None:
    """Count the attempt and prepare the request. None when the delivery is settled without sending (hook paused or
    removed, target blocked)."""
    h = db.get(Webhook, d.webhook_id)
    d.attempts += 1
    d.last_attempt_at = now
    d.last_status_code, d.last_error = None, None
    if h is None or h.deleted_at is not None or h.status != "active":
        d.status, d.last_error, d.next_attempt_at = "failed", "The webhook was paused or removed.", None
        return None
    try:
        netguard.check_url(h.url, offline=mode(settings) == "fake")
    except netguard.Unsafe as exc:
        d.status, d.last_error, d.next_attempt_at = "blocked", f"Not sent: {exc} (private or unknown address)"[:500], None
        return None
    body = json.dumps(d.payload, separators=(",", ":"), sort_keys=True).encode()
    ts = str(int(now.replace(tzinfo=timezone.utc).timestamp()))  # `now` is naive UTC; .timestamp() alone would read it as local time
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT, "X-Futran-Event": d.event, "X-Futran-Delivery": d.id,
               "X-Futran-Timestamp": ts, "X-Futran-Signature": f"t={ts},v1={signature(open_secret(settings, h), ts, body)}"}
    d.next_attempt_at = now + CLAIM
    return Outgoing(d.id, h.url, body, headers)


def send(out: Outgoing, sender: Sender) -> tuple[int | None, Exception | None]:
    """The HTTP call. Run it with no database transaction open."""
    try:
        return sender(out.url, out.body, out.headers, TIMEOUT), None
    except Exception as exc:  # network errors, timeouts, the sender's own address check
        return None, exc


def record(db: Session, d: WebhookDelivery, now: datetime, code: int | None, exc: Exception | None) -> WebhookDelivery:
    if isinstance(exc, netguard.Unsafe):  # the sender's own check, just before it connects
        d.status, d.last_error, d.next_attempt_at = "blocked", f"Not sent: {exc} (private or unknown address)"[:500], None
        return d
    if exc is not None:  # the server log keeps the detail, the delivery log a plain reason
        ok = False
        d.last_error = error_reason(exc)
        log.info("Webhook delivery %s failed: %r", d.id, exc)
    else:
        d.last_status_code = code
        ok = 200 <= code < 300
        if not ok:
            d.last_error = status_reason(code)
    h = db.get(Webhook, d.webhook_id)
    if h is not None:
        h.last_delivery_at = now
    if ok:
        d.status, d.delivered_at, d.next_attempt_at = "delivered", now, None
    elif d.attempts >= MAX_ATTEMPTS:
        d.status, d.next_attempt_at = "failed", None
    else:
        d.status, d.next_attempt_at = "retrying", now + BACKOFF[d.attempts - 1]
    return d


def status_reason(code: int) -> str:
    if 300 <= code < 400:
        return "Receiver returned a redirect. Redirects are not followed."
    if 400 <= code < 500:
        return "Receiver returned 4xx."
    if code >= 500:
        return "Receiver returned 5xx."
    return "Receiver returned an unexpected status."


def error_reason(exc: Exception) -> str:
    """A plain reason for the delivery log; never the exception text, which can name internal addresses."""
    import httpx

    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "Timed out."
    return "Could not connect."


def deliver_due(db: Session, settings, now: datetime, sender: Sender | None = None, limit: int = 100) -> int:
    """Send what is due. Commits: the claims first, then each result on its own, with no transaction open during a send."""
    sender = sender_for(settings, sender)
    rows = list(db.scalars(select(WebhookDelivery).where(WebhookDelivery.status.in_(("pending", "retrying")), WebhookDelivery.next_attempt_at <= now)
                           .order_by(WebhookDelivery.next_attempt_at).limit(limit)))
    claimed = [(d, claim(db, settings, d, now)) for d in rows]
    db.commit()
    for d, out in claimed:
        if out is None:
            continue
        code, exc = send(out, sender)
        record(db, d, now, code, exc)
        db.commit()
    return len(rows)


def run_tick(db: Session, settings, now: datetime) -> None:
    run_event_scan(db, settings, now)
    db.commit()
    deliver_due(db, settings, now)


def delivery_out(d: WebhookDelivery) -> dict:
    return {"id": d.id, "event": d.event, "status": d.status, "attempts": d.attempts, "created_at": d.created_at.isoformat(),
            "last_attempt_at": d.last_attempt_at.isoformat() if d.last_attempt_at else None, "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None,
            "last_status_code": d.last_status_code, "last_error": d.last_error, "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None}
