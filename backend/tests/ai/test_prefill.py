"""Screen 25 document pre-fill (F1): suggestions per template question with document, page, quote and confidence;
quotes are checked against the documents (rule 2); nothing is saved until a named auditor accepts (rule 1); every
suggestion and decision is logged (rule 3)."""
from sqlalchemy import func, select

from app.ai.models import AIInteraction
from app.audit_log.models import AuditLog
from app.docrequests.models import EvidenceRequest
from app.findings.models import Finding
from app.questionnaire.models import Question, Response
from tests.ai.conftest import enable_ai, upload_docs
from tests.factories import login_as

GOOD = "All models are trained and deployed through the Azure ML pipeline"
REPLY = {"suggestions": [
    {"code": "6.1.01", "answer": "mlops", "detail": "Azure ML pipeline with staged approval gates.", "document": "D1", "page": 2, "quote": GOOD, "confidence": "high", "draft_finding": None},
    {"code": "6.1.02", "answer": "no", "detail": "The model card leaves the limitations section empty.", "document": "D2", "page": 1, "quote": "Section 5 Limitations: TBD.", "confidence": "medium",
     "draft_finding": {"title": "Model card incomplete", "severity": "medium", "condition": "The model card has no documented limitations.", "criteria": "Template §6.1 expects a complete model card.",
                       "cause": "Documentation was not finished before release.", "effect": "Reviewers cannot judge where the model should not be relied on.",
                       "recommendation": "Complete section 5 of the model card and have the model owner approve it."}},
    {"code": "6.1.07", "answer": None, "detail": None, "document": None, "page": None, "quote": None, "confidence": "low", "not_found_note": "No passage covers reproducibility.", "draft_finding": None},
    {"code": "6.1.08", "answer": "Changes go through the change advisory board.", "detail": None, "document": "D1", "page": 3, "quote": "All changes are approved by the change advisory board.", "confidence": "high", "draft_finding": None},
    {"code": "6.1.06", "answer": "magic", "detail": None, "document": "D1", "page": 2, "quote": GOOD, "confidence": "high", "draft_finding": None},
]}


def _run(client, db, w, reply=REPLY):
    enable_ai(client, db, w)
    files = upload_docs(client, db, w)
    w.fake.replies["copilot_prefill"] = reply
    login_as(client, db, w.people["aud"])
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/prefill", json={"sub_section": "6.1"})
    assert r.status_code == 200, r.text
    return files, {x["target_code"]: x for x in r.json()["suggestions"]}


def test_prefill_suggests_with_checked_citations_and_saves_nothing(client, db, ai_sys):
    w = ai_sys
    files, s = _run(client, db, w)
    codes_in_section = {q.code for q in db.scalars(select(Question).where(Question.sub_section == "6.1"))}
    assert set(s) == codes_in_section  # one suggestion row per question, unanswered ones too
    assert len({x["call_id"] for x in s.values()}) == 1
    assert s["6.1.01"]["status"] == "suggested" and s["6.1.01"]["confidence"] == "high" and s["6.1.01"]["output"]["value"] == "mlops"
    assert s["6.1.01"]["citations"] == [{"file_id": files["Model_Governance_Standard_v3.pdf"], "filename": "Model_Governance_Standard_v3.pdf", "page": 2, "quote": GOOD, "found": True}]
    assert s["6.1.02"]["status"] == "suggested" and s["6.1.02"]["output"]["draft_finding"]["title"] == "Model card incomplete"
    assert s["6.1.07"]["status"] == "unsupported" and s["6.1.07"]["output"]["note"] == "No passage covers reproducibility."
    assert s["6.1.08"]["status"] == "unsupported" and s["6.1.08"]["citations"][0]["found"] is False  # the quote is not in the document
    assert s["6.1.06"]["status"] == "unsupported"  # not one of the question's options
    assert s["6.1.05"]["status"] == "unsupported"  # the model said nothing about it
    assert db.scalar(select(func.count()).select_from(Response).where(Response.ai_system_id == w.s.id)) == 0
    assert db.scalar(select(AuditLog).where(AuditLog.action == "ai.suggest")) is not None
    call = w.fake.calls[-1]
    assert "Azure ML pipeline" in call["prompt"] and "6.1.01" in call["prompt"] and "Model development methodology" in call["prompt"]
    assert "only" in call["system"].lower() and "quote" in call["system"].lower()
    # the panel shows the latest run for the section
    panel = client.get(f"/api/v1/systems/{w.s.id}/copilot?section=6.1").json()
    assert {x["target_code"] for x in panel["suggestions"]} == codes_in_section and len(panel["documents"]) == 2


def test_accept_edit_and_reject(client, db, ai_sys):
    w = ai_sys
    files, s = _run(client, db, w)
    r = client.post(f"/api/v1/ai/interactions/{s['6.1.01']['id']}/accept", json={})
    assert r.status_code == 200, r.text
    resp = db.scalar(select(Response).join(Question, Question.id == Response.question_id).where(Response.ai_system_id == w.s.id, Question.code == "6.1.01"))
    assert resp.value == "mlops" and resp.source == "ai_suggested_accepted" and resp.verified_at is None and resp.answered_side == "futran"
    assert files["Model_Governance_Standard_v3.pdf"] in resp.evidence_ids and GOOD in resp.detail
    i = db.get(AIInteraction, s["6.1.01"]["id"])
    assert i.status == "accepted" and i.decided_by == w.people["aud"].id and i.result_refs == [{"type": "response", "id": resp.id}]
    assert client.post(f"/api/v1/ai/interactions/{i.id}/accept", json={}).status_code == 409  # decided once

    r = client.post(f"/api/v1/ai/interactions/{s['6.1.02']['id']}/accept", json={"value": "yes", "detail": "Card exists; limitations missing."})
    assert r.status_code == 200 and db.get(AIInteraction, s["6.1.02"]["id"]).status == "edited"

    assert client.post(f"/api/v1/ai/interactions/{s['6.1.07']['id']}/accept", json={"value": "yes"}).status_code == 409  # unsupported
    assert client.post(f"/api/v1/ai/interactions/{s['6.1.05']['id']}/reject", json={"reason": ""}).status_code == 422
    assert client.post(f"/api/v1/ai/interactions/{s['6.1.05']['id']}/reject", json={"reason": "Asked in interview instead."}).status_code == 200
    assert db.get(AIInteraction, s["6.1.05"]["id"]).reason == "Asked in interview instead."


def test_accept_answer_and_create_draft_finding(client, db, ai_sys):
    w = ai_sys
    files, s = _run(client, db, w)
    r = client.post(f"/api/v1/ai/interactions/{s['6.1.02']['id']}/accept", json={"create_finding": True})
    assert r.status_code == 200, r.text
    f = db.scalar(select(Finding).where(Finding.engagement_id == w.e.id, Finding.origin == "ai_suggestion"))
    assert f.status == "draft" and f.severity == "medium" and f.title == "Model card incomplete" and f.source_question_ids == ["6.1.02"] and f.author_id == w.people["aud"].id
    assert "Condition: The model card has no documented limitations." in f.description and "Cause:" in f.description and f.recommended_remediation.startswith("Complete section 5")
    assert {"type": "finding", "id": f.id} in db.get(AIInteraction, s["6.1.02"]["id"]).result_refs
    assert client.post(f"/api/v1/ai/interactions/{s['6.1.01']['id']}/accept", json={"create_finding": True}).status_code == 422  # no draft finding suggested


def test_accept_all_high_confidence_logs_each_acceptance(client, db, ai_sys):
    w = ai_sys
    reply = {"suggestions": REPLY["suggestions"][:2] + [{"code": "6.1.04", "answer": "70/15/15 split by invoice date", "detail": None, "document": "D1", "page": 2, "quote": "with staged approval gates (dev, UAT, prod).", "confidence": "high", "draft_finding": None}]}
    files, s = _run(client, db, w, reply)
    before = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "ai.accept"))
    ids = [x["id"] for x in s.values()]  # the screen sends what it shows; only high-confidence supported ones are taken
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/accept-high", json={"ids": ids})
    assert r.status_code == 200 and r.json()["accepted"] == 2
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "ai.accept")) == before + 2
    assert db.get(AIInteraction, s["6.1.02"]["id"]).status == "suggested"


def test_unsupported_goes_to_the_interview_list_or_an_evidence_request(client, db, ai_sys):
    w = ai_sys
    files, s = _run(client, db, w)
    assert client.post(f"/api/v1/ai/interactions/{s['6.1.07']['id']}/interview").status_code == 200
    panel = client.get(f"/api/v1/systems/{w.s.id}/copilot?section=6.1").json()
    assert [x["target_code"] for x in panel["interview_list"]] == ["6.1.07"]
    r = client.post(f"/api/v1/ai/interactions/{s['6.1.05']['id']}/evidence-request", json={"description": "Hyperparameter tuning records for the current model", "due_date": "2099-01-31"})
    assert r.status_code == 200, r.text
    er = db.scalar(select(EvidenceRequest).where(EvidenceRequest.engagement_id == w.e.id))
    assert er.ai_system_id == w.s.id and er.ref == "ER-001" and db.get(AIInteraction, s["6.1.05"]["id"]).follow_up_ref == "ER-001"


def test_clients_and_unassigned_auditors_never_reach_the_copilot(client, db, ai_sys):
    w = ai_sys
    files, s = _run(client, db, w)
    login_as(client, db, w.maria)
    assert client.get(f"/api/v1/systems/{w.s.id}/copilot?section=6.1").status_code in (403, 404)
    assert client.post(f"/api/v1/ai/interactions/{s['6.1.01']['id']}/accept", json={}).status_code in (403, 404)
    login_as(client, db, w.people["aud2"])
    assert client.post(f"/api/v1/systems/{w.s.id}/copilot/prefill", json={"sub_section": "6.1"}).status_code == 404
