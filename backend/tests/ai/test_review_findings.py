"""Fixes from the independent review of the AI copilot (WS-G): quotes must be long enough to show support, the
"Audited by Futran" label needs a person's confirmation, accepting a suggestion never silently replaces an auditor's
verified answer, long inputs are sent in batches, report narratives are never lost, and explanations never carry an
answer in any field."""
from io import BytesIO

import pytest
from sqlalchemy import select

from app.ai.models import AIInteraction
from app.questionnaire.models import Question, Response
from tests.ai.conftest import CONSENT, enable_ai, upload_docs
from tests.ai.test_obligations import law  # noqa: F401
from tests.factories import login_as
from tests.regmaster.conftest import seeded  # noqa: F401

GOOD = "All models are trained and deployed through the Azure ML pipeline"
XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _prefill(client, w, suggestions):
    w.fake.replies["copilot_prefill"] = {"suggestions": suggestions}
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/prefill", json={"sub_section": "6.1"})
    assert r.status_code == 200, r.text
    return {x["target_code"]: x for x in r.json()["suggestions"]}


def _one(code="6.1.01", answer="mlops", quote=GOOD, page=2, confidence="high"):
    return {"code": code, "answer": answer, "detail": None, "document": "D1", "page": page, "quote": quote, "confidence": confidence, "draft_finding": None}


# ---- G1: a quote must be long enough to show support
def test_quote_check_needs_a_meaningful_passage():
    from app.ai.text import find_quote, quote_in

    pages = [{"page": 1, "text": "The model card says the model owner validates the model. Section 5 Limitations: TBD."}]
    assert find_quote(pages, "the", 1) is None
    assert find_quote(pages, "the model owner", 1) is None  # three words: too short to show anything
    assert find_quote(pages, "Section 5 Limitations: TBD.", 1) == 1  # four words, 27 characters: a real passage
    assert find_quote(pages, "the model owner validates the model", 1) == 1
    assert quote_in(pages[0]["text"], "model") is False and quote_in(pages[0]["text"], "says the model owner validates") is True


def test_prefill_with_a_too_short_quote_is_unsupported(client, db, ai_sys):
    w = ai_sys
    enable_ai(client, db, w)
    upload_docs(client, db, w)
    login_as(client, db, w.people["aud"])
    x = _prefill(client, w, [_one(quote="the", page=9)])["6.1.01"]
    assert x["status"] == "unsupported" and x["citations"][0]["found"] is False
    assert "too short" in x["output"]["note"]
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/accept-high", json={"ids": [x["id"]]})
    assert r.json()["accepted"] == 0


def test_obligation_with_a_too_short_quote_is_unsupported(client, db, seeded, law):
    reg, legal, fake = law
    fake.replies["obligation_extract"] = {"obligations": [
        {"text": "Notify candidates.", "actor": "employer", "action": "notify", "condition": None, "deadline": None, "citation": "§20-871", "quote": "notice",
         "requirement_codes": [], "question_codes": [], "confidence": "high"}]}
    login_as(client, db, legal)
    r = client.post(f"/api/v1/reg/laws/{reg.id}/obligations/extract")
    assert r.status_code == 200, r.text
    o = r.json()["obligations"][0]
    assert o["status"] == "unsupported" and o["quote_found"] is False


@pytest.fixture
def qn(client, db, live, people, app):
    from app.ai.client import FakeAIClient

    cid, e, maria = live
    fake = FakeAIClient()
    app.state.ai_client_factory = lambda s: fake
    login_as(client, db, people["chief"])
    assert client.put(f"/api/v1/engagements/{e.id}/ai", json={"enabled": True, "consent_note": CONSENT}).status_code == 200
    return cid, e, maria, people, fake


def _xlsx(questions) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Question", "Response"])
    for q in questions:
        ws.append([q, None])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _signed_report(db, cid, e, body):
    from app.core.clock import utcnow
    from app.reports.models import Report

    db.add(Report(organization_id=cid, engagement_id=e.id, version="v1.0", status="final", body_md=body, content_hash="x", signed_at=utcnow(), released_to_client_at=utcnow()))
    db.commit()


def test_questionnaire_answer_with_a_too_short_quote_is_unsupported(client, db, qn):
    cid, e, maria, people, fake = qn
    _signed_report(db, cid, e, "# Audit report\n\nThe bias audit found gaps.\n")
    login_as(client, db, maria)
    q = client.post("/api/v1/questionnaires", data={"customer_name": "X"}, files={"file": ("ddq.xlsx", _xlsx(["Do you hold ISO 42001 certification for your AI management system?"]), XLSX_CT)}).json()
    fake.replies["questionnaire"] = {"answers": [{"item": "Q1", "answer": "Yes. We are ISO 42001 certified.", "source": "R1", "quote": "audit", "confidence": "high"}]}
    it = client.post(f"/api/v1/questionnaires/{q['id']}/draft").json()["items"][0]
    assert it["status"] == "unsupported" and it["audited_by_futran"] is False and it["citations"][0]["found"] is False


# ---- G4: verifying an accepted AI answer keeps its source
def test_verifying_an_accepted_ai_answer_keeps_its_source(client, db, ai_sys):
    w = ai_sys
    enable_ai(client, db, w)
    upload_docs(client, db, w)
    login_as(client, db, w.people["aud"])
    x = _prefill(client, w, [_one()])["6.1.01"]
    assert client.post(f"/api/v1/ai/interactions/{x['id']}/accept", json={}).status_code == 200
    rid = db.get(AIInteraction, x["id"]).result_refs[0]["id"]
    person = {"source_person_name": "Jane Roe", "source_person_title": "Head of Data Science"}
    r = client.put(f"/api/v1/systems/{w.s.id}/responses/6.1.01", json={"status": "answered", "value": "mlops", "verified": True} | person)
    assert r.status_code == 200, r.text
    db.expire_all()
    resp = db.get(Response, rid)
    assert resp.source == "ai_suggested_accepted" and resp.verified_at is not None
    other = next(str(o["value"]) for o in db.scalar(select(Question).where(Question.code == "6.1.01")).options if str(o["value"]) != "mlops")
    assert client.put(f"/api/v1/systems/{w.s.id}/responses/6.1.01", json={"status": "answered", "value": other} | person).status_code == 200
    db.expire_all()
    assert db.get(Response, rid).source == "auditor"  # the auditor changed the answer: it is now their own
