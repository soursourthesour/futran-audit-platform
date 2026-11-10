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
