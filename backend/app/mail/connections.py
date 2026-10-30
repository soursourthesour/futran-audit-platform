"""Mailbox connections: Futran's (E1), a client's (E2) and each user's own (§27.1).

Consent goes through the provider's own page. The `state` sent with it is signed, names the connection and carries a
nonce whose hash is kept on the connection, so a consent response is accepted once and only for the connection that
asked. The callback needs no sign-in: the client's IT admin can approve from the link the Client Admin emails them.
"""
import hashlib
import re
import secrets
from urllib.parse import quote, urlsplit

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import AppError, Conflict, Invalid
from app.mail import adminlog, delivery, tokens
from app.mail.models import DirectorySync, MailConnection, MailOrgSettings, MailRecipient, MailSend, UserMailConnection
from app.mail.providers import PROVIDER_LABELS, PROVIDERS, ProviderError, credentials_status, get_adapter, use_fake
from app.tenancy.models import Organization, User

STATE_MAX_AGE = {"admin": 7 * 24 * 3600, "user": 3600}  # IT may approve a few days after the request
RETURN_PATHS = {"futran": "/staff/admin/email", "client": "/admin/email", "user": "/welcome/mailbox"}


class BadRequest(AppError):
    status_code = 400


def safe_next(v) -> str | None:
    """A return path is kept only when it is a same-origin relative path that starts with a single "/"."""
    if not isinstance(v, str) or not v.startswith("/") or v.startswith("//") or len(v) > 500 or re.search(r"[\x00-\x1f\x7f\\]", v):
        return None
    parts = urlsplit(v)
    return v if not parts.scheme and not parts.netloc else None


def with_query(path: str, **params: str) -> str:
    """Add query parameters to a return path that may already carry some."""
    q = "&".join(f"{k}={quote(v, safe='/')}" for k, v in params.items())
    return f"{path}{'&' if '?' in path else '?'}{q}"


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="mail-oauth")


def _h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def org_connection(db: Session, org: Organization, create: bool = False) -> MailConnection | None:
    c = db.scalar(select(MailConnection).where(MailConnection.organization_id == org.id, MailConnection.deleted_at.is_(None)).limit(1))
    if c is None and create:
        c = MailConnection(organization_id=org.id, owner="futran" if org.type == "futran" else "client", status="not_connected", sender_mode="own",
                           reply_to_mode="mailbox", sync_interval_min=15, onboarding_step=1,
                           options={"save_activity": True, "sync_replies": True, "track_bounces": True, "futran_copy": "audit"})
        db.add(c)
        db.flush()
    return c


def user_connection(db: Session, user: User, create: bool = False) -> UserMailConnection | None:
    c = db.scalar(select(UserMailConnection).where(UserMailConnection.user_id == user.id, UserMailConnection.deleted_at.is_(None)).limit(1))
    if c is None and create:
        c = UserMailConnection(organization_id=user.organization_id, user_id=user.id, provider="microsoft365", status="pending")
        db.add(c)
        db.flush()
    return c


def _check_provider(settings: Settings, provider: str):
    if provider not in PROVIDERS:
        raise Invalid(errors=[{"field": "provider", "message": "Choose Microsoft 365 or Google Workspace."}])
    adapter = get_adapter(settings, provider)
    if adapter is None:
        st = credentials_status(settings)[provider]
        raise Conflict(f"{PROVIDER_LABELS[provider]} is not set up on this platform yet. Futran IT must register the app and add {', '.join(st['missing'])} to the "
                       "configuration. Until then emails go out through the platform's own mail service.")
    return adapter


def start_consent(db: Session, settings: Settings, actor: User | None, holder, *, provider: str, kind: str, mailbox: str | None = None, tenant: str | None = None,
                  next_path: str | None = None) -> str:
    """Return the provider URL that asks for consent. `holder` is a MailConnection (kind admin) or a UserMailConnection."""
    adapter = _check_provider(settings, provider)
    nonce = secrets.token_urlsafe(16)
    target = "user" if isinstance(holder, UserMailConnection) else "org"
    payload = {"t": target, "id": holder.id, "n": nonce, "k": kind, "p": provider}
    if target == "user" and safe_next(next_path):
        payload["r"] = safe_next(next_path)  # where the person was going when the mailbox step interrupted them
    state = _serializer(settings).dumps(payload)
    holder.oauth_state_hash = _h(nonce)
    holder.provider = provider
    if isinstance(holder, MailConnection):
        if mailbox:
            holder.mailbox_address = mailbox.strip().lower()
        if holder.status in ("not_connected", "disconnected", "error"):
            holder.status = "consent_requested"
    db.flush()
    return adapter.consent_url(kind=kind, state=state, tenant=tenant, login_hint=mailbox or (holder.mailbox if isinstance(holder, UserMailConnection) else None))


def _load_state(settings: Settings, state: str) -> dict:
    try:
        data = _serializer(settings).loads(state or "", max_age=STATE_MAX_AGE["admin"])
    except SignatureExpired as exc:
        raise BadRequest("This consent link has expired. Start the connection again.") from exc
    except BadSignature as exc:
        raise BadRequest("This consent response is not valid.") from exc
    return data


def complete_consent(db: Session, settings: Settings, provider: str, params: dict) -> tuple[str, object]:
    """Finish a consent from the provider's redirect. Returns (return path, holder)."""
    data = _load_state(settings, params.get("state", ""))
    if data.get("p") != provider:
        raise BadRequest("This consent response is not valid.")
    model = UserMailConnection if data["t"] == "user" else MailConnection
    holder = db.get(model, data["id"])
    if holder is None or holder.oauth_state_hash is None or holder.oauth_state_hash != _h(data["n"]):
        raise BadRequest("This consent response has already been used or was replaced by a newer request.")
    if data["t"] == "user" and (utcnow() - holder.updated_at).total_seconds() > STATE_MAX_AGE["user"]:
        raise BadRequest("This sign-in has expired. Connect your mailbox again.")
    holder.oauth_state_hash = None  # single use, whatever happens next
    adapter = _check_provider(settings, provider)
    try:
        grant = adapter.complete_consent(kind=data["k"], params=params)
    except ProviderError as exc:
        if isinstance(holder, MailConnection):
            holder.status, holder.last_error = "error", str(exc)[:500]
            adminlog.write(db, organization_id=holder.organization_id, category="consent", action="consent_failed", actor_name="Provider", summary=f"Consent not completed: {str(exc)[:200]}")
        db.flush()
        raise Invalid(errors=[{"field": "consent", "message": str(exc)}]) from exc
    now = utcnow()
    if isinstance(holder, UserMailConnection):
        holder.mailbox = (grant.get("mailbox") or holder.mailbox or "").lower() or None
        holder.scopes, holder.status, holder.consented_at = adapter.scopes("user"), "connected", now
        tokens.store(settings, holder, grant)
        db.flush()
        r = safe_next(data.get("r"))
        return (with_query(RETURN_PATHS["user"], next=r) if r else RETURN_PATHS["user"]), holder
    domains = [d.lower() for d in grant.get("domains") or []]
    if grant.get("mailbox") and (not holder.mailbox_address or provider == "google"):
        holder.mailbox_address = grant["mailbox"]
    holder.tenant_id = grant.get("tenant") or holder.tenant_id
    holder.domain = (holder.mailbox_address.split("@", 1)[1] if holder.mailbox_address and "@" in holder.mailbox_address else (domains[0] if domains else None))
    holder.scopes, holder.status, holder.consent_at, holder.last_error = adapter.scopes(data["k"]), "connected", now, None
    holder.consent_by = grant.get("mailbox") or "the organization's IT administrator"
    tokens.store(settings, holder, grant)
    domain_check(db, settings, holder)
    org = db.get(Organization, holder.organization_id)
    adminlog.write(db, organization_id=holder.organization_id, category="consent", action="consent", actor_name="IT admin",
                   summary=f"Admin consent for the Futran Audit Platform in {PROVIDER_LABELS[provider]} (send mail, read replies to platform emails, read users and groups)")
    adminlog.write(db, organization_id=holder.organization_id, category="connection", action="connected", actor_name="System",
                   summary=f"Connected {PROVIDER_LABELS[provider]}" + (f"; sender {holder.mailbox_address}" if holder.mailbox_address else ""))
    if holder.owner == "client":
        holder.onboarding_step = max(holder.onboarding_step or 1, 2)
        if db.scalar(select(DirectorySync).where(DirectorySync.connection_id == holder.id)) is None:
            db.add(DirectorySync(organization_id=holder.organization_id, connection_id=holder.id, schedule="daily", department_field="department", include_guests=False,
                                 use_directory_groups=True, enabled=True))
    db.flush()
    return RETURN_PATHS["futran" if org.type == "futran" else "client"], holder


def domain_check(db: Session, settings: Settings, conn: MailConnection) -> None:
    if not conn.domain:
        return
    if use_fake(settings):
        conn.spf_ok = conn.dkim_ok = conn.dmarc_ok = True
        return
    from app.mail.domain_check import check_domain

    r = check_domain(conn.domain, conn.provider)
    conn.spf_ok, conn.dkim_ok, conn.dmarc_ok = r["spf_ok"], r["dkim_ok"], r["dmarc_ok"]


SETTABLE = ("send_as_name", "reply_to", "reply_to_mode", "sender_mode", "sync_interval_min", "options", "mailbox_address", "onboarding_step")


def update(db: Session, actor: User, conn: MailConnection, data: dict) -> MailConnection:
    errs = []
    before = {k: getattr(conn, k) for k in SETTABLE}
    if "mailbox_address" in data:
        mb = str(data.get("mailbox_address") or "").strip().lower()
        if mb and ("@" not in mb or " " in mb):
            errs.append({"field": "mailbox_address", "message": "Enter the mailbox address, for example ai-governance@yourcompany.com."})
        elif mb and conn.status == "connected" and conn.provider == "google" and conn.mailbox_address and mb != conn.mailbox_address:
            errs.append({"field": "mailbox_address", "message": "With Google Workspace the sender is the account that signed in. Connect again as the other mailbox."})
        else:
            conn.mailbox_address = mb or None
            if mb:
                conn.domain = mb.split("@", 1)[1]
    if "send_as_name" in data:
        conn.send_as_name = " ".join(str(data.get("send_as_name") or "").split())[:200] or None
    if "reply_to_mode" in data:
        if data["reply_to_mode"] not in ("mailbox", "chief_auditor", "caico"):
            errs.append({"field": "reply_to_mode", "message": "Choose where replies go."})
        else:
            conn.reply_to_mode = data["reply_to_mode"]
    if "reply_to" in data:
        conn.reply_to = str(data.get("reply_to") or "").strip().lower() or None
    if "sender_mode" in data:
        if data["sender_mode"] not in ("own", "futran_on_behalf") or (conn.owner == "futran" and data["sender_mode"] != "own"):
            errs.append({"field": "sender_mode", "message": "Choose who the emails come from."})
        else:
            conn.sender_mode = data["sender_mode"]
    if "sync_interval_min" in data:
        try:
            n = int(data["sync_interval_min"])
        except (TypeError, ValueError):
            n = 0
        if n not in (5, 15, 60):
            errs.append({"field": "sync_interval_min", "message": "Choose 5 minutes, 15 minutes or hourly."})
        else:
            conn.sync_interval_min = n
    if "options" in data and isinstance(data["options"], dict):
        allowed = {"save_activity", "sync_replies", "track_bounces", "futran_copy", "calendar"}
        conn.options = {**(conn.options or {}), **{k: v for k, v in data["options"].items() if k in allowed}}
    if "onboarding_step" in data:
        try:
            conn.onboarding_step = max(1, min(5, int(data["onboarding_step"])))
        except (TypeError, ValueError):
            pass
    if errs:
        raise Invalid(errors=errs)
    changed = {k for k in SETTABLE if before[k] != getattr(conn, k)} - {"onboarding_step"}
    if changed & {"mailbox_address", "send_as_name", "sender_mode", "reply_to_mode", "reply_to"}:
        who = "Futran on the client's behalf" if conn.sender_mode == "futran_on_behalf" else (conn.mailbox_address or "not set")
        adminlog.write(db, organization_id=conn.organization_id, category="sender", action="sender_changed", actor=actor,
                       summary=f"Sender: {who}" + (f" as “{conn.send_as_name}”" if conn.send_as_name and conn.sender_mode == "own" else ""),
                       details={k: [before[k], getattr(conn, k)] for k in changed if k != "options"})
    elif changed:
        adminlog.write(db, organization_id=conn.organization_id, category="connection", action="settings_changed", actor=actor,
                       summary="Changed email settings: " + ", ".join(sorted(k.replace("_", " ") for k in changed)))
    db.flush()
    return conn


def disconnect(db: Session, settings: Settings, actor: User | None, holder) -> None:
    adapter = get_adapter(settings, holder.provider)
    if adapter is not None and holder.token_encrypted:
        try:
            adapter.revoke(tokens.load(settings, holder))
        except (ProviderError, tokens.TokenError):
            pass
    tokens.clear(holder)
    holder.status = "disconnected"
    if isinstance(holder, MailConnection):
        adminlog.write(db, organization_id=holder.organization_id, category="connection", action="disconnected", actor=actor,
                       summary=f"Disconnected {PROVIDER_LABELS.get(holder.provider or '', 'the mailbox')}; emails now go through the platform's own mail service")
    db.flush()


def send_test(db: Session, settings: Settings, actor: User, conn: MailConnection, to: str) -> MailSend:
    to = (to or "").strip().lower()
    if "@" not in to:
        raise Invalid(errors=[{"field": "to", "message": "Enter the address to send the test to."}])
    org = db.get(Organization, conn.organization_id)
    sender = delivery.resolve_sender(db, settings, conn.organization_id, prefer="futran" if conn.owner == "futran" else "organization")
    from app.mail.service import render

    subject, html, text = render("test_message", {"organization_name": org.name, "body": f"This test was sent from {sender.label} by the Futran Audit Platform. "
                                                  "If you can read it, email from the platform reaches your people.", "base_url": settings.base_url})
    now = utcnow()
    s = MailSend(organization_id=conn.organization_id, kind="test", mode="direct", template_key="test_message", template_name="Test email", subject=subject,
                 channel=sender.channel, sender_label=sender.label, sender_connection_id=sender.connection.id if sender.connection else None, recipient_count=1,
                 sent_by=actor.id, sent_by_name=actor.name, status="sent", sent_at=now, retain_until=adminlog.retain_until(now), created_by=actor.id)
    db.add(s)
    db.flush()
    env = delivery.Envelope(to=[to], subject=subject, html=html, text=text)
    msg = delivery.record(db, organization_id=conn.organization_id, env=env, stored=None, template_key="test_message", actor_id=actor.id, mail_send_id=s.id, channel=sender.channel)
    res = delivery.deliver(db, settings, sender, env, msg)
    db.add(MailRecipient(organization_id=conn.organization_id, send_id=s.id, email=to, status="sent" if res.ok else "bounced", error=res.error, last_event_at=now, attempts=1))
    if res.ok:
        conn.test_sent_at, conn.test_sent_to = now, to
        conn.onboarding_step = max(conn.onboarding_step or 1, 4)
    adminlog.write(db, organization_id=conn.organization_id, category="send", action="test", actor=actor, send_id=s.id,
                   summary=f"Test email to {to} from {sender.label}" + ("" if res.ok else f" failed: {(res.error or '')[:150]}"))
    db.flush()
    if not res.ok:
        raise Conflict(f"The test email was not sent: {res.error}")
    return s


def request_it(db: Session, settings: Settings, actor: User, conn: MailConnection, email: str, provider: str) -> None:
    email = (email or "").strip().lower()
    if "@" not in email or " " in email:
        raise Invalid(errors=[{"field": "email", "message": "Enter your IT administrator's email."}])
    url = start_consent(db, settings, actor, conn, provider=provider, kind="admin", mailbox=conn.mailbox_address)
    org = db.get(Organization, conn.organization_id)
    adapter = get_adapter(settings, provider)
    from app.mail.service import send

    send(db, settings, "it_consent_request", to=[email], organization_id=conn.organization_id, actor_id=actor.id, related=conn,
         context={"organization": org.name, "requester": actor.name, "provider": PROVIDER_LABELS[provider], "link": url, "scopes": adapter.scopes("admin"),
                  "microsoft": provider == "microsoft365", "mailbox": conn.mailbox_address},
         redact={"link": "(consent link sent to IT, not stored)"})
    conn.it_request_email, conn.it_request_sent_at = email, utcnow()
    adminlog.write(db, organization_id=conn.organization_id, category="consent", action="consent_requested", actor=actor,
                   summary=f"Asked IT ({email}) to approve access in {PROVIDER_LABELS[provider]}")
    db.flush()


# ---- per-user policy
def org_settings(db: Session, org_id: str, create: bool = False) -> MailOrgSettings | None:
    s = db.scalar(select(MailOrgSettings).where(MailOrgSettings.organization_id == org_id))
    if s is None and create:
        s = MailOrgSettings(organization_id=org_id, per_user_sync="optional")
        db.add(s)
        db.flush()
    return s


def per_user_policy(db: Session, org_id: str) -> str:
    s = org_settings(db, org_id)
    return s.per_user_sync if s else "optional"


def connection_out(c: MailConnection | None) -> dict:
    if c is None:
        return {"status": "not_connected", "provider": None, "mailbox_address": None}
    return {"id": c.id, "status": c.status, "provider": c.provider, "provider_label": PROVIDER_LABELS.get(c.provider or "", None), "mailbox_address": c.mailbox_address,
            "send_as_name": c.send_as_name, "reply_to": c.reply_to, "reply_to_mode": c.reply_to_mode, "sender_mode": c.sender_mode, "scopes": c.scopes or [],
            "consent_by": c.consent_by, "consent_at": c.consent_at.isoformat() if c.consent_at else None, "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
            "spf_ok": c.spf_ok, "dkim_ok": c.dkim_ok, "dmarc_ok": c.dmarc_ok, "sync_interval_min": c.sync_interval_min, "options": c.options or {}, "domain": c.domain,
            "it_request_email": c.it_request_email, "it_request_sent_at": c.it_request_sent_at.isoformat() if c.it_request_sent_at else None,
            "test_sent_at": c.test_sent_at.isoformat() if c.test_sent_at else None, "test_sent_to": c.test_sent_to, "last_error": c.last_error,
            "onboarding_step": c.onboarding_step, "completed_at": c.completed_at.isoformat() if c.completed_at else None}
