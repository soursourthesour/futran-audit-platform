"""Screen 28: new AI project intake → tier and laws → department and DPO reviews → the CAICO's decision → register system."""
import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.register.models import HistoryEntry, RegisterSystem
from app.sales.models import Opportunity
from tests.factories import login_as, make_department, make_user


@pytest.fixture
def abc(db, lit):
    from app.reference.models import Jurisdiction
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(db)
    org = lit["abc"]
    hr = make_department(db, org, name="Human Resources")
    cs = make_department(db, org, name="Customer Support")
    p = {
        "org": org, "hr": hr, "cs": cs, "maria": lit["maria"],
        "dana": make_user(db, org, roles=[("dept_compliance_lead", "department", cs.id)], name="Dana Lead", email="dana@abc.test"),
        "cole": make_user(db, org, roles=[("contributor", "department", cs.id)], name="Cole Contributor", email="cole@abc.test"),
        "hal": make_user(db, org, roles=[("dept_compliance_lead", "department", hr.id)], name="Hal Lead", email="hal@abc.test"),
        "priya": make_user(db, org, roles=["dpo"], name="Priya Privacy", email="priya@abc.test"),
        "ian": make_user(db, org, roles=["client_admin"], name="Ian Admin", email="ian@abc.test"),
        "omar": make_user(db, org, roles=["caico"], name="Omar Officer", email="omar@abc.test"),
        "geo": {j.code: j.id for j in db.scalars(select(Jurisdiction).where(Jurisdiction.code.in_(["US-NYC", "US-NY", "US-CA", "US-IL"])))},
    }
    db.commit()
    return p


def chatbot(abc, **kw):
    return {"project_name": "Customer support chatbot", "department_id": abc["cs"].id, "purpose": "Answer customer questions about orders and refunds.",
            "tool_or_vendor": "Zendesk AI agents", "system_type": "genai_chat_tool", "sourcing": "vendor", "planned_go_live": "2027-02-01",
            "jurisdiction_ids": [abc["geo"]["US-NY"], abc["geo"]["US-IL"], abc["geo"]["US-CA"]], "data_categories": ["personal"], "data_subjects": ["customers"],
            "decision_impact": "informs", "public_facing": True} | kw


def screener(abc, **kw):
    return chatbot(abc, project_name="Applicant ranking", department_id=abc["hr"].id, purpose="Ranks applicants before recruiter review.", tool_or_vendor="HireRank",
                   system_type="vendor_app", data_subjects=["candidates"], decision_impact="consequential", public_facing=False,
                   jurisdiction_ids=[abc["geo"]["US-NYC"]]) | kw


def _submit(client, db, abc, body, who="cole"):  # a contributor; the department lead reviews
    login_as(client, db, abc[who])
    r = client.post("/api/v1/projects", json=body)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post(f"/api/v1/projects/{pid}/submit")
    assert r.status_code == 200, r.text
    return r.json()


def _review(client, db, abc, pid, who, step, rec="approve", comment="Reviewed the intake."):
    login_as(client, db, abc[who])
    return client.post(f"/api/v1/projects/{pid}/reviews", json={"step": step, "recommendation": rec, "comment": comment})


def test_live_assessment_shows_tier_depth_and_laws_without_saving(client, db, abc):
    login_as(client, db, abc["dana"])
    r = client.post("/api/v1/projects/assess", json=chatbot(abc))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["tier"] == 2 and d["depth"] == "light" and any(x["matched"] for x in d["laws"])
    assert client.get("/api/v1/projects").json()["rows"] == []


def test_a_department_lead_saves_a_draft_with_its_tier_and_submits_it(client, db, abc):
    login_as(client, db, abc["dana"])
    r = client.post("/api/v1/projects", json=chatbot(abc))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["reference"] == "IA-001" and d["status"] == "draft" and d["proposed_tier"] == 2 and d["matched_regulations"]
    r = client.post(f"/api/v1/projects/{d['id']}/submit")
    assert r.status_code == 200 and r.json()["status"] == "in_review"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "impact.submit")) is not None


def test_required_intake_fields_are_checked_on_submit(client, db, abc):
    login_as(client, db, abc["dana"])
    pid = client.post("/api/v1/projects", json={"project_name": "Half-filled", "department_id": abc["cs"].id}).json()["id"]
    r = client.post(f"/api/v1/projects/{pid}/submit")
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["errors"]}
    assert {"purpose", "tool_or_vendor", "data_categories", "decision_impact"} <= fields


def test_a_department_lead_cannot_file_for_another_department(client, db, abc):
    login_as(client, db, abc["dana"])
    assert client.post("/api/v1/projects", json=screener(abc)).status_code == 403
    p = _submit(client, db, abc, screener(abc), who="hal")
    login_as(client, db, abc["dana"])
    assert client.get(f"/api/v1/projects/{p['id']}").status_code == 404
    assert client.get("/api/v1/projects").json()["rows"] == []


def test_the_caico_decides_only_after_the_department_and_dpo_reviews(client, db, abc):
    p = _submit(client, db, abc, chatbot(abc))
    login_as(client, db, abc["maria"])
    r = client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved", "note": "Fine"})
    assert r.status_code == 409 and "review" in r.json()["detail"].lower()
    assert _review(client, db, abc, p["id"], "priya", "department").status_code == 403  # the DPO is not the department reviewer
    assert _review(client, db, abc, p["id"], "dana", "department").status_code == 200
    assert _review(client, db, abc, p["id"], "priya", "dpo", "approve_with_conditions", "Run a DPIA before go-live.").status_code == 200
    login_as(client, db, abc["maria"])
    r = client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved_with_conditions", "note": "Approved with the DPO's condition.",
                                                                "conditions": [{"text": "Complete a DPIA before go-live", "owner_user_id": abc["priya"].id, "due_on": "2027-01-15"}]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "decided" and d["decision"] == "approved_with_conditions"
    assert [c["text"] for c in d["conditions"]] == ["Complete a DPIA before go-live"] and d["conditions"][0]["status"] == "open"


def test_approval_creates_a_proposed_register_system_with_the_intake(client, db, abc):
    p = _submit(client, db, abc, chatbot(abc))
    _review(client, db, abc, p["id"], "dana", "department")
    _review(client, db, abc, p["id"], "priya", "dpo")
    login_as(client, db, abc["maria"])
    d = client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved", "note": "Approved."}).json()
    s = db.get(RegisterSystem, d["register_system_id"])
    assert s.stage == "proposed" and s.name == "Customer support chatbot" and s.type == "genai_chat_tool" and s.department_id == abc["cs"].id
    assert s.risk_tier == 2 and s.decision_impact == "informs"
    h = db.scalar(select(HistoryEntry).where(HistoryEntry.register_system_id == s.id))
    assert h.type == "impact_assessment" and "IA-001" in h.summary


def test_approval_can_link_an_existing_register_system(client, db, abc, lit):
    p = _submit(client, db, abc, chatbot(abc))
    _review(client, db, abc, p["id"], "dana", "department")
    _review(client, db, abc, p["id"], "priya", "dpo")
    login_as(client, db, abc["maria"])
    d = client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved", "note": "Same tool.", "link_register_system_id": lit["chatbot"].id}).json()
    assert d["register_system_id"] == lit["chatbot"].id
    assert db.scalar(select(RegisterSystem).where(RegisterSystem.name == "Customer support chatbot")) is None


def test_rejection_needs_a_reason_and_creates_no_system(client, db, abc):
    p = _submit(client, db, abc, chatbot(abc))
    _review(client, db, abc, p["id"], "dana", "department", "reject", "No business case.")
    _review(client, db, abc, p["id"], "priya", "dpo", "reject", "Personal data with no lawful basis.")
    login_as(client, db, abc["maria"])
    assert client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "rejected"}).status_code == 422
    d = client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "rejected", "note": "No lawful basis for the data."}).json()
    assert d["decision"] == "rejected" and d["register_system_id"] is None


def test_the_submitter_cannot_decide_their_own_project(client, db, abc):
    p = _submit(client, db, abc, chatbot(abc), who="maria")
    _review(client, db, abc, p["id"], "dana", "department")
    _review(client, db, abc, p["id"], "priya", "dpo")
    login_as(client, db, abc["maria"])
    assert client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved", "note": "ok"}).status_code == 403
    login_as(client, db, abc["omar"])
    assert client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved", "note": "ok"}).status_code == 200


def test_with_no_dpo_the_dpo_review_is_not_required(client, db, abc):
    abc["priya"].status = "disabled"
    db.commit()
    p = _submit(client, db, abc, chatbot(abc))
    _review(client, db, abc, p["id"], "dana", "department")
    login_as(client, db, abc["maria"])
    assert client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved", "note": "ok"}).status_code == 200


def test_conditions_are_met_by_the_owner_and_closed_by_the_caico(client, db, abc):
    p = _submit(client, db, abc, chatbot(abc))
    _review(client, db, abc, p["id"], "dana", "department")
    _review(client, db, abc, p["id"], "priya", "dpo")
    login_as(client, db, abc["maria"])
    d = client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved_with_conditions", "note": "ok",
                                                                "conditions": [{"text": "Publish an AI chat notice", "owner_user_id": abc["dana"].id, "due_on": "2027-01-10"}]}).json()
    cid = d["conditions"][0]["id"]
    login_as(client, db, abc["dana"])
    r = client.post(f"/api/v1/projects/{p['id']}/conditions/{cid}/met", json={"note": "Notice live on the help centre."})
    assert r.status_code == 200 and r.json()["status"] == "met"
    assert client.post(f"/api/v1/projects/{p['id']}/conditions/{cid}/close", json={}).status_code == 403
    login_as(client, db, abc["maria"])
    r = client.post(f"/api/v1/projects/{p['id']}/conditions/{cid}/close", json={})
    assert r.status_code == 200 and r.json()["status"] == "closed"


def test_conditional_approval_needs_at_least_one_condition(client, db, abc):
    p = _submit(client, db, abc, chatbot(abc))
    _review(client, db, abc, p["id"], "dana", "department")
    _review(client, db, abc, p["id"], "priya", "dpo")
    login_as(client, db, abc["maria"])
    assert client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved_with_conditions", "note": "ok", "conditions": []}).status_code == 422


def test_an_independent_opinion_is_for_tier_3_projects_and_opens_an_opportunity(client, db, abc):
    low = _submit(client, db, abc, chatbot(abc))
    login_as(client, db, abc["maria"])
    assert client.post(f"/api/v1/projects/{low['id']}/opinion").status_code == 409
    high = _submit(client, db, abc, screener(abc), who="hal")
    login_as(client, db, abc["maria"])
    r = client.post(f"/api/v1/projects/{high['id']}/opinion")
    assert r.status_code == 200, r.text
    o = db.scalar(select(Opportunity).where(Opportunity.trigger == "impact_assessment"))
    assert o.organization_id == abc["org"].id and o.trigger_ref == high["id"] and o.service_kind == "advisory" and "Applicant ranking" in o.service
    assert client.post(f"/api/v1/projects/{high['id']}/opinion").json()["opinion_opportunity_id"] == o.id  # once


def test_futran_staff_and_contributors_outside_the_department_do_not_see_projects(client, db, abc, lit):
    _submit(client, db, abc, chatbot(abc))
    login_as(client, db, lit["chief"])
    assert client.get("/api/v1/projects").status_code == 404
    login_as(client, db, abc["ian"])  # Client Admin reads the list
    assert len(client.get("/api/v1/projects").json()["rows"]) == 1
