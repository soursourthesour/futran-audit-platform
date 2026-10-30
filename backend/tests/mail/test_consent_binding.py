"""Security review C1 and I1: a consent response binds only a tenant or mailbox that belongs to the organisation or user
that asked for it."""
import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.errors import AppError
from app.mail import connections as cx
from app.mail.models import AdminLogEntry, MailConnection
from app.mail.providers.fake import FAKE
from tests.factories import login_as, make_org, make_user


@pytest.fixture(autouse=True)
def _reset():
    FAKE.reset()
    yield
    FAKE.reset()


def _state(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def _live_microsoft(monkeypatch, settings, tenants: dict[str, list[str]]):
    """Live Microsoft mode against a mock Graph: `tenants` maps each tenant that has consented to its verified domains."""
    settings.mail_provider_mode = "live"
    settings.ms_client_id, settings.ms_client_secret = "cid", "secret"

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.startswith("https://login.microsoftonline.com/") and url.endswith("/oauth2/v2.0/token"):
            tenant = url.split("/")[3]
            if tenant not in tenants:
                return httpx.Response(400, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": f"tok-{tenant}", "expires_in": 3600})
        tenant = req.headers["Authorization"].split("tok-", 1)[1]
        if url.endswith("/organization"):
            return httpx.Response(200, json={"value": [{"displayName": tenant, "verifiedDomains": [{"name": d} for d in tenants[tenant]]}]})
        return httpx.Response(404)

    import app.mail.providers.microsoft as ms

    monkeypatch.setattr(ms, "client", lambda transport=None: httpx.Client(transport=httpx.MockTransport(handler)))


def _client_a(db):
    make_org(db, type="futran")
    a = make_org(db, name="Client A")
    admin = make_user(db, a, roles=["client_admin"], email="it@clienta.com")
    return a, admin


# ---------------------------------------------------------------- C1: Microsoft admin consent
def test_admin_consent_refuses_a_tenant_that_does_not_own_the_organisations_domain(db, settings, monkeypatch):
    _live_microsoft(monkeypatch, settings, {"tenant-b": ["clientb.com"]})
    a, admin = _client_a(db)
    conn = cx.org_connection(db, a, create=True)
    url = cx.start_consent(db, settings, admin, conn, provider="microsoft365", kind="admin", mailbox="ai@clienta.com")
    with pytest.raises(AppError) as exc:
        cx.complete_consent(db, settings, "microsoft365", {"state": _state(url), "admin_consent": "True", "tenant": "tenant-b"})
    assert "clienta.com" in str(exc.value.errors or exc.value.detail)
    assert conn.status != "connected" and conn.tenant_id is None and conn.token_encrypted is None
    assert db.query(AdminLogEntry).filter_by(organization_id=a.id, action="consent_failed").count() == 1


def test_admin_consent_stores_the_tenants_verified_domains(db, settings, monkeypatch):
    _live_microsoft(monkeypatch, settings, {"tenant-a": ["clienta.com", "clienta.onmicrosoft.com"]})
    a, admin = _client_a(db)
    conn = cx.org_connection(db, a, create=True)
    url = cx.start_consent(db, settings, admin, conn, provider="microsoft365", kind="admin", mailbox="ai@clienta.com")
    cx.complete_consent(db, settings, "microsoft365", {"state": _state(url), "admin_consent": "True", "tenant": "tenant-a"})
    assert conn.status == "connected" and conn.tenant_id == "tenant-a"
    assert conn.verified_domains == ["clienta.com", "clienta.onmicrosoft.com"]


def test_admin_consent_refuses_a_sending_mailbox_outside_the_tenants_verified_domains(db, settings, monkeypatch):
    _live_microsoft(monkeypatch, settings, {"tenant-a": ["clienta.com"]})
    a, admin = _client_a(db)
    conn = cx.org_connection(db, a, create=True)
    url = cx.start_consent(db, settings, admin, conn, provider="microsoft365", kind="admin", mailbox="ceo@clientb.com")
    with pytest.raises(AppError):
        cx.complete_consent(db, settings, "microsoft365", {"state": _state(url), "admin_consent": "True", "tenant": "tenant-a"})
    assert conn.status != "connected" and conn.token_encrypted is None


def test_admin_consent_refuses_a_tenant_already_bound_to_another_organisation(db, settings, monkeypatch):
    _live_microsoft(monkeypatch, settings, {"tenant-shared": ["clienta.com", "clientb.com"]})
    a, admin = _client_a(db)
    b = make_org(db, name="Client B")
    make_user(db, b, roles=["client_admin"], email="it@clientb.com")
    db.add(MailConnection(organization_id=b.id, owner="client", provider="microsoft365", tenant_id="tenant-shared", mailbox_address="ai@clientb.com", status="connected"))
    db.flush()
    conn = cx.org_connection(db, a, create=True)
    url = cx.start_consent(db, settings, admin, conn, provider="microsoft365", kind="admin", mailbox="ai@clienta.com")
    with pytest.raises(AppError) as exc:
        cx.complete_consent(db, settings, "microsoft365", {"state": _state(url), "admin_consent": "True", "tenant": "tenant-shared"})
    assert "another organisation" in str(exc.value.errors or exc.value.detail)
    assert conn.status != "connected" and conn.tenant_id is None


def test_the_fake_provider_refuses_a_tenant_outside_the_organisations_domain(client, db, settings):
    """Test mode models the same rule: the fake tenant's verified domain comes from the mailbox the consent page names."""
    a, admin = _client_a(db)
    db.commit()
    login_as(client, db, admin)
    start = client.post("/api/v1/mail/client/connect", json={"provider": "microsoft365", "mailbox_address": "ai@clienta.com"}).json()
    r = client.post("/api/v1/mail/oauth/microsoft365/test", json={"state": _state(start["url"]), "mailbox": "ceo@clientb.com"})
    assert r.status_code == 400, r.text
    db.expire_all()
    assert cx.org_connection(db, a).status != "connected"


def test_the_fake_provider_refuses_a_named_tenant_whose_domains_do_not_match(db, settings):
    FAKE.add_tenant("fake-tenant-b", ["clientb.com"])
    a, admin = _client_a(db)
    conn = cx.org_connection(db, a, create=True)
    url = cx.start_consent(db, settings, admin, conn, provider="microsoft365", kind="admin", mailbox="ai@clienta.com")
    with pytest.raises(AppError):
        cx.complete_consent(db, settings, "microsoft365", {"state": _state(url), "admin_consent": "True", "tenant": "fake-tenant-b", "mailbox": "ai@clienta.com"})
    assert conn.status != "connected"


def test_a_mailbox_change_outside_the_verified_domains_is_refused(client, db, settings):
    a, admin = _client_a(db)
    db.commit()
    login_as(client, db, admin)
    start = client.post("/api/v1/mail/client/connect", json={"provider": "microsoft365", "mailbox_address": "ai@clienta.com"}).json()
    assert client.post("/api/v1/mail/oauth/microsoft365/test", json={"state": _state(start["url"]), "mailbox": "ai@clienta.com"}).status_code == 200
    r = client.patch("/api/v1/mail/client/connection", json={"mailbox_address": "ceo@clientb.com"})
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["field"] == "mailbox_address"
    ok = client.patch("/api/v1/mail/client/connection", json={"mailbox_address": "governance@clienta.com"})
    assert ok.status_code == 200, ok.text
    db.expire_all()
    assert cx.org_connection(db, a).mailbox_address == "governance@clienta.com"


# ---------------------------------------------------------------- C1: Google
def _id_token(claims: dict) -> str:
    def part(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.sig"


def _live_google(monkeypatch, settings, email: str, hd: str | None):
    settings.mail_provider_mode = "live"
    settings.google_client_id, settings.google_client_secret = "gid", "gsecret"

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://oauth2.googleapis.com/token":
            claims = {"email": email, **({"hd": hd} if hd else {})}
            return httpx.Response(200, json={"access_token": "g-tok", "refresh_token": "g-ref", "expires_in": 3600, "id_token": _id_token(claims)})
        if url.endswith("/users/me/profile"):
            return httpx.Response(200, json={"emailAddress": email})
        return httpx.Response(404)

    import app.mail.providers.google as g

    monkeypatch.setattr(g, "client", lambda transport=None: httpx.Client(transport=httpx.MockTransport(handler)))


def test_google_consent_refuses_an_account_outside_the_organisations_domain(db, settings, monkeypatch):
    _live_google(monkeypatch, settings, "someone@gmail.com", None)
    a, admin = _client_a(db)
    conn = cx.org_connection(db, a, create=True)
    url = cx.start_consent(db, settings, admin, conn, provider="google", kind="admin", mailbox="ai@clienta.com")
    with pytest.raises(AppError):
        cx.complete_consent(db, settings, "google", {"state": _state(url), "code": "c"})
    assert conn.status != "connected" and conn.token_encrypted is None


def test_google_consent_accepts_the_organisations_hosted_domain(db, settings, monkeypatch):
    _live_google(monkeypatch, settings, "ai@clienta.com", "clienta.com")
    a, admin = _client_a(db)
    conn = cx.org_connection(db, a, create=True)
    url = cx.start_consent(db, settings, admin, conn, provider="google", kind="admin", mailbox="ai@clienta.com")
    cx.complete_consent(db, settings, "google", {"state": _state(url), "code": "c"})
    assert conn.status == "connected" and conn.mailbox_address == "ai@clienta.com" and conn.verified_domains == ["clienta.com"]


# ---------------------------------------------------------------- I1: the personal mailbox is bound to the browser and the user
def _start_user(client, db, user):
    login_as(client, db, user)
    r = client.post("/api/v1/me/mailbox/connect", json={"provider": "microsoft365"})
    assert r.status_code == 200, r.text
    return _state(r.json()["url"])


def test_personal_mailbox_consent_needs_the_session_that_started_it(client, db, settings):
    make_org(db, type="futran")
    a = make_org(db, name="Client A")
    u = make_user(db, a, roles=["contributor"], email="junior@clienta.com")
    other = make_user(db, a, roles=["contributor"], email="other@clienta.com")
    db.commit()
    state = _start_user(client, db, u)
    login_as(client, db, other)  # a different signed-in session completes it
    r = client.post("/api/v1/mail/oauth/microsoft365/test", json={"state": state, "mailbox": "junior@clienta.com"})
    assert r.status_code == 400 and "same browser" in r.json()["detail"]
    client.cookies.clear()  # and no session at all
    r = client.post("/api/v1/mail/oauth/microsoft365/test", json={"state": state, "mailbox": "junior@clienta.com"})
    assert r.status_code == 400
    db.expire_all()
    assert cx.user_connection(db, u).status != "connected"


def test_personal_mailbox_must_be_the_users_own_address(client, db, settings):
    make_org(db, type="futran")
    a = make_org(db, name="Client A")
    u = make_user(db, a, roles=["contributor"], email="Junior@ClientA.com")
    db.commit()
    state = _start_user(client, db, u)
    r = client.post("/api/v1/mail/oauth/microsoft365/test", json={"state": state, "mailbox": "ceo@clienta.com"})
    assert r.status_code == 400 and "junior@clienta.com" in r.json()["detail"].lower()
    db.expire_all()
    assert cx.user_connection(db, u).status != "connected"
    state = _start_user(client, db, u)
    r = client.post("/api/v1/mail/oauth/microsoft365/test", json={"state": state, "mailbox": "JUNIOR@clienta.com"})
    assert r.status_code == 200, r.text
    db.expire_all()
    uc = cx.user_connection(db, u)
    assert uc.status == "connected" and uc.mailbox == "junior@clienta.com"


def test_personal_mailbox_callback_needs_the_session_cookie(client, db, settings):
    """The real provider redirect (GET) is checked the same way: without the session it lands on the error page."""
    make_org(db, type="futran")
    a = make_org(db, name="Client A")
    u = make_user(db, a, roles=["contributor"], email="junior@clienta.com")
    db.commit()
    state = _start_user(client, db, u)
    client.cookies.clear()
    r = client.get("/api/v1/mail/oauth/microsoft365", params={"state": state, "mailbox": "junior@clienta.com", "code": "x"}, follow_redirects=False)
    assert r.status_code == 302 and "/mail/consent-result?error=" in r.headers["location"]
    db.expire_all()
    assert cx.user_connection(db, u).status != "connected"
