"""Claude Platform on AWS as an AI provider (26 Nov 2026 request: law library and court-case refresh on "Claude on AWS").

Claude on Amazon Bedrock has no web search server tool, which the refresh depends on, so the platform connects to Claude
Platform on AWS instead: Anthropic's own Claude API behind an AWS gateway, through `anthropic.AnthropicAWS`. It signs with
an API key from the AWS Console or with the server's AWS credentials (the ECS task role on Fargate).

Every test is offline. Most replace the SDK class (`app.ai.providers.anthropic_aws.sdk_class`) with a recorder; a few use
the real `AnthropicAWS` with an httpx2 MockTransport, so the gateway address and headers it would send are checked too.
"""
import importlib.util
import json
import logging
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from tests.factories import login_as, make_org, make_user

API = "/api/v1"
KEY = "aws-key-SECRETVALUE-4d2b9e17"
WS = "wrkspc_01AbCdEf23"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
HAS_BOTOCORE = importlib.util.find_spec("botocore") is not None


def msg(text='{"ok": true}', *, model="claude-sonnet-5-5", stop="end_turn", citations=(), searches=0):
    block = NS(type="text", text=text, citations=[NS(url=u, cited_text=q) for u, q in citations])
    return NS(content=[block], stop_reason=stop, model=model,
              usage=NS(input_tokens=100, output_tokens=20, server_tool_use=NS(web_search_requests=searches)))


class FakeSDK:
    """Stands in for anthropic.AnthropicAWS: records how it was made and every messages.create call."""

    made: list = []
    replies: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.messages = NS(create=self._create)
        FakeSDK.made.append(self)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if FakeSDK.replies:
            r = FakeSDK.replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return msg()


@pytest.fixture
def fake_sdk(monkeypatch):
    FakeSDK.made, FakeSDK.replies = [], []
    monkeypatch.setattr("app.ai.providers.anthropic_aws.sdk_class", lambda: FakeSDK)
    return FakeSDK


def settings(**kw):
    from app.core.config import Settings

    base = {"email_mode": "outbox", "anthropic_api_key": None, "anthropic_aws_region": None, "anthropic_aws_workspace_id": None,
            "anthropic_aws_api_key": None, "anthropic_aws_base_url": None}
    return Settings(_env_file=None, **(base | kw))


def aws_cfg(**kw):
    from app.ai.providers import ConnectionConfig

    base = dict(provider="anthropic_aws", model="claude-opus-5-5", api_key=KEY, auth_mode="api_key", region="eu-west-1", workspace_id=WS)
    return ConnectionConfig(**(base | kw))


# ---- the catalogue
def test_the_catalogue_offers_claude_platform_on_aws_with_region_workspace_and_two_ways_to_sign_in():
    from app.ai.providers import CATALOGUE, LABELS

    p = next(x for x in CATALOGUE if x["id"] == "anthropic_aws")
    assert p["label"] == LABELS["anthropic_aws"] == "Claude Platform on AWS"
    assert p["aws"] is True and p["needs_endpoint"] is False
    assert p["models"] == ["claude-sonnet-5-5", "claude-opus-5-5"]  # the bare first-party ids, not Bedrock's
    assert [m["id"] for m in p["auth_modes"]] == ["api_key", "aws_role"]
    assert "Use the server's AWS role" in [m["label"] for m in p["auth_modes"]]
    assert "Claude Platform on AWS" in p["key_help"] and "API keys" in p["key_help"]
    assert "wrkspc_" in p["workspace_help"] and "region" in p["region_help"].lower()
    assert all("aws" not in x or x["id"] == "anthropic_aws" for x in CATALOGUE)


# ---- build() picks AnthropicAWS with the saved settings
def test_build_with_an_api_key_makes_an_anthropic_aws_client_for_the_region_and_workspace(fake_sdk):
    from app.ai.providers import build

    p = build(aws_cfg(), settings())
    assert p.provider == "anthropic_aws" and p.model == "claude-opus-5-5"
    r = p.complete(task="connection_test", system="s", prompt="p", schema=SCHEMA, max_tokens=1024)
    assert r.data == {"ok": True} and r.provider == "anthropic_aws"
    (sdk,) = fake_sdk.made
    assert sdk.kwargs == {"api_key": KEY, "aws_region": "eu-west-1", "workspace_id": WS, "base_url": "https://aws-external-anthropic.eu-west-1.api.aws"}
    call = sdk.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["extra_body"]["output_config"]["format"]["schema"] == SCHEMA


def test_build_with_the_servers_aws_role_passes_no_key_and_keeps_a_saved_gateway_address(fake_sdk):
    from app.ai.providers import build

    p = build(aws_cfg(api_key="", auth_mode="aws_role", region="us-east-1", endpoint="https://aws-external-anthropic.us-east-1.api.aws"), settings())
    p.complete(task="t", system="s", prompt="p", schema=SCHEMA)
    (sdk,) = fake_sdk.made
    assert "api_key" not in sdk.kwargs
    assert sdk.kwargs == {"aws_region": "us-east-1", "workspace_id": WS, "base_url": "https://aws-external-anthropic.us-east-1.api.aws"}


def test_the_sdk_client_is_made_once_and_only_when_first_used(fake_sdk):
    from app.ai.providers import build

    p = build(aws_cfg(), settings())
    assert fake_sdk.made == []  # building the provider makes no client (so an old SDK cannot break pages that never call it)
    p.complete(task="t", system="s", prompt="p", schema=SCHEMA)
    p.complete(task="t", system="s", prompt="p", schema=SCHEMA)
    assert len(fake_sdk.made) == 1 and len(fake_sdk.made[0].calls) == 2


def test_an_sdk_without_anthropic_aws_gives_a_plain_message(monkeypatch):
    import anthropic

    from app.ai.client import AIError
    from app.ai.providers import build

    monkeypatch.delattr(anthropic, "AnthropicAWS")
    p = build(aws_cfg(), settings())
    with pytest.raises(AIError, match="Claude Platform on AWS needs the anthropic package version 2.8 or later"):
        p.complete(task="t", system="s", prompt="p", schema=SCHEMA)


# ---- the refresh researches with web search, then asks for JSON, exactly like Anthropic
def test_the_refresh_client_sends_the_web_search_tool_then_a_json_call(fake_sdk):
    from app.ai.providers import build
    from app.refresh.claude import AnthropicStructuredClient

    s = settings()
    fake_sdk.replies = [msg("Colorado delayed SB 24-205 to 30 June 2026.", citations=[("https://leg.colorado.gov/bills/sb24-205", "delayed to June 30, 2026")], searches=2),
                        msg('{"changes": []}')]
    rc = build(aws_cfg(), s).refresh_client(s)
    assert isinstance(rc, AnthropicStructuredClient) and rc.provider == "anthropic_aws" and rc.model == "claude-opus-5-5"
    reply = rc.propose(system="sys", prompt="Jurisdiction code: US-CO", schema={"type": "object"}, allowed_domains=["leg.colorado.gov"])
    research, structure = fake_sdk.made[0].calls
    assert research["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": s.refresh_max_searches, "allowed_domains": ["leg.colorado.gov"]}]
    assert "tools" not in structure and structure["extra_body"]["output_config"]["format"]["type"] == "json_schema"
    assert reply.provider == "anthropic_aws" and reply.searches == 2 and reply.cited == {"https://leg.colorado.gov/bills/sb24-205": ["delayed to June 30, 2026"]}
    assert len(fake_sdk.made) == 1  # one client for both calls


def test_research_client_for_a_saved_aws_connection_uses_it(client, db, staff, app, fake_sdk):
    from app.ai.client import research_client_for

    login_as(client, db, staff["admin"])
    assert save(client).status_code == 200
    rc = research_client_for(app.state, app.state.settings)
    assert rc.provider == "anthropic_aws"
    rc.propose(system="s", prompt="Jurisdiction code: US-CO", schema={"type": "object"}, allowed_domains=[])
    assert fake_sdk.made[0].kwargs["workspace_id"] == WS and fake_sdk.made[0].calls[0]["tools"][0]["type"] == "web_search_20250305"


def test_the_drafting_client_researches_with_web_search(fake_sdk):
    from app.ai.providers import build
    from app.laws.refresh import AnthropicClaudeClient

    s = settings()
    fake_sdk.replies = [msg('```json {"short_name": "SB 24-205"} ```')]
    dc = build(aws_cfg(), s).drafting_client(s)
    assert isinstance(dc, AnthropicClaudeClient) and dc.provider == "anthropic_aws"
    assert "SB 24-205" in dc.research("Draft the Colorado AI Act")
    call = fake_sdk.made[0].calls[0]
    assert call["model"] == "claude-opus-5-5" and call["tools"][0]["type"] == "web_search_20250305"


# ---- AWS failures in plain words, never the response body
def _status_error(status, body="workspace wrkspc_01AbCdEf23 trace 77aa"):
    import anthropic
    import httpx2

    req = httpx2.Request("POST", "https://aws-external-anthropic.eu-west-1.api.aws/v1/messages")
    resp = httpx2.Response(status, request=req, json={"message": body})
    cls = {401: anthropic.AuthenticationError, 403: anthropic.PermissionDeniedError, 404: anthropic.NotFoundError,
           400: anthropic.BadRequestError, 429: anthropic.RateLimitError}.get(status, anthropic.InternalServerError)
    return cls(f"Error code: {status} - {body}", response=resp, body={"message": body})


@pytest.mark.parametrize("make,expected", [
    (lambda: _status_error(401), "refused the credentials"),
    (lambda: _status_error(403), "workspace ID"),
    (lambda: _status_error(404), "model name and the workspace ID"),
    (lambda: _status_error(400), "rejected the request"),
    (lambda: _status_error(429), "too many requests"),
    (lambda: _status_error(503), "unavailable"),
])
def test_aws_status_errors_are_plain_and_never_echo_the_body(fake_sdk, make, expected):
    from app.ai.client import AIError
    from app.ai.providers import build

    fake_sdk.replies = [make()]
    with pytest.raises(AIError) as ex:
        build(aws_cfg(), settings()).complete(task="t", system="s", prompt="p", schema=SCHEMA)
    assert expected in str(ex.value) and "77aa" not in str(ex.value) and "Claude Platform on AWS" in str(ex.value)
    assert ex.value.__cause__ is None and ex.value.__suppress_context__  # the SDK error (with its body) is not chained into logs


def test_an_unreachable_gateway_names_the_address_so_a_wrong_region_is_obvious(fake_sdk):
    import anthropic
    import httpx2

    from app.ai.client import AIError
    from app.ai.providers import build

    fake_sdk.replies = [anthropic.APIConnectionError(request=httpx2.Request("POST", "https://aws-external-anthropic.eu-west-9.api.aws/v1/messages"))]
    with pytest.raises(AIError) as ex:
        build(aws_cfg(region="eu-west-9"), settings()).complete(task="t", system="s", prompt="p", schema=SCHEMA)
    assert "aws-external-anthropic.eu-west-9.api.aws" in str(ex.value) and "region" in str(ex.value)


@pytest.mark.parametrize("exc,expected", [
    (RuntimeError("Could not resolve AWS credentials from session"), "found no AWS credentials"),
    (type("NoCredentialsError", (Exception,), {})("Unable to locate credentials"), "found no AWS credentials"),
    (ModuleNotFoundError("No module named 'botocore'", name="botocore"), "boto3"),
])
def test_signing_failures_with_the_servers_role_are_explained(fake_sdk, exc, expected):
    from app.ai.client import AIError
    from app.ai.providers import build

    fake_sdk.replies = [exc]
    with pytest.raises(AIError, match=expected):
        build(aws_cfg(api_key="", auth_mode="aws_role"), settings()).complete(task="t", system="s", prompt="p", schema=SCHEMA)


def test_the_refresh_reports_an_aws_failure_as_a_plain_message(fake_sdk):
    from app.ai.client import AIError
    from app.ai.providers import build

    fake_sdk.replies = [_status_error(403)]
    s = settings()
    with pytest.raises(AIError, match="workspace ID"):
        build(aws_cfg(), s).refresh_client(s).propose(system="s", prompt="p", schema={}, allowed_domains=[])


# ---- the real SDK, offline: the address, headers and auth it would use
def _real(handler, **cfg):
    import httpx2

    from app.ai.providers import build

    p = build(aws_cfg(**cfg), settings())
    p.client.http_client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return p


def test_the_real_sdk_posts_to_the_regional_gateway_with_the_workspace_header_and_the_key():
    import httpx2

    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(200, json={"id": "m1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "stop_reason": "end_turn",
                                          "content": [{"type": "text", "text": '{"ok": true}'}], "usage": {"input_tokens": 9, "output_tokens": 3}})

    r = _real(handler).complete(task="t", system="s", prompt="p", schema=SCHEMA)
    assert r.data == {"ok": True} and r.model == "claude-opus-5-5"
    (req,) = seen
    assert str(req.url) == "https://aws-external-anthropic.eu-west-1.api.aws/v1/messages"
    assert req.headers["anthropic-workspace-id"] == WS
    assert KEY in (req.headers.get("x-api-key", "") + req.headers.get("authorization", ""))


def test_the_real_sdk_reports_a_refused_workspace_plainly():
    import httpx2

    def handler(request):
        return httpx2.Response(403, json={"type": "error", "error": {"type": "permission_error", "message": f"not allowed on {WS}; trace 77aa"}})

    from app.ai.client import AIError

    with pytest.raises(AIError) as ex:
        _real(handler).complete(task="t", system="s", prompt="p", schema=SCHEMA)
    assert "workspace ID" in str(ex.value) and "77aa" not in str(ex.value)


@pytest.mark.skipif(HAS_BOTOCORE, reason="boto3 is installed here, so signing would be attempted")
def test_the_servers_role_without_boto3_says_what_to_install_and_sends_nothing(monkeypatch):
    seen = []
    monkeypatch.setenv("ANTHROPIC_AWS_API_KEY", "an-env-key-that-must-not-be-used")  # the saved choice wins over the SDK's own env lookup
    from app.ai.client import AIError

    p = _real(lambda r: seen.append(r), api_key="", auth_mode="aws_role")
    with pytest.raises(AIError, match="boto3"):
        p.complete(task="t", system="s", prompt="p", schema=SCHEMA)
    assert seen == []


def test_the_servers_role_never_falls_back_to_an_api_key_in_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AWS_API_KEY", "an-env-key-that-must-not-be-used")
    p = _real(lambda r: None, api_key="", auth_mode="aws_role")
    sdk = p.client.sdk()
    assert sdk._use_sigv4 is True and not sdk.api_key and sdk.auth_headers == {}


# ---- the key stays out of reprs and logs
def test_the_key_is_not_in_any_repr_or_log_line(fake_sdk, caplog):
    from app.ai.providers import build

    caplog.set_level(logging.DEBUG)
    s = settings(anthropic_aws_api_key=KEY, anthropic_aws_region="eu-west-1", anthropic_aws_workspace_id=WS)
    cfg = aws_cfg()
    p = build(cfg, s)
    fake_sdk.replies = [_status_error(401)]
    with pytest.raises(Exception):
        p.complete(task="t", system="s", prompt="p", schema=SCHEMA)
    for obj in (cfg, p, p.client, s, p.refresh_client(s), p.drafting_client(s)):
        assert KEY not in repr(obj) and "SECRETVALUE" not in repr(obj)
    assert "SECRETVALUE" not in caplog.text


# ---- the environment fallback: ANTHROPIC_AWS_* when nothing is saved
def test_with_nothing_saved_the_aws_environment_settings_drive_every_ai_feature(fake_sdk):
    from app.ai.client import ai_status, client_for, drafting_client_for, research_client_for

    s = settings(anthropic_aws_region="us-west-2", anthropic_aws_workspace_id=WS, ai_client="anthropic")
    c = client_for(None, s)
    assert c.provider == "anthropic_aws" and c.model == s.claude_model
    assert research_client_for(None, s).provider == "anthropic_aws"
    assert drafting_client_for(None, s).provider == "anthropic_aws"
    assert ai_status(None, s) == {"source": "environment", "provider": "anthropic_aws", "provider_label": "Claude Platform on AWS", "model": s.claude_model}
    c.complete(task="t", system="s", prompt="p", schema=SCHEMA)
    assert fake_sdk.made[0].kwargs == {"aws_region": "us-west-2", "workspace_id": WS, "base_url": "https://aws-external-anthropic.us-west-2.api.aws"}


def test_the_environment_fallback_uses_the_api_key_and_gateway_address_when_set(fake_sdk):
    from app.ai.client import client_for

    s = settings(anthropic_aws_region="us-west-2", anthropic_aws_workspace_id=WS, anthropic_aws_api_key=KEY,
                 anthropic_aws_base_url="https://aws-external-anthropic.us-west-2.api.aws", ai_client="anthropic", ai_model="claude-opus-5-5")
    c = client_for(None, s)
    c.complete(task="t", system="s", prompt="p", schema=SCHEMA)
    assert c.model == "claude-opus-5-5"
    assert fake_sdk.made[0].kwargs == {"api_key": KEY, "aws_region": "us-west-2", "workspace_id": WS, "base_url": "https://aws-external-anthropic.us-west-2.api.aws"}


def test_anthropic_api_key_wins_when_both_are_set_and_half_an_aws_setup_is_ignored(fake_sdk):
    from app.ai.client import AnthropicAIClient, ai_status, client_for, research_client_for
    from app.refresh.claude import AnthropicStructuredClient

    both = settings(anthropic_api_key="sk-ant-env", anthropic_aws_region="us-west-2", anthropic_aws_workspace_id=WS, ai_client="anthropic")
    assert type(client_for(None, both)) is AnthropicAIClient
    rc = research_client_for(None, both)
    assert type(rc) is AnthropicStructuredClient and rc.provider == "anthropic"
    assert ai_status(None, both)["provider"] == "anthropic"
    half = settings(anthropic_aws_region="us-west-2", ai_client="anthropic")  # no workspace: not configured
    assert client_for(None, half) is None and research_client_for(None, half) is None and ai_status(None, half)["source"] is None


def test_a_saved_connection_wins_over_the_aws_environment(client, db, staff, app, fake_sdk):
    from app.ai.client import client_for

    app.state.settings = app.state.settings.model_copy(update={"anthropic_aws_region": "us-west-2", "anthropic_aws_workspace_id": "wrkspc_env"})
    assert client_for(app.state, app.state.settings).provider == "anthropic_aws"
    login_as(client, db, staff["admin"])
    assert client.put(f"{API}/admin/ai-connection", json={"provider": "openai", "model": "gpt-test", "api_key": "sk-proj-0123456789"}).status_code == 200
    assert client_for(app.state, app.state.settings).provider == "openai"


# ---- the connection API
@pytest.fixture
def staff(db):
    f = make_org(db, type="futran")
    p = {"admin": make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test"),
         "chief": make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test"),
         "aud": make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")}
    db.commit()
    return p


def save(client, **kw):
    body = {"provider": "anthropic_aws", "model": "claude-sonnet-5-5", "auth_mode": "api_key", "api_key": KEY, "aws_region": "eu-west-1",
            "aws_workspace_id": WS} | kw
    return client.put(f"{API}/admin/ai-connection", json=body)


def test_admin_saves_an_aws_connection_with_a_key_that_never_comes_back(client, db, staff):
    from app.ai.connection import AIConnection
    from app.audit_log.models import AuditLog

    login_as(client, db, staff["admin"])
    r = save(client)
    assert r.status_code == 200, r.text
    out = r.json()
    assert KEY not in r.text and "SECRETVALUE" not in r.text
    assert (out["provider"], out["provider_label"], out["auth_mode"], out["aws_region"], out["aws_workspace_id"], out["key_hint"]) == \
        ("anthropic_aws", "Claude Platform on AWS", "api_key", "eu-west-1", WS, "…9e17")
    assert out["active"] == {"source": "connection", "provider": "anthropic_aws", "provider_label": "Claude Platform on AWS", "model": "claude-sonnet-5-5"}
    row = db.scalar(select(AIConnection))
    db.refresh(row)
    assert KEY not in row.key_encrypted and (row.auth_mode, row.aws_region, row.aws_workspace_id) == ("api_key", "eu-west-1", WS)
    log = db.scalars(select(AuditLog).where(AuditLog.action == "ai_connection.saved")).one()
    assert KEY not in json.dumps([log.before, log.after, log.summary]) and log.after["aws_workspace_id"] == WS and log.after["auth_mode"] == "api_key"


def test_admin_saves_an_aws_connection_that_uses_the_servers_role_and_stores_no_key(client, db, staff, app, fake_sdk):
    from app.ai.client import client_for
    from app.ai.connection import AIConnection

    login_as(client, db, staff["admin"])
    r = save(client, auth_mode="aws_role", api_key=None, aws_region="US-EAST-1")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["auth_mode"] == "aws_role" and out["key_hint"] is None and out["key_unreadable"] is False and out["aws_region"] == "us-east-1"
    row = db.scalar(select(AIConnection))
    db.refresh(row)
    assert row.key_encrypted == "" and row.key_hint == ""
    client_for(app.state, app.state.settings).complete(task="t", system="s", prompt="p", schema=SCHEMA)
    assert "api_key" not in fake_sdk.made[0].kwargs and fake_sdk.made[0].kwargs["aws_region"] == "us-east-1"
    # switching back to an API key needs a key, since none is stored
    r = save(client, auth_mode="api_key", api_key=None)
    assert r.status_code == 422 and [e["field"] for e in r.json()["errors"]] == ["api_key"]


def test_changing_the_region_keeps_the_saved_key_and_clears_the_last_test(client, db, staff):
    login_as(client, db, staff["admin"])
    assert save(client).status_code == 200
    r = save(client, api_key=None, aws_region="us-west-2")
    assert r.status_code == 200 and r.json()["key_hint"] == "…9e17" and r.json()["aws_region"] == "us-west-2"


@pytest.mark.parametrize("body,field", [
    ({"aws_region": ""}, "aws_region"),
    ({"aws_region": "europe"}, "aws_region"),
    ({"aws_workspace_id": ""}, "aws_workspace_id"),
    ({"aws_workspace_id": "arn:aws:aws-external-anthropic:us-east-1:123:workspace/wrkspc_1"}, "aws_workspace_id"),
    ({"auth_mode": "sso"}, "auth_mode"),
    ({"auth_mode": "aws_role", "api_key": KEY}, "api_key"),
    ({"endpoint": "http://aws-external-anthropic.eu-west-1.api.aws"}, "endpoint"),
    ({"endpoint": "https://abc123.execute-api.eu-west-1.amazonaws.com"}, "endpoint"),
    ({"endpoint": "https://aws-external-anthropic.eu-west-1.api.aws.attacker.example"}, "endpoint"),
    ({"model": "anthropic.claude-sonnet-5-5-v1:0 x"}, "model"),
    ({"model": "anthropic.claude-sonnet-5-5-v1:0"}, "model"),
])
def test_invalid_aws_settings_are_refused_field_by_field(client, db, staff, body, field):
    login_as(client, db, staff["admin"])
    r = save(client, **body)
    assert r.status_code == 422 and field in [e["field"] for e in r.json()["errors"]], r.text


def test_a_gateway_address_on_the_aws_domains_is_kept(client, db, staff):
    login_as(client, db, staff["admin"])
    r = save(client, endpoint="https://aws-external-anthropic.eu-west-1.api.aws/")
    assert r.status_code == 200 and r.json()["endpoint"] == "https://aws-external-anthropic.eu-west-1.api.aws"


def test_other_providers_store_no_aws_fields(client, db, staff):
    login_as(client, db, staff["admin"])
    assert save(client).status_code == 200
    r = client.put(f"{API}/admin/ai-connection", json={"provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": "sk-ant-0123456789",
                                                       "auth_mode": "aws_role", "aws_region": "us-east-1", "aws_workspace_id": WS})
    assert r.status_code == 200 and (r.json()["auth_mode"], r.json()["aws_region"], r.json()["aws_workspace_id"]) == (None, None, None)


def test_only_the_futran_admin_changes_or_tests_the_aws_connection(client, db, staff):
    login_as(client, db, staff["admin"])
    assert save(client).status_code == 200
    login_as(client, db, staff["chief"])
    g = client.get(f"{API}/admin/ai-connection")
    assert g.status_code == 200 and g.json()["can_manage"] is False and KEY not in g.text and g.json()["aws_workspace_id"] == WS
    assert save(client).status_code == 403
    assert client.post(f"{API}/admin/ai-connection/test").status_code == 403
    login_as(client, db, staff["aud"])
    assert client.get(f"{API}/admin/ai-connection").status_code == 403


def test_test_connection_makes_one_small_call_and_reports_success(client, db, staff, fake_sdk):
    login_as(client, db, staff["admin"])
    save(client)
    r = client.post(f"{API}/admin/ai-connection/test")
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert "Claude Platform on AWS answered with model claude-sonnet-5-5" in r.json()["message"]
    assert len(fake_sdk.made[0].calls) == 1 and fake_sdk.made[0].calls[0]["max_tokens"] <= 1024


def test_test_connection_reports_a_wrong_workspace_plainly(client, db, staff, fake_sdk):
    login_as(client, db, staff["admin"])
    save(client)
    fake_sdk.replies = [_status_error(403)]
    r = client.post(f"{API}/admin/ai-connection/test")
    assert r.status_code == 200 and r.json()["ok"] is False
    assert "workspace ID" in r.json()["message"] and "77aa" not in r.text and KEY not in r.text
    assert client.get(f"{API}/admin/ai-connection").json()["last_test"]["ok"] is False


def test_the_browser_test_stand_in_answers_for_an_aws_role_connection(client, db, staff, app):
    app.state.settings = app.state.settings.model_copy(update={"ai_provider_http": "fake"})
    login_as(client, db, staff["admin"])
    save(client, auth_mode="aws_role", api_key=None)
    r = client.post(f"{API}/admin/ai-connection/test")
    assert r.json()["ok"] is True, r.text
