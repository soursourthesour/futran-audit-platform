"""A small httpx helper shared by the real adapters. Tests pass an httpx.MockTransport, so nothing touches the network."""
import time

import httpx

from app.mail.providers import ProviderError

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=transport)


def check(resp: httpx.Response, what: str) -> httpx.Response:
    if resp.status_code < 400:
        return resp
    retryable = resp.status_code == 429 or resp.status_code >= 500
    detail = ""
    try:
        data = resp.json()
        err = data.get("error")
        detail = (err.get("message") if isinstance(err, dict) else data.get("error_description") or err) or ""
    except Exception:  # not JSON
        detail = resp.text[:200]
    raise ProviderError(f"{what} failed ({resp.status_code}){': ' + str(detail)[:300] if detail else ''}", retryable=retryable, status=resp.status_code)


def request(c: httpx.Client, method: str, url: str, what: str, **kw) -> httpx.Response:
    try:
        return check(c.request(method, url, **kw), what)
    except httpx.HTTPError as exc:
        raise ProviderError(f"{what} failed: {exc.__class__.__name__}", retryable=True) from exc


def expired(grant) -> bool:
    return not grant.get("access_token") or float(grant.get("expires_at") or 0) <= time.time() + 60


def expires_at(seconds) -> float:
    return time.time() + float(seconds or 3600)
