"""F1 (11-03 notes): Draft with AI uses the AI provider the Futran Admin connected, and a provider failure never shows the
provider's own error text. HTTP is mocked (httpx.MockTransport); nothing reaches the network."""
import json

import httpx
from sqlalchemy import select

from tests.factories import login_as

API = "/api/v1"
DRAFT = {"short_name": "Utah AI Policy Act", "citation": "SB 149 (2024)", "jurisdiction_code": "US-UT", "type": "statute", "status": "in_force",
         "sources": [{"name": "Utah Legislature", "url": "https://le.utah.gov/~2024/bills/static/SB0149.html"}],
         "requirements": [{"code": "UT-01", "text": "Disclose generative AI when asked", "citation": "Utah Code 13-2-12", "source_quote": "clearly and conspicuously disclose"}]}


def connect_gemini(db, app, people, handler):
    from app.ai import connection

    connection.save(db, app.state.settings, people["chief"], {"provider": "gemini", "model": "gemini-test", "api_key": "AIzaSyTESTKEY-0042"})
    db.commit()
    app.state.ai_http_transport = httpx.MockTransport(handler)


def test_draft_with_ai_uses_the_connected_provider(client, db, seeded, app):
    from app.audit_log.models import AuditLog

    seen = []

    def handler(request):
        seen.append(request)
        text = "```json\n" + json.dumps(DRAFT) + "\n```"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP", "groundingMetadata": {"webSearchQueries": ["Utah SB 149"]}}],
                                         "modelVersion": "gemini-test-001"})

    connect_gemini(db, app, seeded, handler)
    login_as(client, db, seeded["chief"])
    assert client.get(f"{API}/reg/laws").json()["claude_available"] is True
    r = client.post(f"{API}/reg/laws/draft", json={"ref": "Utah SB 149"})
    assert r.status_code == 200, r.text
    assert r.json()["draft"]["short_name"] == "Utah AI Policy Act" and len(seen) == 1
    assert seen[0].url.path.endswith("/models/gemini-test:generateContent") and json.loads(seen[0].content)["tools"] == [{"google_search": {}}]
    log = db.scalars(select(AuditLog).where(AuditLog.action == "regmaster.draft_with_claude")).one()
    assert log.after["provider"] == "gemini" and log.after["model"] == "gemini-test" and "Google Gemini" in log.summary


def test_a_failed_draft_gives_a_generic_message(client, db, seeded, app):
    connect_gemini(db, app, seeded, lambda request: httpx.Response(400, json={"error": {"message": "API key AIzaSyTESTKEY-0042 not valid. trace 51c"}}))
    login_as(client, db, seeded["chief"])
    r = client.post(f"{API}/reg/laws/draft", json={"ref": "Utah SB 149"})
    assert r.status_code == 409 and "could not draft this law" in r.json()["detail"]
    assert "AIzaSyTESTKEY" not in r.text and "51c" not in r.text
