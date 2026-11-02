"""The Microsoft tenant a connector reads is proven by the person who connects it, not taken from the consent redirect.

Microsoft's admin-consent redirect names a tenant in its query string; anyone holding a valid state can edit it. After
admin consent the platform signs the administrator in (OpenID Connect, authorization code) and takes the tenant from the
ID token's `tid`, which must match the tenant that gave consent. The organisation's own domains count only the users
who have accepted their invitation and signed in. Every request goes to an httpx.MockTransport."""
import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.connectors import service as svc
from app.connectors.adapters.fake import FAKE
from app.connectors.adapters.microsoft import MicrosoftAdapter
from app.core.errors import AppError
from tests.factories import make_user

LOGIN = "https://login.microsoftonline.com"


def _id_token(claims: dict) -> str:
    return "h." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".s"


def _q(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


class World:
    """Two tenants have consented to the shared multi-tenant discovery app: ABC Corp's own and Other Co's."""

    def __init__(self, signed_in_tid: str, **overrides):
        self.signed_in_tid, self.overrides, self.calls = signed_in_tid, overrides, []
        self.domains = {"abc-tenant": "abccorp.example", "victim-tenant": "otherco.example"}

    def handler(self, req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        self.calls.append(u)
        if u == f"{LOGIN}/organizations/oauth2/v2.0/token":
            body = parse_qs(req.content.decode())
            assert body["grant_type"] == ["authorization_code"] and body["code"] == ["the-code"]
            tid = self.signed_in_tid
            claims = {"aud": "cid", "iss": f"{LOGIN}/{tid}/v2.0", "tid": tid, "nonce": self.nonce, "exp": int(time.time()) + 600, **self.overrides}
            return httpx.Response(200, json={"access_token": "user-token", "id_token": _id_token(claims)})
        for tenant, domain in self.domains.items():
            if u == f"{LOGIN}/{tenant}/oauth2/v2.0/token":
                return httpx.Response(200, json={"access_token": f"app-{tenant}"})
        if "/organization" in u:
            tenant = req.headers["Authorization"].split("app-", 1)[1]
            return httpx.Response(200, json={"value": [{"displayName": tenant, "verifiedDomains": [{"name": self.domains[tenant]}]}]})
        return httpx.Response(200, json={"value": []})


@pytest.fixture
def live(settings, monkeypatch):
    settings.discovery_ms_client_id, settings.discovery_ms_client_secret = "cid", "sec"

    def make(signed_in_tid: str, **overrides) -> World:
        world = World(signed_in_tid, **overrides)
        ad = MicrosoftAdapter(settings, "entra_id", transport=httpx.MockTransport(world.handler))
        monkeypatch.setattr(svc, "get_adapter", lambda s, t: ad)
        return world

    return make


def _consent(w, settings, world: World, tenant: str):
    """Admin consent comes back naming `tenant`; the platform answers with the sign-in that proves it."""
    url = svc.start_consent(w.db, settings, w.admin, "sess-1", w.org, "entra_id")
    assert "/adminconsent?" in url
    nxt = svc.complete_consent(w.db, settings, "microsoft", {"state": _q(url)["state"], "tenant": tenant, "admin_consent": "True"}, session_id="sess-1", user_id=w.admin.id)
    assert isinstance(nxt, str) and nxt.startswith(f"{LOGIN}/organizations/oauth2/v2.0/authorize?")
    q = _q(nxt)
    assert q["response_type"] == "code" and q["scope"] == "openid" and q["client_id"] == "cid" and q["nonce"]
    world.nonce = q["nonce"]
    return q["state"]


def test_a_tenant_edited_into_the_consent_redirect_is_not_connected(w, settings, live):
    world = live("abc-tenant")  # the attacker's own administrator signs in to their own tenant
    make_user(w.db, w.org, roles=["contributor"], name="Plant", email="plant@otherco.example")
    st = _consent(w, settings, world, "victim-tenant")
    conn = svc.connector(w.db, w.org, "entra_id")
    assert conn.status != "connected" and conn.tenant_id is None
    with pytest.raises(AppError) as exc:
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "code": "the-code", "tenant": "victim-tenant"}, session_id="sess-1", user_id=w.admin.id)
    assert "different Microsoft tenant" in str(exc.value.detail)
    assert conn.status != "connected" and conn.tenant_id is None and conn.token_encrypted is None
    assert not any("/victim-tenant/" in u for u in world.calls)  # no app token was even asked for


def test_the_tenant_the_administrator_signs_in_to_is_connected(w, settings, live):
    world = live("abc-tenant")
    st = _consent(w, settings, world, "abc-tenant")
    conn = svc.complete_consent(w.db, settings, "microsoft", {"state": st, "code": "the-code"}, session_id="sess-1", user_id=w.admin.id)
    assert conn.status == "connected" and conn.tenant_id == "abc-tenant" and conn.verified_domains == ["abccorp.example"]


@pytest.mark.parametrize("bad", [{"aud": "someone-else"}, {"nonce": "replayed"}, {"iss": f"{LOGIN}/victim-tenant/v2.0"}, {"exp": 1},
                                 {"idp": "https://sts.windows.net/home-tenant/"}])
def test_an_id_token_that_does_not_check_out_is_refused(w, settings, live, bad):
    world = live("abc-tenant", **bad)
    st = _consent(w, settings, world, "abc-tenant")
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "code": "the-code"}, session_id="sess-1", user_id=w.admin.id)
    assert svc.connector(w.db, w.org, "entra_id").status != "connected"


def test_the_sign_in_step_is_bound_to_the_same_session_and_used_once(w, settings, live):
    world = live("abc-tenant")
    st = _consent(w, settings, world, "abc-tenant")
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "code": "the-code"}, session_id="another-session", user_id=w.admin.id)
    svc.complete_consent(w.db, settings, "microsoft", {"state": st, "code": "the-code"}, session_id="sess-1", user_id=w.admin.id)
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "code": "the-code"}, session_id="sess-1", user_id=w.admin.id)


def test_the_provider_callback_sends_the_browser_on_to_the_sign_in(w, settings, live):
    live("abc-tenant")
    w.as_(w.admin)
    state = _q(w.client.post("/api/v1/integrations/entra_id/connect", json={}).json()["url"])["state"]
    cb = w.client.get(f"/api/v1/connectors/oauth/microsoft?state={state}&admin_consent=True&tenant=abc-tenant", follow_redirects=False)
    assert cb.status_code == 302 and cb.headers["location"].startswith(f"{LOGIN}/organizations/oauth2/v2.0/authorize?")


def test_invited_users_who_never_signed_in_do_not_make_a_domain_the_organisations(w, settings):
    make_user(w.db, w.org, roles=["contributor"], name="Plant", email="plant@otherco.example", status="invited")
    assert "otherco.example" not in svc.own_domains(w.db, w.org) and "abccorp.example" in svc.own_domains(w.db, w.org)
    FAKE.tenants["other-tenant"] = ["otherco.example"]
    url = svc.start_consent(w.db, settings, w.admin, "sess-1", w.org, "entra_id")
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": _q(url)["state"], "tenant": "other-tenant"}, session_id="sess-1", user_id=w.admin.id)
