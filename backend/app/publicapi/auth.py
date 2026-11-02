"""OAuth 2.0 client credentials for the public API (RFC 6749 §4.4), bearer tokens (RFC 6750) and the per-client rate limit.

The public API never reads cookies: the only credential it accepts is `Authorization: Bearer <token>`, and the session
API (/api/v1) never reads bearer tokens. Every token belongs to one API client, and one API client to one organization;
every query the public endpoints run is scoped to that organization. Each call is written to the audit log in its own
transaction, so a call that fails is still on record.
"""
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.ratelimit import client_ip
from app.publicapi.models import SCOPES, ApiClient, ApiToken  # noqa: F401  (SCOPES re-exported for public_app)
from app.tenancy.models import Organization, User

TOKEN_TTL = timedelta(hours=1)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_client_id() -> str:
    return "fap_" + secrets.token_hex(12)


def new_secret() -> str:
    return "fapsk_" + secrets.token_urlsafe(32)


def new_access_token() -> str:
    return "fapat_" + secrets.token_urlsafe(32)


class OAuthError(Exception):
    """An RFC 6749 / 6750 error response: {"error": code, "error_description": text}."""

    def __init__(self, status: int, code: str, description: str, headers: dict | None = None):
        super().__init__(description)
        self.status, self.code, self.description, self.headers = status, code, description, headers or {}

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status, content={"error": self.code, "error_description": self.description}, headers={"Cache-Control": "no-store", **self.headers})


# ---------------------------------------------------------------- rate limit: one token bucket per API client
class TokenBucket:
    def __init__(self, per_minute: int):
        self.capacity = max(1, per_minute)
        self.tokens = float(self.capacity)
        self.rate = self.capacity / 60.0
        self.at = time.monotonic()

    def take(self) -> float | None:
        """None when allowed; otherwise seconds to wait."""
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.at) * self.rate)
        self.at = now
        if self.tokens >= 1:
            self.tokens -= 1
            return None
        return (1 - self.tokens) / self.rate


def _bucket(request: Request, c: ApiClient) -> TokenBucket:
    store = request.app.state.__dict__.setdefault("_api_buckets", {})
    b = store.get(c.id)
    if b is None or b.capacity != max(1, c.rate_limit_per_minute):
        b = store[c.id] = TokenBucket(c.rate_limit_per_minute)
    return b


# ---------------------------------------------------------------- the token endpoint
def _log(request: Request, org_id: str, action: str, c: ApiClient, summary: str) -> None:
    """Write one audit entry in its own transaction."""
    db: Session = request.app.state.sessionmaker()
    try:
        audit.record(db, actor_id=None, actor_name=f"API client: {c.name}", action=action, object_type="ApiClient", object_id=c.id, organization_id=org_id,
                     request=request, summary=summary[:300])
        if action == "public_api.call":
            row = db.get(ApiClient, c.id)
            if row is not None:
                row.last_used_at = utcnow()
        db.commit()
    finally:
        db.close()


def issue_token(request: Request, db: Session, form: dict, basic: tuple[str, str] | None) -> dict:
    grant = (form.get("grant_type") or "").strip()
    cid, secret = basic if basic else ((form.get("client_id") or "").strip(), form.get("client_secret") or "")
    if grant != "client_credentials":
        raise OAuthError(400, "unsupported_grant_type", "Only the client_credentials grant is supported.")
    if not cid or not secret:
        raise OAuthError(400, "invalid_request", "Send client_id and client_secret (in the body or with HTTP Basic authentication).")
    c = db.scalar(select(ApiClient).where(ApiClient.client_id == cid, ApiClient.deleted_at.is_(None)))
    if c is None or c.status != "active" or not hmac.compare_digest(c.secret_hash, sha256(secret)) or not _org_active(db, c):
        if c is not None:
            _log(request, c.organization_id, "public_api.token_refused", c, f"Refused a token request for {c.name} from {client_ip(request)}")
        raise OAuthError(401, "invalid_client", "The client credentials are not valid.", {"WWW-Authenticate": 'Basic realm="futran-public-api"'})
    asked = (form.get("scope") or "").split()
    if asked and not set(asked) <= set(c.scopes or []):
        raise OAuthError(400, "invalid_scope", "The client may not use one or more of the requested scopes.")
    scopes = [s for s in (c.scopes or []) if not asked or s in asked]
    raw = new_access_token()
    db.add(ApiToken(organization_id=c.organization_id, api_client_id=c.id, token_hash=sha256(raw), scopes=scopes, issued_at=utcnow(), expires_at=utcnow() + TOKEN_TTL))
    db.flush()
    # same transaction as the token: a second connection would wait on this one's write lock (SQLite)
    audit.record(db, actor_id=None, actor_name=f"API client: {c.name}", action="public_api.token_issued", object_type="ApiClient", object_id=c.id,
                 organization_id=c.organization_id, request=request, summary=f"Issued an access token to {c.name} ({' '.join(scopes)})"[:300])
    return {"access_token": raw, "token_type": "Bearer", "expires_in": int(TOKEN_TTL.total_seconds()), "scope": " ".join(scopes)}


def _org_active(db: Session, c: ApiClient) -> bool:
    org = db.get(Organization, c.organization_id)
    return org is not None and org.type == "client" and org.deleted_at is None


# ---------------------------------------------------------------- the caller of a public endpoint
@dataclass
class Caller:
    client: ApiClient
    organization: Organization
    scopes: set[str]
    request: Request

    def owner(self, db: Session) -> User:
        """The Client Admin who answers for this API client; API writes are recorded as theirs, with the client named."""
        from app.core.errors import Conflict

        u = db.get(User, self.client.owner_id)
        if u is None or u.status != "active" or u.deleted_at is not None or u.organization_id != self.organization.id:
            raise Conflict("The person who owns this API client no longer has an active account. Ask your Client Admin to take it over.")
        return u


def authenticate(request: Request, db: Session) -> Caller:
    header = request.headers.get("authorization") or ""
    scheme, _, raw = header.partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        raise OAuthError(401, "invalid_token", "Send an access token: Authorization: Bearer <token>.", {"WWW-Authenticate": 'Bearer realm="futran-public-api"'})
    t = db.scalar(select(ApiToken).where(ApiToken.token_hash == sha256(raw.strip())))
    c = db.get(ApiClient, t.api_client_id) if t is not None else None
    if t is None or c is None or t.revoked_at is not None or t.expires_at <= utcnow() or c.status != "active" or c.deleted_at is not None or not _org_active(db, c):
        raise OAuthError(401, "invalid_token", "The access token is not valid or has expired.", {"WWW-Authenticate": 'Bearer realm="futran-public-api", error="invalid_token"'})
    wait = _bucket(request, c).take()
    if wait is not None:
        _log(request, c.organization_id, "public_api.rate_limited", c, f"Rate limited {request.method} {request.url.path.removeprefix('/api/public/v1')}")
        raise OAuthError(429, "rate_limited", f"Too many requests. This client may make {c.rate_limit_per_minute} calls a minute.", {"Retry-After": str(max(1, round(wait)))})
    _log(request, c.organization_id, "public_api.call", c, f"{request.method} {request.url.path.removeprefix('/api/public/v1')}")
    return Caller(client=c, organization=db.get(Organization, c.organization_id), scopes=set(t.scopes or []), request=request)


def require(caller: Caller, scope: str) -> None:
    assert scope in SCOPES, scope
    if scope not in caller.scopes:
        raise OAuthError(403, "insufficient_scope", f"This call needs the {scope} scope.", {"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'})
