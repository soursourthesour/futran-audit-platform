"""Website API keys: making, checking and describing them."""
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.library.models import WebsiteApiKey

KEY_PREFIX = "fwl_"  # "Futran website library"
PREFIX_SHOWN = 12
LAST_USED_EVERY = timedelta(minutes=1)  # last_used_at is written at most once a minute per key, not on every call
LOCAL_HOSTS = ("localhost", "127.0.0.1")


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def normalize_origin(value: str) -> str | None:
    """`https://host[:port]` in lower case, or `http://localhost[:port]` for local work; None when it is not an origin."""
    v = (value or "").strip()
    parts = urlsplit(v)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.path not in ("", "/") or "*" in v:
        return None
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    return f"{parts.scheme}://{parts.hostname.lower()}" + (f":{port}" if port else "")


def find_active(db: Session, raw: str) -> WebsiteApiKey | None:
    if not raw or not raw.startswith(KEY_PREFIX) or len(raw) > 200:
        return None
    k = db.scalar(select(WebsiteApiKey).where(WebsiteApiKey.key_hash == key_hash(raw)))
    return k if k is not None and k.status == "active" else None


def touch(k: WebsiteApiKey) -> None:
    now = utcnow()
    if k.last_used_at is None or now - k.last_used_at >= LAST_USED_EVERY:
        k.last_used_at = now


def allowed_anywhere(db: Session, origin: str) -> bool:
    """Whether any active key lists this browser origin (for CORS preflight, which carries no key)."""
    return any(origin in (k.allowed_origins or []) for k in db.scalars(select(WebsiteApiKey).where(WebsiteApiKey.status == "active")))
