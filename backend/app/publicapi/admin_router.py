"""Admin > API and webhooks (client app, `/admin/api`): the Client Admin creates API clients and webhooks; the CAICO may
look. Secrets are returned once, in the response that creates or rotates them. Every endpoint calls `authorize`."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor, get_settings_dep
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Forbidden, Invalid, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.publicapi import auth as A
from app.publicapi import netguard, webhooks
from app.publicapi.models import EVENTS, SCOPES, ApiClient, ApiToken, Webhook, WebhookDelivery
from app.tenancy.models import Organization, User

router = APIRouter(tags=["public api admin"])


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str]
    rate_limit_per_minute: int = Field(default=60, ge=1, le=600)


class ClientPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    scopes: list[str] | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=600)


class TransferIn(BaseModel):
    owner_id: str = Field(max_length=64)


class HookIn(BaseModel):
    url: str = Field(max_length=500)
    events: list[str]
    description: str | None = Field(default=None, max_length=200)


class HookPatch(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    events: list[str] | None = None
    description: str | None = Field(default=None, max_length=200)
    status: str | None = None


def _org(db: Session, actor: Actor, action: Action):
    if actor.is_futran:
        raise NotFound()  # the client's own integration settings
    authorize(db, actor, action, org_id=actor.organization.id)
    return actor.organization


def _may(db: Session, actor: Actor, action: Action) -> bool:
    try:
        _org(db, actor, action)
        return True
    except (Forbidden, NotFound):
        return False


def _scopes(v: list[str]) -> list[str]:
    bad = [s for s in v if s not in SCOPES]
    if bad or not v:
        raise Invalid(errors=[{"field": "scopes", "message": "Choose at least one scope from the list." if not bad else f"Unknown scope: {', '.join(bad)}."}])
    return [s for s in SCOPES if s in v]


def _events(v: list[str]) -> list[str]:
    bad = [e for e in v if e not in EVENTS]
    if bad or not v:
        raise Invalid(errors=[{"field": "events", "message": "Choose at least one event." if not bad else f"Unknown event: {', '.join(bad)}."}])
    return [e for e in EVENTS if e in v]


def _url(v: str, settings) -> str:
    try:
        netguard.check_url(v, offline=webhooks.mode(settings) == "fake")
    except netguard.Unsafe as exc:
        raise Invalid(str(exc), errors=[{"field": "url", "message": str(exc)}]) from exc
    return v.strip()


def client_out(db: Session, c: ApiClient) -> dict:
    owner = db.get(User, c.owner_id)
    org = db.get(Organization, c.organization_id)
    return {"id": c.id, "name": c.name, "client_id": c.client_id, "secret_hint": c.secret_hint, "scopes": c.scopes, "rate_limit_per_minute": c.rate_limit_per_minute,
            "status": c.status, "owner": owner.name if owner else None, "owner_id": c.owner_id, "owner_is_client_admin": A.is_client_admin(db, owner, org), "created_at": c.created_at.isoformat(), "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
            "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None}


def hook_out(db: Session, h: Webhook) -> dict:
    last = db.scalar(select(WebhookDelivery).where(WebhookDelivery.webhook_id == h.id).order_by(WebhookDelivery.created_at.desc()).limit(1))
    return {"id": h.id, "url": h.url, "events": h.events, "description": h.description, "status": h.status, "created_at": h.created_at.isoformat(),
            "last_delivery": webhooks.delivery_out(last) if last else None}


def _client(db: Session, actor: Actor, client_id: str) -> ApiClient:
    org = _org(db, actor, Action.MANAGE_API_CLIENTS)
    c = db.get(ApiClient, client_id)
    if c is None or c.deleted_at is not None or c.organization_id != org.id:
        raise NotFound()
    return c


def _hook(db: Session, actor: Actor, hook_id: str, action: Action = Action.MANAGE_API_CLIENTS) -> Webhook:
    org = _org(db, actor, action)
    h = db.get(Webhook, hook_id)
    if h is None or h.deleted_at is not None or h.organization_id != org.id:
        raise NotFound()
    return h


def _client_admins(db: Session, org) -> list[dict]:
    """The people an API client can be transferred to."""
    users = db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None), User.status == "active").order_by(User.name))
    return [{"id": u.id, "name": u.name} for u in users if A.is_client_admin(db, u, org)]


@router.get("/admin/api")
def overview(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _org(db, actor, Action.VIEW_API_CLIENTS)
    can_manage = _may(db, actor, Action.MANAGE_API_CLIENTS)
    clients = db.scalars(select(ApiClient).where(ApiClient.organization_id == org.id, ApiClient.deleted_at.is_(None)).order_by(ApiClient.created_at))
    hooks = db.scalars(select(Webhook).where(Webhook.organization_id == org.id, Webhook.deleted_at.is_(None)).order_by(Webhook.created_at))
    return {"clients": [client_out(db, c) for c in clients], "webhooks": [hook_out(db, h) for h in hooks], "scopes": [{"code": k, "label": v} for k, v in SCOPES.items()],
            "events": [{"code": k, "label": v} for k, v in EVENTS.items()], "can_manage": can_manage, "client_admins": _client_admins(db, org) if can_manage else [],
            "token_url": "/api/public/v1/oauth/token", "base_url": "/api/public/v1"}


@router.post("/admin/api/clients")
def create_client(body: ClientIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _org(db, actor, Action.MANAGE_API_CLIENTS)
    name = " ".join(body.name.split())
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Name the API client, for example the system that will use it."}])
    secret = A.new_secret()
    c = ApiClient(organization_id=org.id, name=name, client_id=A.new_client_id(), secret_hash=A.sha256(secret), secret_hint=secret[-4:], scopes=_scopes(body.scopes),
                  rate_limit_per_minute=body.rate_limit_per_minute, status="active", owner_id=actor.id, created_by=actor.id, updated_by=actor.id)
    db.add(c)
    db.flush()
    audit.record(db, actor_id=actor.id, action="api_client.created", obj=c, request=actor.request, after={"name": c.name, "scopes": c.scopes, "rate_limit_per_minute": c.rate_limit_per_minute},
                 summary=f"Created API client {c.name}")
    return {"client": client_out(db, c), "client_secret": secret}


@router.patch("/admin/api/clients/{client_id}")
def patch_client(client_id: str, body: ClientPatch, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    c = _client(db, actor, client_id)
    before = {"name": c.name, "scopes": c.scopes, "rate_limit_per_minute": c.rate_limit_per_minute}
    if body.name is not None and " ".join(body.name.split()):
        c.name = " ".join(body.name.split())
    if body.scopes is not None:
        c.scopes = _scopes(body.scopes)
        for t in db.scalars(select(ApiToken).where(ApiToken.api_client_id == c.id, ApiToken.revoked_at.is_(None))):
            t.revoked_at = utcnow()  # new scopes apply from the next token
    if body.rate_limit_per_minute is not None:
        c.rate_limit_per_minute = body.rate_limit_per_minute
    c.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="api_client.edited", obj=c, request=actor.request, before=before,
                 after={"name": c.name, "scopes": c.scopes, "rate_limit_per_minute": c.rate_limit_per_minute}, summary=f"Edited API client {c.name}")
    return client_out(db, c)


@router.post("/admin/api/clients/{client_id}/transfer")
def transfer_client(client_id: str, body: TransferIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Hand the client to another Client Admin of the organization; API writes are recorded as the owner's."""
    c = _client(db, actor, client_id)
    if c.status != "active":
        raise Invalid("A revoked API client cannot be transferred.")
    org = actor.organization
    new = db.get(User, body.owner_id)
    if not A.is_client_admin(db, new, org):
        raise Invalid(errors=[{"field": "owner_id", "message": "Choose an active Client Admin of your organization."}])
    old = db.get(User, c.owner_id)
    if new.id != c.owner_id:
        c.owner_id, c.updated_by = new.id, actor.id
        audit.record(db, actor_id=actor.id, action="api_client.transferred", obj=c, request=actor.request, before={"owner": old.name if old else None},
                     after={"owner": new.name}, summary=f"Transferred API client {c.name} to {new.name}"[:300])
    return client_out(db, c)


def _revoke_tokens(db: Session, c: ApiClient) -> None:
    for t in db.scalars(select(ApiToken).where(ApiToken.api_client_id == c.id, ApiToken.revoked_at.is_(None))):
        t.revoked_at = utcnow()


@router.post("/admin/api/clients/{client_id}/rotate-secret")
def rotate_secret(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    c = _client(db, actor, client_id)
    if c.status != "active":
        raise Invalid("A revoked API client cannot get a new secret. Create a new client instead.")
    secret = A.new_secret()
    c.secret_hash, c.secret_hint, c.secret_rotated_at, c.updated_by = A.sha256(secret), secret[-4:], utcnow(), actor.id
    _revoke_tokens(db, c)
    audit.record(db, actor_id=actor.id, action="api_client.secret_rotated", obj=c, request=actor.request, summary=f"Issued a new secret for API client {c.name}; old tokens revoked")
    return {"client": client_out(db, c), "client_secret": secret}


@router.post("/admin/api/clients/{client_id}/revoke")
def revoke_client(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    c = _client(db, actor, client_id)
    if c.status != "revoked":
        c.status, c.revoked_at, c.revoked_by, c.updated_by = "revoked", utcnow(), actor.id, actor.id
        _revoke_tokens(db, c)
        audit.record(db, actor_id=actor.id, action="api_client.revoked", obj=c, request=actor.request, summary=f"Revoked API client {c.name}")
    return client_out(db, c)


@router.post("/admin/api/webhooks")
def create_hook(body: HookIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _org(db, actor, Action.MANAGE_API_CLIENTS)
    url, events = _url(body.url, settings), _events(body.events)
    secret = "whsec_" + A.secrets.token_urlsafe(32)
    ref, enc = webhooks.seal_secret(settings, secret)
    h = Webhook(organization_id=org.id, url=url, events=events, secret_encrypted=enc, secret_ref=ref, status="active", description=(body.description or "").strip() or None,
                created_by=actor.id, updated_by=actor.id)
    db.add(h)
    db.flush()
    audit.record(db, actor_id=actor.id, action="webhook.created", obj=h, request=actor.request, after={"url": url, "events": events}, summary=f"Added a webhook to {url}"[:300])
    return {"webhook": hook_out(db, h), "signing_secret": secret}


@router.patch("/admin/api/webhooks/{hook_id}")
def patch_hook(hook_id: str, body: HookPatch, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    h = _hook(db, actor, hook_id)
    before = {"url": h.url, "events": h.events, "status": h.status}
    if body.url is not None:
        h.url = _url(body.url, settings)
    if body.events is not None:
        h.events = _events(body.events)
    if body.description is not None:
        h.description = body.description.strip() or None
    if body.status is not None:
        if body.status not in ("active", "paused"):
            raise Invalid(errors=[{"field": "status", "message": "Choose active or paused."}])
        h.status = body.status
    h.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="webhook.edited", obj=h, request=actor.request, before=before, after={"url": h.url, "events": h.events, "status": h.status},
                 summary=f"Edited the webhook to {h.url}"[:300])
    return hook_out(db, h)


@router.post("/admin/api/webhooks/{hook_id}/remove")
def remove_hook(hook_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    h = _hook(db, actor, hook_id)
    h.deleted_at, h.status, h.updated_by = utcnow(), "paused", actor.id
    audit.record(db, actor_id=actor.id, action="webhook.removed", obj=h, request=actor.request, summary=f"Removed the webhook to {h.url}"[:300])
    return {"removed": True}


@router.post("/admin/api/webhooks/{hook_id}/rotate-secret")
def rotate_hook_secret(hook_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    h = _hook(db, actor, hook_id)
    secret = "whsec_" + A.secrets.token_urlsafe(32)
    h.secret_ref, h.secret_encrypted = webhooks.seal_secret(settings, secret)
    h.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="webhook.secret_rotated", obj=h, request=actor.request, summary=f"Issued a new signing secret for the webhook to {h.url}"[:300])
    return {"webhook": hook_out(db, h), "signing_secret": secret}


@router.post("/admin/api/webhooks/{hook_id}/test")
def test_hook(hook_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    from app.core.ratelimit import TooManyRequests, limiter

    h = _hook(db, actor, hook_id)
    try:
        limiter(request, "webhook_test_send", webhooks.TEST_SENDS_PER_MINUTE).check(h.id)
    except TooManyRequests:
        raise TooManyRequests("Too many test deliveries to this webhook. Wait a minute and try again.") from None
    now = utcnow()
    d = webhooks.enqueue(db, h.organization_id, "ping", {"message": "Test delivery from the Futran Audit Platform.", "requested_by": actor.user.name},
                         event_key=f"ping:{now.isoformat()}", hooks=[h])[0]
    out = webhooks.claim(db, settings, d, now)
    db.commit()  # no write transaction stays open while the receiver answers
    if out is not None:
        code, exc = webhooks.send(out, webhooks.sender_for(settings, getattr(request.app.state, "webhook_sender", None)))
        webhooks.record(db, d, now, code, exc)
    if d.status == "retrying":  # a test is tried once
        d.status, d.next_attempt_at = "failed", None
    audit.record(db, actor_id=actor.id, action="webhook.tested", obj=h, request=actor.request, summary=f"Sent a test delivery to {h.url}: {d.status}"[:300])
    return webhooks.delivery_out(d)


@router.get("/admin/api/webhooks/{hook_id}/deliveries")
def deliveries(hook_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    h = _hook(db, actor, hook_id, Action.VIEW_API_CLIENTS)
    rows = db.scalars(select(WebhookDelivery).where(WebhookDelivery.webhook_id == h.id).order_by(WebhookDelivery.created_at.desc()).limit(200))
    return {"rows": [webhooks.delivery_out(d) for d in rows]}
