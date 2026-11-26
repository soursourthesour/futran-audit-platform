"""Website library API: the key (X-API-Key or Bearer), CORS per key, per-key rate limits, ETag and Cache-Control."""
import pytest

from app.library.models import WebsiteApiKey
from tests.library.conftest import API, LIB, SITE, hdr, new_key

PATHS = ["/laws", "/cases", "/meta"]


@pytest.mark.parametrize("path", PATHS)
def test_missing_key_is_401_in_the_platform_error_shape(client, libw, path):
    r = client.get(f"{LIB}{path}")
    assert r.status_code == 401
    assert r.json() == {"detail": "Send a website API key in the X-API-Key header.", "errors": []}
    assert r.headers["cache-control"] == "no-store"


def test_wrong_and_revoked_keys_are_401(client, db, libw):
    assert client.get(f"{LIB}/laws", headers=hdr("fwl_not-a-real-key")).status_code == 401
    out = new_key(client, libw)
    k, kid = out["key"], out["website_key"]["id"]
    assert client.get(f"{LIB}/laws", headers=hdr(k)).status_code == 200
    libw.as_(libw.admin)
    assert client.post(f"{API}/admin/website-keys/{kid}/revoke").status_code == 200
    client.cookies.clear()
    r = client.get(f"{LIB}/laws", headers=hdr(k))
    assert r.status_code == 401 and r.json()["detail"] == "This website API key is not valid or has been revoked."


def test_bearer_header_is_accepted_and_last_used_is_recorded(client, db, libw):
    out = new_key(client, libw)
    r = client.get(f"{LIB}/meta", headers={"Authorization": f"Bearer {out['key']}"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(WebsiteApiKey, out["website_key"]["id"]).last_used_at is not None


def test_session_cookie_alone_is_not_enough(client, libw):
    libw.as_(libw.admin)
    assert client.get(f"{LIB}/laws").status_code == 401


# ------------------------------------------------------------------ CORS

def test_preflight_from_an_allowed_origin(client, libw, key):
    r = client.options(f"{LIB}/laws", headers={"Origin": SITE, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-api-key"})
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == SITE
    assert "x-api-key" in r.headers["access-control-allow-headers"].lower()
    assert r.headers["access-control-allow-methods"] == "GET, OPTIONS"
    assert "Origin" in r.headers["vary"]
    assert "access-control-allow-credentials" not in r.headers


def test_preflight_from_another_origin_is_refused(client, libw, key):
    r = client.options(f"{LIB}/laws", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_get_from_allowed_origin_carries_cors_headers(client, libw, key):
    r = client.get(f"{LIB}/laws", headers=hdr(key, Origin=SITE))
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == SITE
    exposed = r.headers["access-control-expose-headers"].lower()
    assert "etag" in exposed and "x-library-last-refreshed" in exposed and "retry-after" in exposed


def test_key_used_from_an_origin_it_does_not_list_is_refused(client, libw, key):
    r = client.get(f"{LIB}/laws", headers=hdr(key, Origin="https://evil.example"))
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers
    assert r.json()["detail"] == "This website API key is not allowed from this origin."


def test_server_side_key_with_no_origins_refuses_browser_calls(client, libw):
    k = new_key(client, libw, name="Website server", origins=())["key"]
    assert client.get(f"{LIB}/laws", headers=hdr(k)).status_code == 200  # server to server: no Origin header
    assert client.get(f"{LIB}/laws", headers=hdr(k, Origin=SITE)).status_code == 403


def test_cors_does_not_leak_to_the_client_public_api(client, libw, key):
    r = client.options("/api/public/v1/me", headers={"Origin": SITE, "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


# ------------------------------------------------------------------ rate limits

def test_rate_limit_per_key_answers_429_with_retry_after(client, libw):
    k = new_key(client, libw, rate=3)["key"]
    other = new_key(client, libw, name="Second site", rate=3)["key"]
    for _ in range(3):
        r = client.get(f"{LIB}/meta", headers=hdr(k))
        assert r.status_code == 200
    assert r.headers["x-ratelimit-limit"] == "3" and r.headers["x-ratelimit-remaining"] == "0"
    r = client.get(f"{LIB}/meta", headers=hdr(k))
    assert r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert r.json() == {"detail": "Too many requests for this website API key. Wait and try again.", "errors": []}
    assert client.get(f"{LIB}/meta", headers=hdr(other)).status_code == 200  # each key has its own allowance


def test_bad_keys_are_rate_limited_per_address(client, libw):
    codes = [client.get(f"{LIB}/meta", headers=hdr(f"fwl_guess{i}")).status_code for i in range(32)]
    assert codes[:30] == [401] * 30 and codes[-1] == 429


# ------------------------------------------------------------------ caching

@pytest.mark.parametrize("path", PATHS)
def test_responses_carry_etag_cache_control_and_last_refreshed(client, libw, key, path):
    r = client.get(f"{LIB}{path}", headers=hdr(key))
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=600"
    assert r.headers["etag"].startswith('"') and r.headers["etag"].endswith('"')
    assert {"origin", "x-api-key", "authorization"} <= {v.strip().lower() for v in r.headers["vary"].split(",")}
    assert r.headers["x-library-last-refreshed"].startswith("20")


def test_if_none_match_answers_304_until_the_data_changes(client, db, libw, key):
    r = client.get(f"{LIB}/cases", headers=hdr(key))
    tag = r.headers["etag"]
    again = client.get(f"{LIB}/cases", headers=hdr(key, **{"If-None-Match": tag}))
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == tag and again.headers["cache-control"].startswith("public")
    assert client.get(f"{LIB}/cases", headers=hdr(key, **{"If-None-Match": f'W/{tag}, "other"'})).status_code == 304
    # a staff edit invalidates the server-side cache and the ETag
    libw.as_(libw.chief)
    assert client.patch(f"{API}/litigation/{libw.case.id}", json={"stage": "trial", "stage_note": "Trial set"}).status_code == 200
    client.cookies.clear()
    fresh = client.get(f"{LIB}/cases", headers=hdr(key, **{"If-None-Match": tag}))
    assert fresh.status_code == 200 and fresh.headers["etag"] != tag
    assert next(c for c in fresh.json()["data"] if c["id"] == libw.case.id)["stage"] == "trial"


def test_etag_differs_by_query(client, libw, key):
    a = client.get(f"{LIB}/laws", headers=hdr(key)).headers["etag"]
    b = client.get(f"{LIB}/laws", params={"region": "eu"}, headers=hdr(key)).headers["etag"]
    assert a != b


def test_server_cache_serves_repeat_queries(client, libw, key, monkeypatch):
    from app.library import content

    calls = []
    real = content.law_list
    monkeypatch.setattr(content, "law_list", lambda *a, **kw: calls.append(1) or real(*a, **kw))
    for _ in range(3):
        assert client.get(f"{LIB}/laws", params={"q": "colorado"}, headers=hdr(key)).status_code == 200
    assert len(calls) == 1


def test_unknown_record_is_404_in_the_platform_shape(client, libw, key):
    for path in ("/laws/nope", "/cases/nope"):
        r = client.get(f"{LIB}{path}", headers=hdr(key))
        assert r.status_code == 404 and r.json() == {"detail": "Not found.", "errors": []}


def test_bad_parameters_are_422(client, libw, key):
    assert client.get(f"{LIB}/laws", params={"limit": 0}, headers=hdr(key)).status_code == 422
    assert client.get(f"{LIB}/laws", params={"limit": 500}, headers=hdr(key)).status_code == 422
    assert client.get(f"{LIB}/laws", params={"sort": "secret"}, headers=hdr(key)).status_code == 422
    assert client.get(f"{LIB}/cases", params={"stage": "hearings"}, headers=hdr(key)).status_code == 422


def test_write_methods_are_not_offered(client, libw, key):
    assert client.post(f"{LIB}/laws", headers=hdr(key), json={}).status_code == 405
    assert client.delete(f"{LIB}/cases/{libw.case.id}", headers=hdr(key)).status_code == 405
