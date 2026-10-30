"""Token encryption and the provider adapters. Real adapters are exercised against httpx.MockTransport: no network."""
import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.config import Settings
from app.mail import tokens
from app.mail.models import MailConnection
from app.mail.providers import OutgoingMessage, ProviderError, credentials_status, get_adapter
from app.mail.providers.fake import FAKE, FakeAdapter
from app.mail.providers.google import GoogleAdapter
from app.mail.providers.microsoft import MicrosoftGraphAdapter


def _live(**kw) -> Settings:
    base = dict(database_url="sqlite://", mfa_required=False, email_mode="smtp", secret_key="test-secret-key-not-for-production-0123456789", disable_scheduler=True,
                base_url="https://audit.example.com")
    return Settings(**{**base, **kw})


# ---- tokens
def test_tokens_are_encrypted_at_rest_and_read_back(settings):
    c = MailConnection(organization_id="o", owner="client")
    tokens.store(settings, c, {"kind": "app", "tenant": "t-1", "access_token": "secret-access-token"})
    assert "secret-access-token" not in (c.token_encrypted or "")
    assert c.token_ref
    assert tokens.load(settings, c)["access_token"] == "secret-access-token"


def test_token_encryption_key_overrides_the_secret_key(settings):
    c = MailConnection(organization_id="o", owner="client")
    s2 = settings.model_copy(update={"token_encryption_key": "a-separate-long-random-token-key-0123456789"})
    tokens.store(s2, c, {"access_token": "x"})
    with pytest.raises(tokens.TokenError):
        tokens.load(settings, c)
    assert tokens.load(s2, c)["access_token"] == "x"


# ---- choosing an adapter
def test_test_mode_always_uses_the_in_process_fake(settings):
    assert isinstance(get_adapter(settings, "microsoft365"), FakeAdapter)
    assert isinstance(get_adapter(settings, "google"), FakeAdapter)


def test_live_mode_without_credentials_has_no_adapter_and_says_what_is_missing():
    s = _live()
    assert get_adapter(s, "microsoft365") is None
    st = credentials_status(s)
    assert st["microsoft365"]["configured"] is False
    assert "MS_CLIENT_ID" in st["microsoft365"]["missing"]
    assert st["microsoft365"]["redirect_uri"] == "https://audit.example.com/api/v1/mail/oauth/microsoft365"


def test_live_mode_with_credentials_uses_the_real_adapters():
    s = _live(ms_client_id="cid", ms_client_secret="sec", google_client_id="gid", google_client_secret="gsec")
    assert isinstance(get_adapter(s, "microsoft365"), MicrosoftGraphAdapter)
    assert isinstance(get_adapter(s, "google"), GoogleAdapter)


# ---- Microsoft Graph
def _ms(handler) -> MicrosoftGraphAdapter:
    return MicrosoftGraphAdapter(_live(ms_client_id="cid", ms_client_secret="sec"), transport=httpx.MockTransport(handler))


def test_microsoft_admin_consent_url_asks_for_the_default_scope():
    url = _ms(lambda r: httpx.Response(500)).consent_url(kind="admin", state="st8", tenant="contoso.com")
    u = urlparse(url)
    q = parse_qs(u.query)
    assert u.netloc == "login.microsoftonline.com" and u.path == "/contoso.com/v2.0/adminconsent"
    assert q["client_id"] == ["cid"] and q["scope"] == ["https://graph.microsoft.com/.default"] and q["state"] == ["st8"]
    assert q["redirect_uri"] == ["https://audit.example.com/api/v1/mail/oauth/microsoft365"]


def test_microsoft_admin_consent_is_confirmed_with_an_app_token_for_that_tenant():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        if req.url.path.endswith("/oauth2/v2.0/token"):
            body = parse_qs(req.content.decode())
            assert body["grant_type"] == ["client_credentials"] and body["scope"] == ["https://graph.microsoft.com/.default"]
            return httpx.Response(200, json={"access_token": "app-tok", "expires_in": 3600})
        if req.url.path == "/v1.0/organization":
            return httpx.Response(200, json={"value": [{"displayName": "Contoso", "verifiedDomains": [{"name": "contoso.com", "isDefault": True}]}]})
        return httpx.Response(404)

    g = _ms(handler).complete_consent(kind="admin", params={"admin_consent": "True", "tenant": "11111111-2222-3333-4444-555555555555"})
    assert g["kind"] == "app" and g["tenant"] == "11111111-2222-3333-4444-555555555555"
    assert g["domains"] == ["contoso.com"]
    assert "/11111111-2222-3333-4444-555555555555/oauth2/v2.0/token" in seen


def test_microsoft_refused_consent_raises():
    with pytest.raises(ProviderError):
        _ms(lambda r: httpx.Response(500)).complete_consent(kind="admin", params={"error": "consent_required", "error_description": "denied"})


def test_microsoft_send_creates_a_draft_then_sends_it_from_the_chosen_mailbox():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "app-tok", "expires_in": 3600})
        assert req.headers["authorization"] == "Bearer app-tok"
        if req.method == "POST" and req.url.path == "/v1.0/users/ai-governance@contoso.com/messages":
            m = json.loads(req.content)
            assert m["bccRecipients"][0]["emailAddress"]["address"] == "b@contoso.com"
            assert m["subject"] == "Hello [FAP-1001]"
            return httpx.Response(201, json={"id": "MSG1", "conversationId": "CONV1", "internetMessageId": "<x@y>"})
        if req.method == "POST" and req.url.path == "/v1.0/users/ai-governance@contoso.com/messages/MSG1/send":
            return httpx.Response(202)
        return httpx.Response(404)

    a = _ms(handler)
    grant = tokens.Grant({"kind": "app", "tenant": "t-1"})
    out = a.send(grant, OutgoingMessage(from_address="ai-governance@contoso.com", from_name="Contoso AI Governance", reply_to=None, to=[], bcc=["b@contoso.com"],
                                        subject="Hello [FAP-1001]", html="<p>Hi</p>", text="Hi"))
    assert out.message_id == "MSG1" and out.thread_id == "CONV1"
    assert ("POST", "/v1.0/users/ai-governance@contoso.com/messages/MSG1/send") in calls
    assert grant.dirty and grant["access_token"] == "app-tok"


def test_microsoft_throttling_is_reported_as_a_retryable_error():
    def handler(req):
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(429, headers={"Retry-After": "30"}, json={"error": {"message": "throttled"}})

    with pytest.raises(ProviderError) as e:
        _ms(handler).send(tokens.Grant({"kind": "app", "tenant": "t"}), OutgoingMessage("a@c.com", "A", None, ["x@c.com"], [], "s", "<p>h</p>", "h"))
    assert e.value.retryable


def test_microsoft_directory_reads_people_page_by_page():
    def handler(req: httpx.Request):
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if req.url.path == "/v1.0/users" and "skiptoken" not in str(req.url):
            return httpx.Response(200, json={"value": [{"id": "u1", "displayName": "Ana Ruiz", "mail": "ana@contoso.com", "department": "Finance", "jobTitle": "Analyst",
                                                        "officeLocation": "NYC", "accountEnabled": True, "userType": "Member", "manager": {"id": "u9"}}],
                                              "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=abc"})
        if req.url.path == "/v1.0/users":
            return httpx.Response(200, json={"value": [{"id": "u2", "displayName": "Guest", "mail": "g@other.com", "accountEnabled": True, "userType": "Guest"}]})
        return httpx.Response(404)

    people = _ms(handler).list_people(tokens.Grant({"kind": "app", "tenant": "t"}), scope_group=None, include_guests=False)
    assert [p.email for p in people] == ["ana@contoso.com"]
    assert people[0].department == "Finance" and people[0].manager_id == "u9" and people[0].office == "NYC"


# ---- Google
def _google(handler) -> GoogleAdapter:
    return GoogleAdapter(_live(google_client_id="gid", google_client_secret="gsec"), transport=httpx.MockTransport(handler))


def test_google_consent_url_asks_for_offline_access_and_the_gmail_and_directory_scopes():
    url = _google(lambda r: httpx.Response(500)).consent_url(kind="admin", state="s1", login_hint="ai-governance@abc.com")
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    scopes = q["scope"][0].split()
    assert "https://www.googleapis.com/auth/gmail.send" in scopes and "https://www.googleapis.com/auth/gmail.modify" in scopes
    assert "https://www.googleapis.com/auth/admin.directory.user.readonly" in scopes
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"] and q["login_hint"] == ["ai-governance@abc.com"]


def test_google_user_consent_asks_only_for_gmail():
    q = parse_qs(urlparse(_google(lambda r: httpx.Response(500)).consent_url(kind="user", state="s")).query)
    assert not any("admin.directory" in s for s in q["scope"][0].split())


def test_google_send_posts_raw_mime_and_returns_the_thread():
    def handler(req: httpx.Request):
        if req.url.host == "oauth2.googleapis.com":
            body = parse_qs(req.content.decode())
            assert body["grant_type"] == ["refresh_token"]
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        assert req.url.path == "/gmail/v1/users/me/messages/send"
        raw = base64.urlsafe_b64decode(json.loads(req.content)["raw"] + "==").decode()
        assert "Subject: Hi [FAP-1002]" in raw and "Bcc: x@abc.com" in raw
        return httpx.Response(200, json={"id": "g1", "threadId": "th1"})

    grant = tokens.Grant({"kind": "delegated", "refresh_token": "r", "access_token": "old", "expires_at": 0})
    out = _google(handler).send(grant, OutgoingMessage("ai@abc.com", "ABC", None, [], ["x@abc.com"], "Hi [FAP-1002]", "<p>h</p>", "h"))
    assert (out.message_id, out.thread_id) == ("g1", "th1")
    assert grant["access_token"] == "fresh"


# ---- fake
def test_fake_adapter_records_sends_and_serves_replies_only_for_known_threads():
    FAKE.reset()
    a = FakeAdapter("microsoft365")
    sent = a.send(tokens.Grant({"kind": "app", "fake": True}), OutgoingMessage("ai@abc.com", "ABC", None, ["x@abc.com"], [], "Q [FAP-1003]", "<p>h</p>", "h"))
    FAKE.add_reply(sent.thread_id, from_address="x@abc.com", subject="RE: Q [FAP-1003]", body="Done")
    msgs = a.thread_messages(tokens.Grant({"kind": "app", "fake": True}), "ai@abc.com", sent.thread_id)
    assert [m.from_address for m in msgs] == ["x@abc.com"]
    assert len(FAKE.sent) == 1
