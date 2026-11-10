"""The refresh pipeline on the providers called over httpx (F1, 11-03 notes). Only httpx.MockTransport; no network."""
import json

import httpx
from sqlalchemy import select

from tests.refresh.conftest import change, reg  # noqa: F401
from tests.wsd_world import lit  # noqa: F401

REAL = "https://www.ilga.gov/legislation/publicacts/fulltext.asp?Name=104-0001"
REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQabc123"


def _run(db, lit, settings, client, codes=("US-IL",)):
    from app.refresh.pipeline import execute_run, start_run

    run = start_run(db, kind="law", actor=lit["chief"], jurisdiction_codes=list(codes), settings=settings)
    execute_run(db, settings, run, client)
    db.commit()
    return run


def test_gemini_redirect_chunks_are_resolved_so_the_allowlist_match_works(db, lit, reg, settings):
    from app.ai.providers.gemini import GeminiProvider
    from app.refresh.models import RefreshProposalMeta
    from app.regmaster.models import ProposedChange

    seen = []

    def handler(request):
        if request.url.host == "vertexaisearch.cloud.google.com":
            return httpx.Response(302, headers={"Location": REAL})
        body = json.loads(request.content)
        seen.append(body)
        if "tools" in body:
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "Effective date moved."}]},
                                                             "groundingMetadata": {"webSearchQueries": ["q"], "groundingChunks": [{"web": {"uri": REDIRECT, "title": "ilga.gov"}}]}}]})
        # a model that follows the structure note and cites only the pages listed
        listed = body["contents"][0]["parts"][0]["text"].split("Cited pages:\n- ", 1)[1].splitlines()[0]
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({"changes": [change(reg["law"], source_url=listed)]})}]}}]})

    p = GeminiProvider(api_key="AIzaX-123456789", model="gemini-test", transport=httpx.MockTransport(handler))
    run = _run(db, lit, settings, p.refresh_client(settings))
    assert run.status == "completed", (run.error, run.warnings)
    structure = seen[1]["contents"][0]["parts"][0]["text"]
    assert "Cited pages:\n- " + REAL in structure and REDIRECT not in structure
    pc = db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id))
    meta = db.scalar(select(RefreshProposalMeta).where(RefreshProposalMeta.proposed_change_id == pc.id))
    assert pc.source_url == REAL and pc.source_id is not None and not meta.off_allowlist
    assert pc.confidence == "low" and meta.needs_second_review  # the HTTP providers cite pages, not passages


def _failing_for(code, error):
    """A refresh client that fails for one geography and finds nothing elsewhere."""
    from app.refresh.claude import FakeRefreshClient

    fake = FakeRefreshClient()

    def boom(prompt):
        raise error

    fake.replies[code] = boom
    return fake


def test_one_failed_geography_does_not_end_the_run(db, lit, reg, settings):
    from app.ai.client import AIError

    fake = _failing_for("US-IL", AIError("The AI provider is unavailable at the moment. Try again later."))
    fake.replies["US-CA"] = {"changes": []}
    run = _run(db, lit, settings, fake, codes=("US-IL", "US-CA"))
    assert [c["key"] for c in fake.calls] == ["US-IL", "US-CA"]  # the second geography was still checked
    assert run.status == "partial", (run.status, run.error)
    assert "US-IL" in run.error and "US-CA" not in run.error
    assert any(w.startswith("US-IL:") and "unavailable" in w for w in run.warnings)
    outcomes = {r["jurisdiction"]: r["outcome"] for r in run.responses}
    assert outcomes == {"US-IL": "failed", "US-CA": "ok"}


def test_a_run_where_every_geography_failed_is_failed(db, lit, reg, settings):
    from app.ai.client import AIError

    fake = _failing_for("US-IL", AIError("The AI provider refused the API key. Check the key and that it is active."))
    run = _run(db, lit, settings, fake)
    assert run.status == "failed" and "refused the API key" in run.error


def test_a_two_geography_run_on_an_http_provider_survives_a_lasting_outage_in_one(db, lit, reg, settings):
    """OpenAI over httpx: Illinois keeps answering 503 (retried, then given up); California is still researched."""
    from app.ai.providers.openai import OpenAIProvider

    asked = []

    def handler(request):
        body = json.loads(request.content)
        text = body.get("input") or body["messages"][1]["content"]
        code = "US-IL" if "Jurisdiction code: US-IL" in text else "US-CA"
        asked.append((code, request.url.path))
        if code == "US-IL":
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        if request.url.path.endswith("/responses"):
            return httpx.Response(200, json={"model": "gpt-x", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Nothing new."}]}]})
        return httpx.Response(200, json={"model": "gpt-x", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"changes": []})}}]})

    p = OpenAIProvider(api_key="sk-test-123456789", model="gpt-x", transport=httpx.MockTransport(handler))
    run = _run(db, lit, settings, p.refresh_client(settings), codes=("US-IL", "US-CA"))
    assert [a for a in asked if a[0] == "US-IL"] == [("US-IL", "/v1/responses")] * 3  # three tries, then given up
    assert ("US-CA", "/v1/chat/completions") in asked
    assert run.status == "partial" and "US-IL" in run.error
