"""httpx helpers for the live connector adapters. Tests pass an httpx.MockTransport, so nothing touches the network."""
import time

import httpx

from app.connectors.adapters import ConnectorError

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_PAGES = 50  # a guard against a provider that never stops paging


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=transport, follow_redirects=False)


def request(c: httpx.Client, method: str, url: str, what: str, **kw) -> httpx.Response:
    try:
        resp = c.request(method, url, **kw)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"{what} failed: {exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        detail = ""
        try:
            data = resp.json()
            err = data.get("error")
            detail = (err.get("message") if isinstance(err, dict) else data.get("error_description") or data.get("errorSummary") or err) or ""
        except Exception:  # not JSON
            detail = resp.text[:200]
        raise ConnectorError(f"{what} failed ({resp.status_code}){': ' + str(detail)[:300] if detail else ''}", status=resp.status_code)
    return resp


def expires_at(seconds) -> float:
    return time.time() + float(seconds or 3600)


def expired(grant: dict) -> bool:
    return not grant.get("access_token") or float(grant.get("expires_at") or 0) <= time.time() + 60
