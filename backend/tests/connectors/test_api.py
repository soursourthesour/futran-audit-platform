"""Screen 30 endpoints: who may see, connect and decide; the OAuth round trip through the browser session; Futran's
read-only view; tenant isolation."""
from urllib.parse import parse_qs, urlparse

from app.connectors.models import Connector, DiscoveredTool
from tests.factories import login_as

EXPENSE = b"Employee,Email,Department,Description\nAna Ruiz,ana@abccorp.example,HR,OPENAI *CHATGPT\nBen Ok,ben@abccorp.example,HR,OTTER.AI\n"


def _upload(w, data=EXPENSE, ctype="expense_csv"):
    return w.client.post(f"/api/v1/integrations/{ctype}/upload", files={"file": ("oct.csv", data, "text/csv")})


def test_client_admin_sees_every_connector_and_can_upload(w):
    w.as_(w.admin)
    r = _upload(w)
    assert r.status_code == 200, r.text
    page = w.client.get("/api/v1/integrations").json()
    assert [c["type"] for c in page["connectors"]] == ["okta", "google_workspace", "microsoft_365", "entra_id", "expense_csv", "casb_csv"]
    assert page["can_manage"] and page["can_decide"]
    assert {t["product"] for t in page["tools"]} == {"ChatGPT", "Otter.ai"} and page["summary"]["undeclared"] == 2


def test_caico_reads_but_cannot_connect_or_decide(w):
    w.as_(w.admin)
    _upload(w)
    w.as_(w.caico)
    page = w.client.get("/api/v1/integrations")
    assert page.status_code == 200 and not page.json()["can_manage"] and not page.json()["can_decide"]
    tid = page.json()["tools"][0]["id"]
    assert _upload(w).status_code == 403
    assert w.client.post(f"/api/v1/discovered-tools/{tid}/dismiss", json={"reason": "Not used for work at all"}).status_code == 403
    assert w.client.post("/api/v1/integrations/entra_id/connect", json={}).status_code == 403


def test_contributor_and_department_lead_cannot_open_the_screen(w):
    for u in (w.contrib, w.hr_lead):
        w.as_(u)
        assert w.client.get("/api/v1/integrations").status_code == 403


def test_decisions_through_the_api_and_bulk_dismiss(w):
    w.as_(w.admin)
    _upload(w)
    tools = w.client.get("/api/v1/integrations").json()["tools"]
    chat = next(t for t in tools if t["product"] == "ChatGPT")
    otter = next(t for t in tools if t["product"] == "Otter.ai")
    r = w.client.post(f"/api/v1/discovered-tools/{chat['id']}/confirm")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    r = w.client.post("/api/v1/discovered-tools/bulk", json={"ids": [otter["id"]], "action": "dismiss", "reason": ""})
    assert r.status_code == 422
    r = w.client.post("/api/v1/discovered-tools/bulk", json={"ids": [otter["id"]], "action": "dismiss", "reason": "Free trial during a vendor pitch, cancelled"})
    assert r.status_code == 200 and r.json()["done"] == 1
    page = w.client.get("/api/v1/integrations").json()
    assert {t["product"]: t["status"] for t in page["tools"]} == {"ChatGPT": "confirmed", "Otter.ai": "dismissed"}
    assert any(a["label"] == "OpenAI ChatGPT" for a in page["ai_tools"])


def test_another_client_cannot_touch_these_tools(w):
    w.as_(w.admin)
    _upload(w)
    tid = w.db.query(DiscoveredTool).first().id
    w.as_(w.other_admin)
    assert w.client.post(f"/api/v1/discovered-tools/{tid}/confirm").status_code == 404
    assert w.client.get("/api/v1/integrations").json()["tools"] == []


def test_futran_auditor_reads_the_clients_tools_with_dismiss_reasons(w):
    w.as_(w.admin)
    _upload(w)
    tid = w.db.query(DiscoveredTool).filter_by(product="Otter.ai").one().id
    w.client.post(f"/api/v1/discovered-tools/{tid}/dismiss", json={"reason": "Free trial during a vendor pitch, cancelled"})
    w.as_(w.auditor)
    r = w.client.get(f"/api/v1/clients/{w.org.id}/integrations")
    assert r.status_code == 200 and not r.json()["can_manage"]
    assert next(t for t in r.json()["tools"] if t["product"] == "Otter.ai")["dismiss_reason"].startswith("Free trial")
    w.as_(w.other_auditor)
    assert w.client.get(f"/api/v1/clients/{w.org.id}/integrations").status_code == 404
    w.as_(w.admin)
    assert w.client.get(f"/api/v1/clients/{w.org.id}/integrations").status_code in (403, 404)


def test_people_endpoint_is_for_auditors_only(w):
    w.as_(w.admin)
    _upload(w)
    tid = w.db.query(DiscoveredTool).filter_by(product="ChatGPT").one().id
    assert w.client.get(f"/api/v1/clients/{w.org.id}/discovered-tools/{tid}/people").status_code in (403, 404)
    w.as_(w.auditor)
    r = w.client.get(f"/api/v1/clients/{w.org.id}/discovered-tools/{tid}/people")
    assert r.status_code == 403 and "Tier 2" in r.json()["detail"]


def test_oauth_round_trip_finishes_only_in_the_session_that_started_it(w):
    w.as_(w.admin)
    r = w.client.post("/api/v1/integrations/google_workspace/connect", json={})
    assert r.status_code == 200
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    login_as(w.client, w.db, w.admin)  # a new session for the same person
    bad = w.client.post("/api/v1/connectors/oauth/google/test", json={"state": state, "domain": "abccorp.example"})
    assert bad.status_code == 400 and "same browser" in bad.json()["detail"]
    w.as_(w.admin)
    r = w.client.post("/api/v1/integrations/google_workspace/connect", json={})
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    info = w.client.get(f"/api/v1/connectors/test-consent-info?state={state}").json()
    assert info["organization"] == "ABC Corp" and info["scopes"] and info["label"] == "Google Workspace"
    ok = w.client.post("/api/v1/connectors/oauth/google/test", json={"state": state, "domain": "abccorp.example"})
    assert ok.status_code == 200 and ok.json()["redirect"].startswith("/integrations")
    conn = w.db.query(Connector).filter_by(organization_id=w.org.id, type="google_workspace").one()
    assert conn.status == "connected"
    assert w.client.post("/api/v1/integrations/google_workspace/sync").json()["status"] == "completed"
    assert w.client.post("/api/v1/integrations/google_workspace/disconnect").json()["status"] == "disconnected"


def test_the_provider_callback_without_a_session_lands_on_an_error(w):
    w.as_(w.admin)
    r = w.client.post("/api/v1/integrations/entra_id/connect", json={})
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    w.client.cookies.clear()
    cb = w.client.get(f"/api/v1/connectors/oauth/microsoft?state={state}&admin_consent=True&tenant=x", follow_redirects=False)
    assert cb.status_code == 302 and "error=" in cb.headers["location"] and "/integrations" in cb.headers["location"]


def test_okta_credentials_through_the_api(w):
    w.as_(w.admin)
    r = w.client.post("/api/v1/integrations/okta/credentials", json={"domain": "abccorp.okta.com", "client_id": "cid", "client_secret": "s3cret"})
    assert r.status_code == 200 and r.json()["status"] == "connected" and "s3cret" not in r.text


def test_the_test_consent_page_details_are_for_the_person_who_started_it(w):
    w.as_(w.admin)
    state = parse_qs(urlparse(w.client.post("/api/v1/integrations/entra_id/connect", json={}).json()["url"]).query)["state"][0]
    assert w.client.get(f"/api/v1/connectors/test-consent-info?state={state}").status_code == 200
    w.client.cookies.clear()
    assert w.client.get(f"/api/v1/connectors/test-consent-info?state={state}").status_code == 401  # nobody signed in
    w.as_(w.caico)  # signed in, same organisation, may not manage integrations
    assert w.client.get(f"/api/v1/connectors/test-consent-info?state={state}").status_code == 403
    w.as_(w.other_admin)  # another client's admin
    assert w.client.get(f"/api/v1/connectors/test-consent-info?state={state}").status_code in (400, 403, 404)
    login_as(w.client, w.db, w.admin)  # the same person in another session
    r = w.client.get(f"/api/v1/connectors/test-consent-info?state={state}")
    assert r.status_code == 400 and "same browser" in r.json()["detail"]
