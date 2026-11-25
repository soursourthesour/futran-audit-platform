"""BUG-H05: every response carries the browser security headers; the app pages carry a Content-Security-Policy that
the built React app works under; Swagger UI gets its own policy; HSTS only when the platform is served over https."""
import pytest
from fastapi.testclient import TestClient

from app.core.security_headers import APP_CSP, DOCS_CSP
from app.main import create_app

PATHS = ["/", "/login", "/staff/login", "/api/v1/health", "/api/v1/auth/me", "/api/v1/nope"]


@pytest.mark.parametrize("path", PATHS)
def test_common_headers_on_pages_and_api(client, path):
    r = client.get(path)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["content-security-policy"] == APP_CSP
    assert "strict-transport-security" not in r.headers  # the test server is http


def test_app_policy_blocks_framing_plugins_and_base_changes():
    for part in ("default-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "base-uri 'self'"):
        assert part in APP_CSP
    assert "script-src" not in APP_CSP or "'unsafe-inline'" not in APP_CSP.split("script-src")[1].split(";")[0]


@pytest.mark.parametrize("path", ["/api/docs", "/api/public/v1/docs"])
def test_swagger_gets_its_own_policy(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == DOCS_CSP
    assert "https://cdn.jsdelivr.net" in DOCS_CSP and "frame-ancestors 'none'" in DOCS_CSP


def test_a_route_that_sets_its_own_policy_keeps_it(client, db):
    """File downloads send a sandbox policy; the middleware must not replace it."""
    from app.core.security_headers import SecurityHeaders

    seen = {}

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-security-policy", b"sandbox; default-src 'none'")]})
        await send({"type": "http.response.body", "body": b""})

    async def capture(msg):
        if msg["type"] == "http.response.start":
            seen.update({k.decode(): v.decode() for k, v in msg["headers"]})

    import asyncio

    asyncio.run(SecurityHeaders(inner, hsts=False)({"type": "http", "path": "/api/v1/files/x"}, None, capture))
    assert seen["content-security-policy"] == "sandbox; default-src 'none'"
    assert seen["x-content-type-options"] == "nosniff"


def test_hsts_when_served_over_https(settings, engine):
    app = create_app(settings.model_copy(update={"base_url": "https://audit.futran.example"}), engine=engine)
    with TestClient(app) as c:
        r = c.get("/api/v1/health")
    assert r.headers["strict-transport-security"] == "max-age=31536000"


def test_api_responses_are_not_cached(client):
    """Review 11-25 #8: API answers carry client data, so shared caches and the browser's back button don't keep them."""
    for path in ("/api/v1/health", "/api/v1/auth/me"):
        assert client.get(path).headers.get("cache-control") == "no-store", path
    assert client.get("/").headers.get("cache-control") != "no-store"  # the app page itself may be cached


def test_no_redoc_page(client):
    """Review 11-25 #8: the unused ReDoc page got the app policy and broke; it is switched off."""
    r = client.get("/redoc")
    assert "redoc" not in r.text.lower()
