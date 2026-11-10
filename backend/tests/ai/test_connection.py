"""F1 (11-03 notes): the Futran Admin connects one AI provider for the whole platform, and every AI feature uses it.

The key is stored encrypted, never returned (only its last four characters), never written to the audit log, and can be
removed. With nothing connected, behaviour is exactly as before: ANTHROPIC_API_KEY, then the demonstration model in test
mode. HTTP providers are exercised through app.state.ai_http_transport (httpx.MockTransport); nothing reaches the network.
"""
import json
from types import SimpleNamespace as NS

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from tests.factories import login_as, make_org, make_user

API = "/api/v1"
KEY = "sk-proj-SECRETVALUE-9f3a1c7e"


@pytest.fixture
def staff(db):
    f = make_org(db, type="futran")
    p = {"admin": make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test"),
         "chief": make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test"),
         "aud": make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")}
    db.commit()
    return p


def chat(content='{"ok": true}', model="gpt-test-2026"):
    return {"model": model, "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}], "usage": {"prompt_tokens": 20, "completion_tokens": 5}}


def mock(app, reply=None, status=200):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json=(reply(request) if callable(reply) else reply) if reply is not None else chat())

    app.state.ai_http_transport = httpx.MockTransport(handler)
    return seen


def save(client, **kw):
    body = {"provider": "openai", "model": "gpt-test", "api_key": KEY} | kw
    return client.put(f"{API}/admin/ai-connection", json=body)


def test_admin_saves_a_connection_and_the_key_never_comes_back(client, db, staff):
    from app.ai.connection import AIConnection
    from app.audit_log.models import AuditLog

    login_as(client, db, staff["admin"])
    r = save(client)
    assert r.status_code == 200, r.text
    assert KEY not in r.text and "SECRETVALUE" not in r.text
    out = r.json()
    assert out["connected"] and out["provider"] == "openai" and out["provider_label"] == "OpenAI" and out["model"] == "gpt-test" and out["key_hint"] == "…1c7e"
    assert out["active"] == {"source": "connection", "provider": "openai", "provider_label": "OpenAI", "model": "gpt-test"}
    g = client.get(f"{API}/admin/ai-connection")
    assert g.status_code == 200 and KEY not in g.text and g.json()["key_hint"] == "…1c7e"
    assert {p["id"] for p in g.json()["providers"]} == {"anthropic", "openai", "azure_openai", "gemini"}
    row = db.scalar(select(AIConnection))
    db.refresh(row)
    assert row.key_encrypted and KEY not in row.key_encrypted and row.key_ref.startswith(("secret_key:", "token_key:"))
    logs = db.scalars(select(AuditLog).where(AuditLog.action.like("ai_connection.%"))).all()
    assert [x.action for x in logs] == ["ai_connection.saved"] and all(KEY not in json.dumps([x.before, x.after, x.summary]) for x in logs)
    assert logs[0].after["key_replaced"] is True and logs[0].after["provider"] == "openai"


def test_changing_the_model_keeps_the_key_but_a_new_provider_needs_a_new_key(client, db, staff):
    from app.ai.connection import AIConnection

    login_as(client, db, staff["admin"])
    assert save(client).status_code == 200
    r = client.put(f"{API}/admin/ai-connection", json={"provider": "openai", "model": "gpt-other"})
    assert r.status_code == 200 and r.json()["model"] == "gpt-other" and r.json()["key_hint"] == "…1c7e"
    r = client.put(f"{API}/admin/ai-connection", json={"provider": "gemini", "model": "gemini-test"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "api_key"
    assert db.scalar(select(AIConnection.provider)) == "openai"


@pytest.mark.parametrize("body,field", [
    ({"provider": "mistral"}, "provider"),
    ({"model": ""}, "model"),
    ({"model": "gpt test; rm"}, "model"),
    ({"api_key": "short"}, "api_key"),
    ({"provider": "azure_openai", "endpoint": "", "deployment": "audit-gpt"}, "endpoint"),
    ({"provider": "azure_openai", "endpoint": "http://futran-ai.openai.azure.com", "deployment": "audit-gpt"}, "endpoint"),
    ({"provider": "azure_openai", "endpoint": "https://attacker.example.com", "deployment": "audit-gpt"}, "endpoint"),
    ({"provider": "azure_openai", "endpoint": "https://futran-ai.openai.azure.com", "deployment": ""}, "deployment"),
])
def test_invalid_settings_are_refused_field_by_field(client, db, staff, body, field):
    login_as(client, db, staff["admin"])
    r = save(client, **body)
    assert r.status_code == 422 and field in [e["field"] for e in r.json()["errors"]], r.text


def test_azure_connection_saves_endpoint_and_deployment(client, db, staff):
    login_as(client, db, staff["admin"])
    r = save(client, provider="azure_openai", model="", endpoint="https://futran-ai.openai.azure.com/", deployment="audit-gpt")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["endpoint"] == "https://futran-ai.openai.azure.com" and out["deployment"] == "audit-gpt" and out["model"] == "audit-gpt"


def test_only_the_futran_admin_changes_it_and_the_chief_auditor_can_read_it(client, db, staff):
    login_as(client, db, staff["admin"])
    assert save(client).status_code == 200
    login_as(client, db, staff["chief"])
    g = client.get(f"{API}/admin/ai-connection")
    assert g.status_code == 200 and g.json()["can_manage"] is False and KEY not in g.text
    assert save(client).status_code == 403
    assert client.delete(f"{API}/admin/ai-connection").status_code == 403
    assert client.post(f"{API}/admin/ai-connection/test").status_code == 403
    login_as(client, db, staff["aud"])
    assert client.get(f"{API}/admin/ai-connection").status_code == 403


def test_test_connection_makes_one_small_call_and_records_the_result(client, db, staff, app):
    from app.audit_log.models import AuditLog

    login_as(client, db, staff["admin"])
    save(client)
    seen = mock(app)
    r = client.post(f"{API}/admin/ai-connection/test")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and "gpt-test-2026" in r.json()["message"] and len(seen) == 1
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert client.get(f"{API}/admin/ai-connection").json()["last_test"]["ok"] is True
    log = db.scalars(select(AuditLog).where(AuditLog.action == "ai_connection.tested")).one()
    assert log.after["ok"] is True and KEY not in json.dumps(log.after)


def test_a_failed_test_gives_a_generic_message_never_the_provider_body(client, db, staff, app):
    login_as(client, db, staff["admin"])
    save(client)
    mock(app, {"error": {"message": f"Incorrect API key provided: {KEY}. Trace 77aa."}}, status=401)
    r = client.post(f"{API}/admin/ai-connection/test")
    assert r.status_code == 200
    assert r.json()["ok"] is False and "refused the API key" in r.json()["message"] and KEY not in r.text and "77aa" not in r.text


def test_test_without_a_connection_is_a_conflict(client, db, staff):
    login_as(client, db, staff["admin"])
    assert client.post(f"{API}/admin/ai-connection/test").status_code == 409


def test_removing_the_connection_deletes_the_key_and_falls_back(client, db, staff, app):
    from app.ai.client import client_for
    from app.ai.connection import AIConnection

    login_as(client, db, staff["admin"])
    save(client)
    r = client.delete(f"{API}/admin/ai-connection")
    assert r.status_code == 200 and r.json()["connected"] is False and r.json()["key_hint"] is None
    assert db.scalar(select(AIConnection)) is None
    assert r.json()["active"]["source"] == "demonstration"  # test mode, no ANTHROPIC_API_KEY: as before
    assert client_for(app.state, app.state.settings).provider == "fake"


# ---- every AI feature uses the connection
def test_client_for_uses_the_saved_connection_before_the_env_key(client, db, staff, app):
    from app.ai.client import AnthropicAIClient, FakeAIClient, client_for

    login_as(client, db, staff["admin"])
    assert isinstance(client_for(app.state, app.state.settings), FakeAIClient)  # nothing connected: as before
    app.state.settings = app.state.settings.model_copy(update={"anthropic_api_key": "env-key"})
    assert isinstance(client_for(app.state, app.state.settings), AnthropicAIClient)
    save(client)
    c = client_for(app.state, app.state.settings)
    assert c.provider == "openai" and c.model == "gpt-test"
    # AI_CLIENT=fake (the demo) never uses the connection; an injected factory still wins
    assert isinstance(client_for(app.state, app.state.settings.model_copy(update={"ai_client": "fake"})), FakeAIClient)
    injected = FakeAIClient()
    app.state.ai_client_factory = lambda s: injected
    assert client_for(app.state, app.state.settings) is injected


def test_a_feature_call_through_the_connection_records_provider_and_model(client, db, staff, app):
    from app.ai import service

    login_as(client, db, staff["admin"])
    save(client)
    seen = mock(app, chat('{"answer": "From the policy."}'))
    c = service.call(app.state, app.state.settings, task="ask", prompt_version="ask-1", system="s", prompt="p",
                     schema={"type": "object"}, context={})
    assert c.reply.provider == "openai" and c.reply.model == "gpt-test-2026" and c.reply.data == {"answer": "From the policy."}
    i = service.record(db, staff["admin"], c, organization_id=staff["admin"].organization_id, feature="copilot_ask")
    assert (i.provider, i.model) == ("openai", "gpt-test-2026") and len(seen) == 1


def test_a_failing_provider_is_reported_as_unavailable_not_a_crash(client, db, staff, app):
    from app.ai import service

    login_as(client, db, staff["admin"])
    save(client)
    mock(app, {"error": "down"}, status=503)
    with pytest.raises(service.AIUnavailable) as ex:
        service.call(app.state, app.state.settings, task="ask", prompt_version="ask-1", system="s", prompt="p", schema={"type": "object"}, context={})
    assert "unavailable" in str(ex.value.detail)


def test_refresh_and_drafting_use_the_connection(client, db, staff, app):
    from app.ai.client import drafting_client_for, research_client_for
    from app.ai.providers.base import ResearchThenStructure, TextResearch
    from app.refresh.claude import client_for as refresh_client_for

    s = app.state.settings
    assert research_client_for(app.state, s) is None and drafting_client_for(app.state, s) is None  # nothing set: as before
    login_as(client, db, staff["admin"])
    save(client, provider="gemini", model="gemini-test")
    r = refresh_client_for(app.state, s)
    assert isinstance(r, ResearchThenStructure) and r.provider == "gemini" and r.model == "gemini-test"
    d = drafting_client_for(app.state, s)
    assert isinstance(d, TextResearch) and d.provider == "gemini"
    # REFRESH_CLIENT=fake (demo, browser tests) and injected factories keep their place
    from app.refresh.claude import FakeRefreshClient

    assert isinstance(refresh_client_for(app.state, s.model_copy(update={"refresh_client": "fake"})), FakeRefreshClient)
    app.state.refresh_client_factory = lambda st: "injected"
    assert refresh_client_for(app.state, s) == "injected"


def test_anthropic_connection_feeds_its_key_and_model_to_every_anthropic_adapter(client, db, staff, app):
    from app.ai.client import client_for, drafting_client_for, research_client_for

    login_as(client, db, staff["admin"])
    save(client, provider="anthropic", model="claude-test-model", api_key="sk-ant-api03-abcdef123456")
    s = app.state.settings
    c = client_for(app.state, s)
    assert c.provider == "anthropic" and c.model == "claude-test-model" and c.client.api_key == "sk-ant-api03-abcdef123456"
    r = research_client_for(app.state, s)
    assert type(r).__name__ == "AnthropicStructuredClient" and r.model == "claude-test-model" and r.client.api_key == "sk-ant-api03-abcdef123456"
    d = drafting_client_for(app.state, s)
    assert type(d).__name__ == "AnthropicClaudeClient" and d.model == "claude-test-model"


def test_scheduled_refresh_finds_the_connection_without_app_state(client, db, staff, app):
    from app.refresh.schedule import _client

    login_as(client, db, staff["admin"])
    save(client, provider="gemini", model="gemini-test")
    assert _client(app.state.settings, db).provider == "gemini"


def test_a_key_sealed_with_another_secret_is_treated_as_not_connected(client, db, staff, app):
    from app.ai.client import client_for

    login_as(client, db, staff["admin"])
    save(client)
    app.state.settings = app.state.settings.model_copy(update={"secret_key": "a-different-secret-key-0123456789abcdef"})
    assert client_for(app.state, app.state.settings).provider == "fake"  # falls back rather than failing every feature
    g = client.get(f"{API}/admin/ai-connection").json()
    assert g["connected"] is True and g["key_unreadable"] is True


def test_platform_settings_and_law_library_report_the_connected_provider(client, db, staff):
    login_as(client, db, staff["admin"])
    assert client.get(f"{API}/admin/settings").json()["law_refresh_enabled"] is False
    save(client)
    s = client.get(f"{API}/admin/settings").json()
    assert s["law_refresh_enabled"] is True and s["ai_label"] == "OpenAI · gpt-test"


def test_no_connection_keeps_the_old_behaviour_exactly():
    from app.ai.client import client_for

    assert client_for(NS(), Settings(secret_key="x" * 40, ai_client="auto", mfa_required=True, email_mode="smtp")) is None
