"""The live adapters call only the documented read endpoints, with read-only scopes, and turn the replies into signals.
Every request goes to an httpx.MockTransport: nothing touches the network."""
import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx

from app.connectors.adapters.google import SCOPES as G_SCOPES, GoogleAdapter
from app.connectors.adapters.microsoft import MicrosoftAdapter
from app.connectors.adapters.okta import OktaAdapter


def _mock(handler, calls):
    def h(req: httpx.Request):
        calls.append((req.method, str(req.url)))
        return handler(req)

    return httpx.MockTransport(h)


def test_okta_reads_apps_and_assignments_with_read_scopes(settings):
    calls = []

    def handler(req):
        u = str(req.url)
        if u.endswith("/oauth2/v1/token"):
            body = parse_qs(req.content.decode())
            assert body["grant_type"] == ["client_credentials"] and body["scope"] == ["okta.apps.read okta.users.read"]
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "/api/v1/users" in u:
            return httpx.Response(200, json=[{"id": "u1", "profile": {"email": "ana@abccorp.example", "firstName": "Ana", "lastName": "Ruiz", "department": "HR"}}])
        if "/api/v1/apps/a1/users" in u:
            return httpx.Response(200, json=[{"id": "u1"}])
        if "/api/v1/apps" in u:
            return httpx.Response(200, json=[{"id": "a1", "label": "HireVue", "signOnMode": "SAML_2_0"}, {"id": "a2", "label": "Workday", "signOnMode": "SAML_2_0"}])
        return httpx.Response(404)

    a = OktaAdapter(settings, transport=_mock(handler, calls))
    grant = a.connect(domain="abccorp.okta.com", client_id="cid", client_secret="sec")
    assert grant["domains"] == ["abccorp.example"]
    sigs = a.collect(grant)
    assert [(s.vendor_key, s.signal, s.department, s.person) for s in sigs] == [("hirevue", "sso_app", "HR", "ana@abccorp.example")]
    assert all(m == "GET" for m, u in calls if "/api/v1/" in u)
    assert not any("/apps/a2/users" in u for _, u in calls)


def test_microsoft_entra_reads_service_principals_and_permission_grants(settings):
    settings.discovery_ms_client_id, settings.discovery_ms_client_secret = "cid", "sec"
    calls = []

    def handler(req):
        u = str(req.url)
        if "/oauth2/v2.0/token" in u:
            assert parse_qs(req.content.decode())["scope"] == ["https://graph.microsoft.com/.default"]
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "/users" in u and "/servicePrincipals" not in u:
            return httpx.Response(200, json={"value": [{"id": "p1", "displayName": "Ana Ruiz", "mail": "ana@abccorp.example", "department": "Finance"}]})
        if "/appRoleAssignedTo" in u:
            return httpx.Response(200, json={"value": [{"principalType": "User", "principalId": "p1"}, {"principalType": "Group", "principalId": "g1"}]})
        if "/servicePrincipals" in u:
            return httpx.Response(200, json={"value": [{"id": "sp1", "displayName": "ChatGPT Enterprise"}, {"id": "sp2", "displayName": "Contoso HR"}]})
        if "/oauth2PermissionGrants" in u:
            assert "clientId" in u
            return httpx.Response(200, json={"value": [{"consentType": "Principal", "principalId": "p1", "scope": "User.Read openid"}]})
        return httpx.Response(404)

    a = MicrosoftAdapter(settings, "entra_id", transport=_mock(handler, calls))
    sigs = a.collect({"tenant": "t1"})
    assert {(s.vendor_key, s.signal, s.department, s.detail) for s in sigs} == {("openai_chatgpt", "sso_app", "Finance", None), ("openai_chatgpt", "oauth_grant", "Finance", "User.Read, openid")}
    assert all(m == "GET" for m, u in calls if "graph.microsoft.com" in u)


def test_microsoft_365_reads_copilot_licences_and_usage(settings):
    settings.discovery_ms_client_id, settings.discovery_ms_client_secret = "cid", "sec"
    calls = []

    def handler(req):
        u = str(req.url)
        if "/oauth2/v2.0/token" in u:
            return httpx.Response(200, json={"access_token": "t"})
        if "/subscribedSkus" in u:
            return httpx.Response(200, json={"value": [{"skuPartNumber": "Microsoft_365_Copilot", "consumedUnits": 3}, {"skuPartNumber": "SPE_E5", "consumedUnits": 400}]})
        if "getMicrosoft365CopilotUsageUserDetail" in u:
            return httpx.Response(200, json={"value": [{"userPrincipalName": "ana@abccorp.example", "lastActivityDate": "2026-10-30"}]})
        if "/users" in u:
            return httpx.Response(200, json={"value": [{"id": "p1", "userPrincipalName": "ana@abccorp.example", "department": "Finance"}]})
        return httpx.Response(404)

    sigs = MicrosoftAdapter(settings, "microsoft_365", transport=_mock(handler, calls)).collect({"tenant": "t1"})
    assert len(sigs) == 3 and sigs[0].department == "Finance" and all(s.vendor_key == "microsoft_copilot" and s.signal == "licence" for s in sigs)
    assert any("/copilot/reports/getMicrosoft365CopilotUsageUserDetail(period='D30')" in u for _, u in calls)


def test_microsoft_admin_consent_proves_the_tenant_and_reads_its_domains(settings):
    settings.discovery_ms_client_id, settings.discovery_ms_client_secret = "cid", "sec"

    def handler(req):
        u = str(req.url)
        if "/t9/oauth2/v2.0/token" in u:
            return httpx.Response(200, json={"access_token": "t"})
        if u.endswith("/organization?$select=displayName,verifiedDomains") or "/organization" in u:
            return httpx.Response(200, json={"value": [{"displayName": "ABC", "verifiedDomains": [{"name": "ABCcorp.example"}]}]})
        return httpx.Response(400, json={"error": "invalid_client"})

    a = MicrosoftAdapter(settings, "entra_id", transport=httpx.MockTransport(handler))
    url = a.consent_url(state="s")
    assert "/adminconsent?" in url and "graph.microsoft.com%2F.default" in url and settings.discovery_ms_client_id in url
    g = a.complete_consent(params={"tenant": "t9", "admin_consent": "True"})
    assert g["tenant"] == "t9" and g["domains"] == ["abccorp.example"]


def _id_token(claims):
    return "x." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".y"


def test_google_consent_needs_every_read_only_scope_and_a_workspace_domain(settings):
    settings.discovery_google_client_id, settings.discovery_google_client_secret = "cid", "sec"
    replies = iter([
        {"access_token": "a", "refresh_token": "r", "scope": " ".join(G_SCOPES), "id_token": _id_token({"email": "admin@abccorp.example", "hd": "abccorp.example"})},
        {"access_token": "a", "scope": G_SCOPES[0], "id_token": _id_token({"hd": "abccorp.example"})},
    ])
    a = GoogleAdapter(settings, transport=httpx.MockTransport(lambda req: httpx.Response(200, json=next(replies))))
    url = a.consent_url(state="s")
    q = parse_qs(urlparse(url).query)
    assert q["access_type"] == ["offline"] and set(q["scope"][0].split()) == {"openid", "email", *G_SCOPES}
    g = a.complete_consent(params={"code": "c"})
    assert g["tenant"] == "abccorp.example" and g["account"] == "admin@abccorp.example"
    import pytest

    from app.connectors.adapters import ConnectorError

    with pytest.raises(ConnectorError):
        a.complete_consent(params={"code": "c"})


def test_google_reads_token_grants_and_gemini_use(settings):
    settings.discovery_google_client_id, settings.discovery_google_client_secret = "cid", "sec"
    calls = []

    def handler(req):
        u = str(req.url)
        if "/directory/v1/users" in u:
            return httpx.Response(200, json={"users": [{"primaryEmail": "ana@abccorp.example", "name": {"fullName": "Ana Ruiz"}, "organizations": [{"department": "Operations"}]}]})
        if "/applications/token" in u:
            assert "eventName=authorize" in u
            return httpx.Response(200, json={"items": [{"actor": {"email": "ana@abccorp.example"}, "events": [{"name": "authorize", "parameters": [
                {"name": "app_name", "value": "Otter.ai"}, {"name": "scope", "multiValue": ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/drive.file"]}]}]}]})
        if "/applications/gemini_in_workspace_apps" in u:
            return httpx.Response(200, json={"items": [{"actor": {"email": "ana@abccorp.example"}}]})
        return httpx.Response(404)

    sigs = GoogleAdapter(settings, transport=_mock(handler, calls)).collect({"access_token": "a", "expires_at": 9e12})
    assert {(s.vendor_key, s.signal, s.department, s.detail) for s in sigs} == {("otter", "oauth_grant", "Operations", "calendar, drive"),
                                                                             ("google_gemini", "licence", "Operations", "Gemini in Workspace apps")}
    assert all(m == "GET" for m, _ in calls)
