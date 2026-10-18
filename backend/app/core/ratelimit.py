"""A small in-process sliding-window rate limiter for public endpoints (one server process on the laptop or Render).
A multi-instance deployment should move this to a shared store."""
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import AppError


class TooManyRequests(AppError):
    status_code = 429


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise TooManyRequests("Too many submissions from this network. Wait a minute and try again.")
        q.append(now)


def limiter(request: Request, name: str, limit: int) -> RateLimiter:
    """Per-app limiters, so each app instance (and each test) starts clean."""
    store = request.app.state.__dict__.setdefault("_limiters", {})
    if name not in store:
        store[name] = RateLimiter(limit)
    return store[name]


def client_ip(request: Request) -> str:
    """The caller's address. Behind a trusted proxy, the right-most X-Forwarded-For entry: the one the platform's own
    proxy appended. Entries to its left come from the caller and can be forged."""
    settings = request.app.state.settings
    fwd = request.headers.get("x-forwarded-for")
    if getattr(settings, "trust_proxy_headers", False) and fwd:
        return fwd.split(",")[-1].strip()[:64]
    return request.client.host if request.client else "unknown"


def client_ip_or_none(request) -> str | None:
    """client_ip for records (sessions, signatures, the audit log); None when there is no request."""
    try:
        ip = client_ip(request)
    except AttributeError:  # a request-like object without app state
        return request.client.host if getattr(request, "client", None) else None
    return None if ip == "unknown" else ip
