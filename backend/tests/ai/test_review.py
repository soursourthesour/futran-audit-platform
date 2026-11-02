"""Screen 25 beyond pre-fill: evidence check per checklist item, the completeness review before sign-offs 5 and 7,
"Ask the copilot", draft finding text and summaries, and the engagement's AI interaction log."""
from sqlalchemy import select

from app.ai.models import AIInteraction
from app.engagements.models import EngagementTeam
from app.findings.models import Finding
from app.questionnaire.models import ChecklistResult
from app.reports.models import ReportNarrative
from tests.ai.conftest import enable_ai, upload_docs
from tests.factories import login_as, make_user


def _ready(client, db, w):
    enable_ai(client, db, w)
    files = upload_docs(client, db, w)
    login_as(client, db, w.people["aud"])
    return files


def test_evidence_check_reads_only_linked_evidence_and_never_ticks(client, db, ai_sys):
    w = ai_sys
    files = _ready(client, db, w)
    std = files["Model_Governance_Standard_v3.pdf"]
    assert client.put(f"/api/v1/systems/{w.s.id}/checklist/6.4.05", json={"confirmed": True, "evidence_ids": [std]}).status_code == 200
    w.fake.replies["evidence_check"] = {"items": [{"code": "6.4.05", "verdict": "does_not_support", "reason": "Validation is done by the model owner, so it is not independent.",
                                                   "document": "D1", "page": 3, "quote": "Validation is performed by the model owner before each release.", "confidence": "high"}]}
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/evidence-check", json={"section": "6.4"})
    assert r.status_code == 200, r.text
    rows = {x["code"]: x for x in r.json()["items"]}
    assert rows["6.4.05"]["suggestion"]["output"]["verdict"] == "does_not_support" and rows["6.4.05"]["suggestion"]["citations"][0]["found"] is True
    others = [c for c in rows if c != "6.4.05"]
    assert others and all(rows[c]["suggestion"] is None and rows[c]["status"] == "no_evidence" for c in others)  # no AI where nothing is linked
    ctx = w.fake.calls[-1]["context"]
    assert [d["filename"] for d in ctx["documents"]] == ["Model_Governance_Standard_v3.pdf"]  # only the linked file
    i = rows["6.4.05"]["suggestion"]["id"]
    assert client.post(f"/api/v1/ai/interactions/{i}/accept", json={}).status_code == 200
    res = db.scalar(select(ChecklistResult).where(ChecklistResult.ai_system_id == w.s.id))
    assert res.confirmed is True and "not independent" in res.auditor_note  # the note is recorded; the tick is the auditor's own


def test_completeness_review_deterministic_parts_and_cited_contradictions(client, db, ai_sys):
    w = ai_sys
    _ready(client, db, w)
    # an interview answer with no source person, and one with a source person that the model card contradicts
    client.put(f"/api/v1/systems/{w.s.id}/responses/6.1.03", json={"status": "answered", "value": "yes"})
    client.put(f"/api/v1/systems/{w.s.id}/responses/8.2.05", json={"status": "answered", "value": "daily", "source_person_name": "Lee Park", "source_person_title": "Data science lead"})
    w.fake.replies["review_check"] = {"contradictions": [
        {"code": "8.2.05", "interview_says": "Monitoring runs daily.", "document_says": "The model card says weekly.", "document": "D2", "page": 1,
         "quote": "Section 6 Monitoring: drift is monitored weekly by the data science team.", "confidence": "high"},
        {"code": "8.2.01", "interview_says": "x", "document_says": "y", "document": "D2", "page": 1, "quote": "A sentence that is not there.", "confidence": "low"}]}
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/completeness", json={"signoff": 5})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["signoff"] == 5
    assert "6.1.01" in {x["code"] for x in d["unanswered_required"]}  # required and unanswered
    assert {x["code"] for x in d["missing_source_person"]} == {"6.1.03"}
    assert d["ticks_without_evidence"] == []
    c = {x["target_code"]: x for x in d["contradictions"]}
    assert c["8.2.05"]["status"] == "suggested" and c["8.2.01"]["status"] == "unsupported"
    assert "Lee Park" in w.fake.calls[-1]["prompt"] and "weekly" in w.fake.calls[-1]["prompt"]
    # the deterministic part needs no model: it is on the panel even when the model is not set up
    client.app.state.ai_client_factory = lambda s: None
    g = client.get(f"/api/v1/systems/{w.s.id}/copilot/completeness?signoff=7").json()
    assert g["signoff"] == 7 and {x["code"] for x in g["missing_source_person"]} == {"6.1.03"} and len(g["contradictions"]) == 2


def test_ask_the_copilot_answers_with_checked_citations(client, db, ai_sys):
    w = ai_sys
    _ready(client, db, w)
    w.fake.replies["ask"] = {"answer": "None of the documents describes an independent validation. The standard says the model owner validates.",
                             "citations": [{"document": "D1", "page": 3, "quote": "Validation is performed by the model owner"}], "confidence": "high"}
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/ask", json={"question": "Which evidence supports independent validation?"})
    assert r.status_code == 200 and r.json()["status"] == "suggested" and r.json()["citations"][0]["page"] == 3
    w.fake.replies["ask"] = {"answer": "Validation is independent.", "citations": [], "confidence": "medium"}
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/ask", json={"question": "Is validation independent?"})
    assert r.json()["status"] == "unsupported"
    assert client.post(f"/api/v1/systems/{w.s.id}/copilot/ask", json={"question": " "}).status_code == 422
    # the fieldwork view asks across the whole engagement
    r = client.post(f"/api/v1/engagements/{w.e.id}/copilot/ask", json={"question": "Who validates the model?"})
    assert r.status_code == 200


def test_draft_finding_text_is_a_suggestion_the_auditor_applies(client, db, ai_sys):
    w = ai_sys
    _ready(client, db, w)
    client.put(f"/api/v1/systems/{w.s.id}/responses/6.2.01", json={"status": "answered", "value": "no"})  # raises an auto-draft
    f = db.scalar(select(Finding).where(Finding.ai_system_id == w.s.id, Finding.deleted_at.is_(None)))
    w.fake.replies["draft_finding"] = {"title": "No bias testing before use", "severity": "high", "condition": "The system has not been tested for bias.", "criteria": "Template §6.2.01.",
                                       "cause": "No testing procedure exists.", "effect": "Unfair outcomes may go undetected.", "recommendation": "Run a bias test before the next release."}
    r = client.post(f"/api/v1/findings/{f.id}/copilot/draft-text")
    assert r.status_code == 200, r.text
    assert "6.2.01" in w.fake.calls[-1]["prompt"]
    db.refresh(f)
    assert f.title != "No bias testing before use"  # nothing changes until accepted
    assert client.post(f"/api/v1/ai/interactions/{r.json()['id']}/accept", json={}).status_code == 200
    db.refresh(f)
    assert f.title == "No bias testing before use" and f.status == "draft" and f.description.startswith("Condition: The system has not been tested")


def test_summaries_for_the_chief_auditor_and_the_report(client, db, ai_sys):
    w = ai_sys
    _ready(client, db, w)
    client.put(f"/api/v1/systems/{w.s.id}/responses/6.2.01", json={"status": "answered", "value": "no"})  # raises F-001
    w.fake.replies["summary"] = {"summary": "ABC Corp's HireScore deployment was reviewed. Finding F-001 is the most significant.", "sources": ["F-001", "6.2.01"], "confidence": "medium"}
    login_as(client, db, w.people["chief"])
    r = client.post(f"/api/v1/engagements/{w.e.id}/copilot/summary", json={"kind": "engagement"})
    assert r.status_code == 200 and r.json()["output"]["summary"].startswith("ABC Corp")
    assert client.post(f"/api/v1/ai/interactions/{r.json()['id']}/accept", json={"use_in_report": True}).status_code == 200
    n = db.scalar(select(ReportNarrative).where(ReportNarrative.engagement_id == w.e.id))
    assert n.narrative.startswith("ABC Corp")
    assert client.post(f"/api/v1/systems/{w.s.id}/copilot/summary", json={}).status_code == 200
    w.fake.replies["summary"] = {"summary": "Everything is fine.", "sources": ["F-999"], "confidence": "high"}
    r = client.post(f"/api/v1/engagements/{w.e.id}/copilot/summary", json={"kind": "engagement"})
    assert r.json()["status"] == "unsupported"  # it relies on a finding that does not exist


def test_the_ai_log_is_for_the_chief_lead_and_qa_only(client, db, ai_sys):
    w = ai_sys
    _ready(client, db, w)
    w.fake.replies["ask"] = {"answer": "The model owner validates.", "citations": [{"document": "D1", "page": 3, "quote": "Validation is performed by the model owner"}], "confidence": "high"}
    client.post(f"/api/v1/systems/{w.s.id}/copilot/ask", json={"question": "Who validates?"})
    assert client.get(f"/api/v1/engagements/{w.e.id}/ai-log").status_code == 403  # the auditor uses the copilot but does not read the log
    from app.tenancy.models import Organization

    qa = make_user(db, db.get(Organization, w.people["aud"].organization_id), roles=["qa_reviewer"], name="Quinn QA", email="quinn@futran.test")
    db.add(EngagementTeam(organization_id=w.e.client_id, engagement_id=w.e.id, user_id=qa.id, role="qa_reviewer"))
    db.commit()
    login_as(client, db, qa)
    log = client.get(f"/api/v1/engagements/{w.e.id}/ai-log").json()
    assert log["rows"][0]["feature"] == "ask" and log["rows"][0]["requested_by"] == "Alex Auditor" and log["rows"][0]["model"] == "fake-ai"
    assert log["totals"]["suggestions"] >= 1
    login_as(client, db, w.maria)
    assert client.get(f"/api/v1/engagements/{w.e.id}/ai-log").status_code in (403, 404)
    assert db.scalar(select(AIInteraction).where(AIInteraction.feature == "ask")).engagement_id == w.e.id
