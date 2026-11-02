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


# ---- G8: every text field of an explanation is checked
def test_an_answer_hidden_in_a_term_meaning_is_replaced(client, db, ai_sys):
    w = ai_sys
    enable_ai(client, db, w)
    w.fake.replies["explain"] = {"explanation": "This question asks whether a person can override the system's output.",
                                 "terms": [{"term": "Human oversight", "meaning": "A person reviews outputs. For your system the answer is Yes, so choose that."}]}
    login_as(client, db, w.maria)
    d = client.post(f"/api/v1/systems/{w.s.id}/questions/7.1.02/explain").json()
    assert "the answer is" not in str(d).lower() and "choose that" not in str(d).lower()
    assert d["terms"] and all("answer is" not in t["meaning"].lower() for t in d["terms"])
    row = db.scalar(select(AIInteraction).where(AIInteraction.feature == "explain"))
    assert row.status == "rejected" and row.output["proposed_an_answer"] is True


# ---- G3: accepting a suggestion never silently replaces the auditor's answer
def _opts(db, code):
    return [str(o["value"]) for o in db.scalar(select(Question).where(Question.code == code)).options or []]


def _response(db, w, code):
    db.expire_all()
    return db.scalar(select(Response).join(Question, Question.id == Response.question_id).where(Response.ai_system_id == w.s.id, Question.code == code))


def test_accepting_does_not_replace_a_verified_or_different_auditor_answer(client, db, ai_sys):
    w = ai_sys
    enable_ai(client, db, w)
    upload_docs(client, db, w)
    login_as(client, db, w.people["aud"])
    other = [o for o in _opts(db, "6.1.01") if o != "mlops"][0]
    person = {"source_person_name": "Jane Roe", "source_person_title": "Head of Data Science"}
    assert client.put(f"/api/v1/systems/{w.s.id}/responses/6.1.01", json={"status": "answered", "value": other, "verified": True} | person).status_code == 200
    yn = [o for o in _opts(db, "6.1.02") if o in ("yes", "no")]
    assert client.put(f"/api/v1/systems/{w.s.id}/responses/6.1.02", json={"status": "answered", "value": yn[0]} | person).status_code == 200  # unverified Futran answer
    s = _prefill(client, w, [_one(), _one(code="6.1.02", answer=yn[1], quote="Validation is performed by the model owner before each release.", page=3)])
    a, b = s["6.1.01"], s["6.1.02"]
    # the card shows what is there now
    assert a["current"]["value"] == other and a["current"]["verified"] is True and a["current"]["display"]
    assert b["current"]["value"] == yn[0] and b["current"]["verified"] is False
    panel = {x["target_code"]: x for x in client.get(f"/api/v1/systems/{w.s.id}/copilot?section=6.1").json()["suggestions"]}
    assert panel["6.1.01"]["current"]["verified"] is True and panel["6.1.03"]["current"] is None
    # accept all high-confidence skips both
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/accept-high", json={"ids": [a["id"], b["id"]]})
    assert r.status_code == 200 and r.json()["accepted"] == 0 and sorted(r.json()["skipped"]) == ["6.1.01", "6.1.02"]
    resp = _response(db, w, "6.1.01")
    assert resp.value == other and resp.verified_at is not None and resp.source == "auditor"
    # a single accept needs an explicit override
    r = client.post(f"/api/v1/ai/interactions/{a['id']}/accept", json={})
    assert r.status_code == 409 and "verified" in r.json()["detail"]
    assert client.post(f"/api/v1/ai/interactions/{b['id']}/accept", json={}).status_code == 409
    assert _response(db, w, "6.1.01").verified_at is not None
    r = client.post(f"/api/v1/ai/interactions/{a['id']}/accept", json={"override": True})
    assert r.status_code == 200, r.text
    resp = _response(db, w, "6.1.01")
    assert resp.value == "mlops" and resp.verified_at is None and resp.source == "ai_suggested_accepted"


def test_accept_high_still_accepts_where_the_answer_is_the_same_or_empty(client, db, ai_sys):
    w = ai_sys
    enable_ai(client, db, w)
    upload_docs(client, db, w)
    login_as(client, db, w.people["aud"])
    assert client.put(f"/api/v1/systems/{w.s.id}/responses/6.1.01", json={"status": "answered", "value": "mlops"}).status_code == 200
    a = _prefill(client, w, [_one()])["6.1.01"]
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/accept-high", json={"ids": [a["id"]]})
    assert r.json()["accepted"] == 1 and r.json()["skipped"] == []


# ---- G7: using a summary in the report never loses a hand-written narrative
def test_using_a_summary_in_the_report_needs_confirmation_and_keeps_the_old_text_in_the_log(client, db, ai_sys):
    from app.audit_log.models import AuditLog
    from app.reports.models import ReportNarrative
    from tests.ai.test_review import _ready

    w = ai_sys
    _ready(client, db, w)
    client.put(f"/api/v1/systems/{w.s.id}/responses/6.2.01", json={"status": "answered", "value": "no"})  # raises F-001
    login_as(client, db, w.people["chief"])
    hand = "Written by the lead auditor after the closing meeting. The HR team has a mature review process."
    r = client.put(f"/api/v1/clients/{w.cid}/report/summary", json={"narrative": hand, "strengths": "Clear ownership.", "immediate_actions": "Run a bias test."})
    assert r.status_code == 200, r.text
    w.fake.replies["summary"] = {"summary": "ABC Corp's HireScore deployment was reviewed. Finding F-001 is the most significant.", "sources": ["F-001", "6.2.01"], "confidence": "medium"}
    s = client.post(f"/api/v1/engagements/{w.e.id}/copilot/summary", json={"kind": "engagement"}).json()
    r = client.post(f"/api/v1/ai/interactions/{s['id']}/accept", json={"use_in_report": True})
    assert r.status_code == 409 and "narrative" in r.json()["detail"].lower()
    db.expire_all()
    assert db.scalar(select(ReportNarrative).where(ReportNarrative.engagement_id == w.e.id)).narrative == hand
    assert db.get(AIInteraction, s["id"]).status == "suggested"  # nothing decided yet
    r = client.post(f"/api/v1/ai/interactions/{s['id']}/accept", json={"use_in_report": True, "replace_narrative": True})
    assert r.status_code == 200, r.text
    db.expire_all()
    n = db.scalar(select(ReportNarrative).where(ReportNarrative.engagement_id == w.e.id))
    assert n.narrative.startswith("ABC Corp") and n.strengths == "Clear ownership." and n.immediate_actions == "Run a bias test."
    row = next(x for x in db.scalars(select(AuditLog).where(AuditLog.action == "report.summary")) if (x.after or {}).get("narrative", "").startswith("ABC Corp"))
    assert row.before["narrative"] == hand
    assert set(row.before) >= {"narrative", "strengths", "immediate_actions", "most_significant_text", "most_significant_finding_id"}
