import pytest
from sqlalchemy import select

from app.core.clock import utcnow
from app.engagements.models import Engagement
from app.findings.models import Finding
from app.questionnaire.models import Question
from app.questionnaire.seed import load_question_bank
from app.systems.models import AISystem
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401

LIGHT = {"3.1", "3.2", "3.3", "5.1", "5.1a", "5.2", "5.3", "7.2", "9.2"}


@pytest.fixture
def sys1(client, db, inv, people):
    """ABC Corp's SYS-001 (HireScore), vendor-built, full depth; Alex is on the team."""
    load_question_bank(db)
    cid, e, maria, hr, *_ = inv
    s = db.scalar(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.reference_id == "SYS-001"))
    s.built_by, s.department_id = "vendor", hr.id
    db.commit()
    return cid, e, maria, s


def _get(client, s):
    r = client.get(f"/api/v1/systems/{s.id}/assessment")
    assert r.status_code == 200, r.text
    return r.json()


def _put(client, s, code, **body):
    return client.put(f"/api/v1/systems/{s.id}/responses/{code}", json=body)


def test_client_sees_only_client_questions(client, db, sys1, people):
    cid, e, maria, s = sys1
    login_as(client, db, maria)
    d = _get(client, s)
    codes = {q["code"] for q in d["questions"]}
    assert "3.1.01" in codes and "3.3.05s" not in codes
    auditor_only = {q.code for q in db.scalars(select(Question).where(Question.default_respondent == "auditor"))}
    assert not codes & auditor_only
    assert "checklists" not in d and "draft_findings" not in d
    assert all("note" not in sec for sec in d["sections"])
    login_as(client, db, people["aud"])
    futran = _get(client, s)
    assert "3.3.05s" in {q["code"] for q in futran["questions"]}
    assert any(sec.get("note") for sec in futran["sections"]) and "checklists" in futran


def test_client_never_sees_verified_or_auditor_answers(client, db, sys1, people):
    cid, e, maria, s = sys1
    login_as(client, db, maria)
    assert _put(client, s, "3.1.03", value="4.1", status="answered").status_code == 200
    login_as(client, db, people["aud"])
    r = _put(client, s, "3.1.03", value="4.2", status="answered", verified=True, source_person_name="Lee Park", source_person_title="HR systems lead")
    assert r.status_code == 200, r.text
    q = next(q for q in _get(client, s)["questions"] if q["code"] == "3.1.03")
    assert q["response"]["value"] == "4.2" and q["response"]["client_value"] == "4.1" and q["response"]["verified"] is True
    login_as(client, db, maria)
    q = next(q for q in _get(client, s)["questions"] if q["code"] == "3.1.03")
    assert q["response"] == {"value": "4.1", "status": "answered", "na_reason": None, "detail": None, "evidence": []}


def test_na_requires_reason(client, db, sys1):
    cid, e, maria, s = sys1
    login_as(client, db, maria)
    r = _put(client, s, "3.1.08", status="na")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "na_reason"
    assert _put(client, s, "3.1.08", status="na", na_reason="No major update since go-live.").status_code == 200
    r = _put(client, s, "3.1.10", value="sometimes", status="answered")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "value"


def test_verified_interview_requires_source_person(client, db, sys1, people):
    cid, e, maria, s = sys1
    login_as(client, db, people["aud"])
    r = _put(client, s, "3.1.03", value="4.2", status="answered", verified=True)
    assert r.status_code == 422 and {x["field"] for x in r.json()["errors"]} == {"source_person_name", "source_person_title"}
    r = _put(client, s, "3.1.03", value="4.2", status="answered")
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.post(f"/api/v1/responses/{rid}/verify").status_code == 422  # recorded by Futran: say who said so
    # a client answer can be verified as it stands
    login_as(client, db, maria)
    rid2 = _put(client, s, "3.1.01", value="HireScore Recruit", status="answered").json()["id"]
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/responses/{rid2}/verify").status_code == 200
    login_as(client, db, maria)
    assert client.post(f"/api/v1/responses/{rid2}/verify").status_code == 403


def test_checklist_tick_requires_evidence(client, db, sys1, people):
    cid, e, maria, s = sys1
    login_as(client, db, people["aud"])
    r = client.put(f"/api/v1/systems/{s.id}/checklist/5.4.01", json={"confirmed": True})
    assert r.status_code == 422 and r.json()["errors"][0]["message"] == "Link at least one evidence file before ticking this item."
    up = client.post(f"/api/v1/systems/{s.id}/evidence", files={"file": ("policy.pdf", b"%PDF-1.4 classification policy", "application/pdf")})
    assert up.status_code == 200, up.text
    r = client.put(f"/api/v1/systems/{s.id}/checklist/5.4.01", json={"confirmed": True, "evidence_ids": [up.json()["id"]]})
    assert r.status_code == 200 and r.json()["confirmed"] is True
    assert client.put(f"/api/v1/systems/{s.id}/checklist/5.4.01", json={"confirmed": True, "evidence_ids": ["not-a-file"]}).status_code == 422
    login_as(client, db, maria)
    assert client.put(f"/api/v1/systems/{s.id}/checklist/5.4.01", json={"confirmed": False}).status_code == 403


def test_not_yet_in_place_creates_draft_finding(client, db, sys1, people):
    cid, e, maria, s = sys1
    login_as(client, db, maria)
    assert _put(client, s, "6.2.01", status="not_yet_in_place", detail="We plan to test next quarter.").status_code == 200
    f = db.scalar(select(Finding).where(Finding.ai_system_id == s.id, Finding.deleted_at.is_(None)))
    assert f is not None and f.status == "draft" and f.severity == "high" and f.source_question_ids == ["6.2.01"] and f.ref == "F-001"
    assert f.title == "No bias testing on an AI system that affects people"
    assert "draft_findings" not in _get(client, s)  # never shown to the client
    login_as(client, db, people["aud"])
    drafts = _get(client, s)["draft_findings"]
    assert [(x["ref"], x["question_code"]) for x in drafts] == [("F-001", "6.2.01")]
    # the answer changes to Yes: the untouched draft goes away
    login_as(client, db, maria)
    _put(client, s, "6.2.01", value="yes", status="answered")
    db.expire_all()
    assert db.scalar(select(Finding).where(Finding.ai_system_id == s.id, Finding.deleted_at.is_(None))) is None
    # No again: a new draft with a new number; the auditor dismisses it with a reason
    _put(client, s, "6.2.01", value="no", status="answered")
    login_as(client, db, people["aud"])
    d = _get(client, s)["draft_findings"]
    assert d[0]["ref"] == "F-002"
    assert client.post(f"/api/v1/draft-findings/{d[0]['id']}/dismiss", json={"reason": ""}).status_code == 422
    assert client.post(f"/api/v1/draft-findings/{d[0]['id']}/dismiss", json={"reason": "Vendor's test covers this population."}).status_code == 200
    assert _get(client, s)["draft_findings"] == []
    # a dismissed draft is not recreated by saving the same answer again
    login_as(client, db, maria)
    _put(client, s, "6.2.01", value="no", status="answered", detail="still no")
    db.expire_all()
    assert db.scalar(select(Finding).where(Finding.ai_system_id == s.id, Finding.deleted_at.is_(None))) is None


def test_light_system_shows_only_light_questions(client, db, sys1, people):
    cid, e, maria, s = sys1
    s.assessment_depth = "light"
    db.commit()
    login_as(client, db, people["aud"])
    d = _get(client, s)
    subs = {q["sub_section"] for q in d["questions"]}
    assert subs <= LIGHT and "7.2" in subs and "9.2" in subs
    assert {c["section"] for c in d["checklists"]} <= {"5.4", "9.3"}


def test_build_type_picks_sections(client, db, sys1, people):
    cid, e, maria, s = sys1
    login_as(client, db, people["aud"])
    subs = {q["sub_section"] for q in _get(client, s)["questions"]}
    assert "V" in subs and "6.1" not in subs and "6.3" not in subs and "OS" not in subs
    s.built_by = "in_house"
    db.commit()
    subs = {q["sub_section"] for q in _get(client, s)["questions"]}
    assert "V" not in subs and "6.1" in subs and "9.2" not in subs


def test_client_write_after_snapshot_conflict(client, db, sys1, people):
    cid, e, maria, s = sys1
    db.get(Engagement, e.id).client_answers_locked_at = utcnow()
    db.commit()
    login_as(client, db, maria)
    r = _put(client, s, "3.1.03", value="4.1", status="answered")
    assert r.status_code == 409 and r.json()["detail"] == "Answers are locked after management representation; ask the auditor to reopen."
    login_as(client, db, people["aud"])
    assert _put(client, s, "3.1.03", value="4.1", status="answered", source_person_name="Lee Park", source_person_title="HR systems lead").status_code == 200
    s.status = "locked"
    db.commit()
    assert _put(client, s, "3.1.03", value="4.3", status="answered").status_code == 409


def test_completion_counts(client, db, sys1, people):
    cid, e, maria, s = sys1
    login_as(client, db, maria)
    _put(client, s, "3.1.01", value="HireScore Recruit", status="answered")
    _put(client, s, "3.1.08", status="na", na_reason="None yet.")
    _put(client, s, "6.2.01", status="not_yet_in_place")
    login_as(client, db, people["aud"])
    d = _get(client, s)
    applicable = len(d["questions"])
    assert d["completion"]["answered"] == 3 and d["completion"]["applicable"] == applicable
    sec = next(x for x in d["sections"] if x["code"] == "3.1")
    assert (sec["answered"], sec["applicable"]) == (2, 10)
    db.expire_all()
    assert db.get(AISystem, s.id).completion_pct == round(300 / applicable)
    assert db.get(AISystem, s.id).status == "client_prefill"


def test_prefill_submit_needs_required_answers(client, db, sys1):
    cid, e, maria, s = sys1
    login_as(client, db, maria)
    r = client.post(f"/api/v1/systems/{s.id}/prefill/submit")
    assert r.status_code == 422 and any(x["field"] == "3.1.01" for x in r.json()["errors"])


def test_contributor_elsewhere_cannot_prefill(client, db, sys1):
    cid, e, maria, s = sys1
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Finance"})
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Fin", "last_name": "Staff", "email": "fin@abc.test", "department": "Finance", "role": "contributor"})
    from app.tenancy.models import User

    fin = db.scalar(select(User).where(User.email == "fin@abc.test"))
    fin.status = "active"
    db.commit()
    login_as(client, db, fin)
    assert client.get(f"/api/v1/systems/{s.id}/assessment").status_code == 403
    assert _put(client, s, "3.1.03", value="x", status="answered").status_code == 403
