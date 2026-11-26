"""Administration > Website API keys (`/admin/website-keys`): the Futran Admin lists, creates and revokes the keys Futran's
website uses to read the public law library and litigation tracker. The key is returned once, by the call that creates it.
Every create and revoke is written to the audit log. Every endpoint calls `authorize` (MANAGE_WEBSITE_KEYS)."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Invalid, NotFound
from app.library import keys as K
from app.library.models import DEFAULT_RATE_LIMIT, WebsiteApiKey
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import User

router = APIRouter(tags=["website api keys"])
MAX_ORIGINS = 20


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    allowed_origins: list[str] = Field(default_factory=list, max_length=MAX_ORIGINS)
    rate_limit_per_minute: int = Field(default=DEFAULT_RATE_LIMIT, ge=1, le=1200)


def _check(db: Session, actor: Actor) -> None:
    if not actor.is_futran:
        raise NotFound()  # Futran's platform settings
    authorize(db, actor, Action.MANAGE_WEBSITE_KEYS)


def _out(db: Session, k: WebsiteApiKey) -> dict:
    def name(uid):
        u = db.get(User, uid) if uid else None
        return u.name if u else None

    iso = (lambda d: d.isoformat() if d else None)
    return {"id": k.id, "name": k.name, "key_prefix": k.key_prefix, "allowed_origins": k.allowed_origins or [], "rate_limit_per_minute": k.rate_limit_per_minute,
            "status": k.status, "created_at": iso(k.created_at), "created_by": name(k.created_by), "revoked_at": iso(k.revoked_at),
            "revoked_by": name(k.revoked_by), "last_used_at": iso(k.last_used_at)}


def _origins(values: list[str]) -> list[str]:
    out, bad = [], []
    for v in values:
        o = K.normalize_origin(v)
        if o is None:
            bad.append(v)
        elif o not in out:
            out.append(o)
    if bad:
        raise Invalid(errors=[{"field": "allowed_origins", "message": f"Not a website origin: {', '.join(bad)[:200]}. Use https://host (http only for localhost), with no path."}])
    return out


@router.get("/admin/website-keys")
def list_keys(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _check(db, actor)
    rows = db.scalars(select(WebsiteApiKey).order_by(WebsiteApiKey.status, WebsiteApiKey.created_at.desc()))
    return {"keys": [_out(db, k) for k in rows], "default_rate_limit_per_minute": DEFAULT_RATE_LIMIT}


@router.post("/admin/website-keys")
def create_key(body: KeyIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _check(db, actor)
    name = body.name.strip()
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Give the key a name, such as the website it is for."}])
    raw = K.new_key()
    k = WebsiteApiKey(name=name, key_prefix=raw[:K.PREFIX_SHOWN], key_hash=K.key_hash(raw), allowed_origins=_origins(body.allowed_origins),
                      rate_limit_per_minute=body.rate_limit_per_minute, status="active", created_by=actor.id)
    db.add(k)
    db.flush()
    audit.record(db, actor_id=actor.id, action="website_key.create", object_type="WebsiteApiKey", object_id=k.id, organization_id=actor.organization.id, request=request,
                 after={"name": k.name, "key_prefix": k.key_prefix, "allowed_origins": k.allowed_origins, "rate_limit_per_minute": k.rate_limit_per_minute},
                 summary=f"Created website API key {k.name} ({k.key_prefix}…)")
    return {"website_key": _out(db, k), "key": raw}


@router.post("/admin/website-keys/{key_id}/revoke")
def revoke_key(key_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _check(db, actor)
    k = db.get(WebsiteApiKey, key_id)
    if k is None:
        raise NotFound()
    if k.status == "revoked":
        raise Conflict("This key is already revoked.")
    k.status, k.revoked_at, k.revoked_by = "revoked", utcnow(), actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="website_key.revoke", object_type="WebsiteApiKey", object_id=k.id, organization_id=actor.organization.id, request=request,
                 before={"status": "active"}, after={"status": "revoked"}, summary=f"Revoked website API key {k.name} ({k.key_prefix}…)")
    return _out(db, k)
