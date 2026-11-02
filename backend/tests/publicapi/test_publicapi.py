"""F17: the public API (spec §21 F17). OAuth 2.0 client credentials, scoped to the API client's organization, released items
only, hashed secrets shown once, rate limited, every call audit-logged."""
import hashlib

import pytest
from sqlalchemy import func, select

from app.audit_log.models import AuditLog
from app.comments.models import Comment
from app.publicapi.models import ApiClient, ApiToken
from app.register.models import ChangeLog, RegisterSystem
from tests.comments.conftest import w  # noqa: F401

API = "/api/v1"
PUB = "/api/public/v1"
ALL = ["inventory:read", "inventory:write", "usecases:write", "attestation:read", "findings:read", "remediation:read", "updates:read"]


def make_client(client, w, user=None, scopes=ALL, name="ServiceNow GRC sync", **kw):
    w.as_(user or w.cadmin)
    r = client.post(f"{API}/admin/api/clients", json={"name": name, "scopes": scopes, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def token(client, creds, scope=None):
    data = {"grant_type": "client_credentials", "client_id": creds["client"]["client_id"], "client_secret": creds["client_secret"]}
    if scope:
        data["scope"] = scope
    client.cookies.clear()
    r = client.post(f"{PUB}/oauth/token", data=data)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def abc(client, w):
    creds = make_client(client, w)
    return creds, token(client, creds)


def test_secret_is_shown_once_and_stored_hashed(client, db, w):
    creds = make_client(client, w)
    secret = creds["client_secret"]
    assert secret and creds["client"]["scopes"] == ALL
    row = db.get(ApiClient, creds["client"]["id"])
    assert row.secret_hash == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in str([getattr(row, c.key) for c in row.__table__.columns])
    listing = client.get(f"{API}/admin/api").json()
    assert secret not in str(listing) and listing["clients"][0]["secret_hint"] == secret[-4:]
    rotated = client.post(f"{API}/admin/api/clients/{row.id}/rotate-secret").json()
    assert rotated["client_secret"] != secret
    client.cookies.clear()
    bad = client.post(f"{PUB}/oauth/token", data={"grant_type": "client_credentials", "client_id": row.client_id, "client_secret": secret})
    assert bad.status_code == 401 and bad.json()["error"] == "invalid_client"


def test_only_the_client_admin_manages_api_clients(client, w):
    for user, code in ((w.caico, 403), (w.hr_lead, 403), (w.aud, 404), (w.chief, 404)):
        w.as_(user)
        assert client.post(f"{API}/admin/api/clients", json={"name": "x", "scopes": ["findings:read"]}).status_code == code, user.name
    w.as_(w.caico)  # the CAICO may look
    assert client.get(f"{API}/admin/api").status_code == 200
    w.as_(w.cadmin)
    assert client.post(f"{API}/admin/api/clients", json={"name": "x", "scopes": ["everything:write"]}).status_code == 422
    creds = make_client(client, w)
    w.as_(w.x_admin)  # another tenant
    assert client.get(f"{API}/admin/api").json()["clients"] == []
    assert client.post(f"{API}/admin/api/clients/{creds['client']['id']}/revoke").status_code == 404


def test_token_endpoint_follows_client_credentials(client, db, w):
    creds = make_client(client, w, scopes=["findings:read"])
    client.cookies.clear()
    cid = creds["client"]["client_id"]
    r = client.post(f"{PUB}/oauth/token", data={"grant_type": "password", "client_id": cid, "client_secret": creds["client_secret"]})
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"
    r = client.post(f"{PUB}/oauth/token", data={"grant_type": "client_credentials", "client_id": cid, "client_secret": "nope"})
    assert r.status_code == 401 and r.json()["error"] == "invalid_client"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "public_api.token_refused", AuditLog.organization_id == w.org.id)) is not None
    r = client.post(f"{PUB}/oauth/token", data={"grant_type": "client_credentials", "client_id": cid, "client_secret": creds["client_secret"], "scope": "inventory:write"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_scope"
    r = client.post(f"{PUB}/oauth/token", auth=(cid, creds["client_secret"]), data={"grant_type": "client_credentials"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 3600 and body["scope"] == "findings:read"
    assert db.scalar(select(ApiToken).where(ApiToken.token_hash == hashlib.sha256(body["access_token"].encode()).hexdigest())) is not None
    assert r.headers.get("cache-control") == "no-store"


def test_cookies_never_authenticate_the_public_api(client, w, abc):
    _, t = abc
    w.as_(w.caico)  # a signed-in browser session with a CSRF token
    assert client.get(f"{PUB}/findings").status_code == 401
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    assert client.get(f"{API}/register", headers=bearer(t)).status_code == 401  # the session API ignores bearer tokens
    assert client.get(f"{PUB}/findings", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get(f"{PUB}/findings", headers=bearer(t)).status_code == 200


def test_scopes_are_enforced(client, w):
    creds = make_client(client, w, scopes=["inventory:read"])
    t = token(client, creds)
    r = client.get(f"{PUB}/findings", headers=bearer(t))
    assert r.status_code == 403 and r.json()["error"] == "insufficient_scope"
    assert client.get(f"{PUB}/inventory/systems", headers=bearer(t)).status_code == 200


def test_findings_are_released_items_of_the_own_organization_with_shared_comments_only(client, db, w, abc):
    _, t = abc
    db.add_all([Comment(organization_id=w.org.id, engagement_id=w.e.id, object_type="finding", object_id=w.finding.id, author_id=w.aud.id, author_side="futran",
                        visibility="internal", body="Internal: the vendor is evasive."),
                Comment(organization_id=w.org.id, engagement_id=w.e.id, object_type="finding", object_id=w.finding.id, author_id=w.aud.id, author_side="futran",
                        visibility="shared", body="Please send the vendor report.")])
    db.commit()
    rows = client.get(f"{PUB}/findings", headers=bearer(t)).json()["data"]
    assert [f["ref"] for f in rows] == ["F-001"]  # the draft F-002 and XYZ's finding are not there
    one = client.get(f"{PUB}/findings/{w.finding.id}", headers=bearer(t)).json()
    assert [c["body"] for c in one["comments"]] == ["Please send the vendor report."]
    assert "evasive" not in client.get(f"{PUB}/findings/{w.finding.id}", headers=bearer(t)).text
    assert client.get(f"{PUB}/findings/{w.draft.id}", headers=bearer(t)).status_code == 404
    assert client.get(f"{PUB}/findings/{w.x_finding.id}", headers=bearer(t)).status_code == 404
    w.e.stage = 6  # before the draft report nothing is released
    db.commit()
    assert client.get(f"{PUB}/findings", headers=bearer(t)).json()["data"] == []


def test_another_tenant_token_sees_only_its_own_data(client, w, abc):
    xcreds = make_client(client, w, user=w.x_admin)
    xt = token(client, xcreds)
    assert [f["ref"] for f in client.get(f"{PUB}/findings", headers=bearer(xt)).json()["data"]] == ["F-001"]
    assert client.get(f"{PUB}/findings/{w.finding.id}", headers=bearer(xt)).status_code == 404
    assert client.get(f"{PUB}/remediation", headers=bearer(xt)).json()["data"] == []


def test_remediation_status(client, w, abc):
    _, t = abc
    rows = client.get(f"{PUB}/remediation", headers=bearer(t)).json()["data"]
    assert len(rows) == 1 and rows[0]["status"] == "open" and rows[0]["finding_ref"] == "F-001" and rows[0]["due_date"]


def test_inventory_read_and_write_go_through_the_register(client, db, w, abc):
    _, t = abc
    r = client.post(f"{PUB}/inventory/systems", headers=bearer(t), json={"name": "Claims triage assistant", "type": "genai_chat_tool", "sourcing": "vendor",
                                                                       "department_id": w.fin.id, "purpose": "Drafts replies to routine claims questions.", "vendor_name": "Acme AI"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    s = db.get(RegisterSystem, sid)
    assert s.organization_id == w.org.id and s.stage == "proposed" and s.origin == "api"
    log = db.scalar(select(ChangeLog).where(ChangeLog.register_system_id == sid, ChangeLog.field == "created"))
    assert "ServiceNow GRC sync" in (log.reason or "")
    assert client.post(f"{PUB}/inventory/systems", headers=bearer(t), json={"name": ""}).status_code == 422
    p = client.patch(f"{PUB}/inventory/systems/{sid}", headers=bearer(t), json={"purpose": "Drafts replies to routine claims questions for adjusters."})
    assert p.status_code == 200 and p.json()["purpose"].endswith("adjusters.")
    assert client.patch(f"{PUB}/inventory/systems/{sid}", headers=bearer(t), json={"stage": "live"}).status_code == 422  # go-live has its own gate
    names = [x["name"] for x in client.get(f"{PUB}/inventory/systems", headers=bearer(t)).json()["data"]]
    assert "Claims triage assistant" in names
    xt = token(client, make_client(client, w, user=w.x_admin))
    assert client.patch(f"{PUB}/inventory/systems/{sid}", headers=bearer(xt), json={"purpose": "x"}).status_code == 404
    assert client.post(f"{PUB}/inventory/systems", headers=bearer(xt), json={"name": "x", "type": "agent", "sourcing": "vendor", "department_id": w.fin.id}).status_code == 422


def test_use_case_intake_creates_a_draft_for_human_review(client, db, w, abc):
    from app.inventory.models import AITool, UseCase

    _, t = abc
    tool = AITool(organization_id=w.org.id, vendor="OpenAI", product="ChatGPT Enterprise", account_type="enterprise")
    db.add(tool)
    w.e.stage = 2
    db.commit()
    body = {"name": "Job advert drafting", "department_id": w.hr.id, "tool_ids": [tool.id], "decision_impact": "none", "data_categories": ["none"], "purpose": "Drafts job adverts."}
    r = client.post(f"{PUB}/usecases", headers=bearer(t), json=body)
    assert r.status_code == 200, r.text
    uc = db.get(UseCase, r.json()["id"])
    assert uc.status == "draft" and uc.engagement_id == w.e.id
    w.e.stage = 7
    db.commit()
    assert client.post(f"{PUB}/usecases", headers=bearer(t), json=body).status_code == 409


def test_attestation_status_and_updates(client, w, abc):
    _, t = abc
    r = client.get(f"{PUB}/attestation/status", headers=bearer(t))
    assert r.status_code == 200 and r.json()["campaign"] is None
    r = client.get(f"{PUB}/updates", headers=bearer(t))
    assert r.status_code == 200 and isinstance(r.json()["data"], list)


def test_every_call_is_audit_logged(client, db, w, abc):
    creds, t = abc
    before = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "public_api.call")) or 0
    client.get(f"{PUB}/findings", headers=bearer(t))
    client.get(f"{PUB}/remediation", headers=bearer(t))
    rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "public_api.call").order_by(AuditLog.at)))
    assert len(rows) == before + 2
    assert rows[-1].organization_id == w.org.id and rows[-1].object_id == creds["client"]["id"] and "GET /remediation" in rows[-1].summary


def test_rate_limit_per_client(client, w):
    creds = make_client(client, w, scopes=["findings:read"], rate_limit_per_minute=3)
    t = token(client, creds)
    codes = [client.get(f"{PUB}/findings", headers=bearer(t)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    r = client.get(f"{PUB}/findings", headers=bearer(t))
    assert r.headers.get("retry-after")


def test_revoking_a_client_stops_its_tokens(client, w, abc):
    creds, t = abc
    w.as_(w.cadmin)
    assert client.post(f"{API}/admin/api/clients/{creds['client']['id']}/revoke").status_code == 200
    client.cookies.clear()
    assert client.get(f"{PUB}/findings", headers=bearer(t)).status_code == 401


def test_public_openapi_lists_only_the_public_api(client, abc):
    spec = client.get(f"{PUB}/openapi.json").json()
    paths = set(spec["paths"])
    assert "/findings" in paths and "/oauth/token" in paths
    assert not any(p.startswith("/api/v1") or "admin" in p for p in paths)
    main = client.get("/api/openapi.json").json()["paths"]
    assert not any(p.startswith("/api/public") or p.endswith("/oauth/token") for p in main)
