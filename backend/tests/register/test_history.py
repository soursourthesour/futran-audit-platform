from sqlalchemy import select

from app.notifications.models import Notification
from app.register.models import BiasTest, ChangeLog, HistoryEntry, NoIncidentStatement
from tests.register.conftest import new_system


def _sys(client, reg, **kw):
    reg.as_(reg.hr_lead)
    return new_system(client, department_id=reg.hr.id, owner_user_id=reg.hr_user.id, decision_impact="consequential", **kw)


def test_add_incident_entry_with_type_fields(client, db, reg):
    s = _sys(client, reg)
    r = client.post(f"/api/v1/register/{s['id']}/history", json={
        "type": "incident", "occurred_on": "2025-06-02", "summary": "Recruiter reported candidates with career gaps ranked lower", "severity": "medium",
        "details": {"people_affected": 40, "cause": "Gap penalty in ranking", "containment": "Vendor removed the feature", "closed_on": "2025-06-20", "reportable": False, "provider_told": True}})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["type_label"] == "Incident" and e["severity"] == "medium" and e["details"]["people_affected"] == 40 and e["recorded_by"] == "Priya Shah"
    hist = client.get(f"/api/v1/register/{s['id']}/history").json()
    assert [x["summary"] for x in hist["entries"]] == ["Recruiter reported candidates with career gaps ranked lower"]


def test_entry_validation(client, db, reg):
    s = _sys(client, reg)
    r = client.post(f"/api/v1/register/{s['id']}/history", json={"type": "incident", "occurred_on": "", "summary": ""})
    fields = {e["field"] for e in r.json()["errors"]}
    assert r.status_code == 422 and {"occurred_on", "summary", "severity"} <= fields
    r = client.post(f"/api/v1/register/{s['id']}/history", json={"type": "gossip", "occurred_on": "2025-01-01", "summary": "x"})
    assert r.status_code == 422
    r = client.post(f"/api/v1/register/{s['id']}/history", json={"type": "incident", "occurred_on": "2025-01-01", "summary": "x", "severity": "medium", "details": {"reportable": True}})
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} >= {"details.law", "details.deadline"}


def test_bias_test_entry_creates_bias_test_and_flags_null_compliance(client, db, reg):
    s = _sys(client, reg)
    r = client.post(f"/api/v1/register/{s['id']}/bias-tests", json={"tested_on": "2025-09-14", "tester_type": "independent", "tester_name": "Audit firm",
                                                                   "method": "Impact ratio by sex and race/ethnicity", "groups_tested": "Sex, race/ethnicity", "result": "flagged",
                                                                   "result_text": "One group at 0.76", "unknown_share": 62})
    assert r.status_code == 200, r.text
    bt = db.scalar(select(BiasTest).where(BiasTest.register_system_id == s["id"]))
    assert bt.next_due.isoformat() == "2026-09-14" and bt.history_entry_id
    he = db.get(HistoryEntry, bt.history_entry_id)
    assert he.type == "bias_test" and he.details["unknown_share"] == 62
    got = client.get(f"/api/v1/register/{s['id']}").json()["bias"]
    assert got["last_tested_on"] == "2025-09-14" and got["null_compliance"] is True


def test_bias_test_through_history_endpoint_is_the_same_record(client, db, reg):
    s = _sys(client, reg)
    r = client.post(f"/api/v1/register/{s['id']}/history", json={"type": "bias_test", "occurred_on": "2026-01-10", "summary": "Internal check", "details": {"tester_type": "internal", "result": "passed"}})
    assert r.status_code == 200, r.text
    assert db.scalar(select(BiasTest).where(BiasTest.register_system_id == s["id"])).result == "passed"


def test_edit_and_delete_entry_are_logged(client, db, reg):
    s = _sys(client, reg)
    e = client.post(f"/api/v1/register/{s['id']}/history", json={"type": "approval", "occurred_on": "2024-03-01", "summary": "HR Director approved go-live", "details": {"approver": "HR Director", "scope": "Go-live"}}).json()
    r = client.patch(f"/api/v1/register/{s['id']}/history/{e['id']}", json={"summary": "HR Director approved go-live for NYC roles", "reason": "Wording"})
    assert r.status_code == 200 and r.json()["summary"].endswith("NYC roles")
    assert client.request("DELETE", f"/api/v1/register/{s['id']}/history/{e['id']}", json={"reason": "Entered twice"}).status_code == 200
    assert client.get(f"/api/v1/register/{s['id']}/history").json()["entries"] == []
    fields = [c.field for c in db.scalars(select(ChangeLog).where(ChangeLog.register_system_id == s["id"], ChangeLog.entity == "HistoryEntry"))]
    assert "history" in fields


def test_client_admin_cannot_record_history(client, db, reg):
    s = _sys(client, reg)
    reg.as_(reg.admin)
    assert client.get(f"/api/v1/register/{s['id']}/history").status_code == 200
    r = client.post(f"/api/v1/register/{s['id']}/history", json={"type": "training", "occurred_on": "2025-01-01", "summary": "x"})
    assert r.status_code == 403


def test_first_entry_no_incidents_by_non_owner_waits_for_owner(client, db, reg):
    s = _sys(client, reg, stage="in_development")
    r = client.post(f"/api/v1/register/{s['id']}/history-answers", json={"incidents": "no", "bias_tests": "no", "deployment_tests": "yes", "approvals": "no", "notices": "no"})
    assert r.status_code == 200, r.text
    h = client.get(f"/api/v1/register/{s['id']}/history").json()
    assert h["answers"]["incidents"] == "no" and h["statement"]["signed_at"] is None and h["statement"]["owner"] == "Hana Ito"
    assert db.scalar(select(Notification).where(Notification.user_id == reg.hr_user.id, Notification.kind == "register_no_incident_statement")) is not None
    # only the owner can sign
    assert client.post(f"/api/v1/register/{s['id']}/no-incident/sign", json={"typed_name": "Priya Shah"}).status_code == 403
    reg.as_(reg.hr_user)
    r = client.post(f"/api/v1/register/{s['id']}/no-incident/sign", json={"typed_name": "Hana Ito"})
    assert r.status_code == 200, r.text
    st = db.scalar(select(NoIncidentStatement).where(NoIncidentStatement.register_system_id == s["id"]))
    assert st.signed_by == reg.hr_user.id and st.signed_by_name == "Hana Ito" and st.signed_at is not None


def test_first_entry_owner_signs_at_once(client, db, reg):
    s = _sys(client, reg)
    reg.as_(reg.hr_user)
    reg.as_(reg.caico)
    db_s = client.patch(f"/api/v1/register/{s['id']}", json={"owner_user_id": reg.caico.id}).json()
    r = client.post(f"/api/v1/register/{db_s['id']}/history-answers", json={"incidents": "no", "sign_as": "Maria Lopez"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/register/{s['id']}/history").json()["statement"]["signed_by"] == "Maria Lopez"


def test_first_entry_answers_validated(client, db, reg):
    s = _sys(client, reg)
    r = client.post(f"/api/v1/register/{s['id']}/history-answers", json={"incidents": "maybe"})
    assert r.status_code == 422


def test_answers_given_on_create(client, db, reg):
    reg.as_(reg.hr_lead)
    s = new_system(client, department_id=reg.hr.id, owner_user_id=reg.hr_user.id, history_answers={"incidents": "yes", "bias_tests": "no"})
    h = client.get(f"/api/v1/register/{s['id']}/history").json()
    assert h["answers"] == {"incidents": "yes", "bias_tests": "no"} and h["statement"] is None


def test_bulk_link_requirement_and_delete(client, db, reg):
    s = _sys(client, reg)
    ids = [client.post(f"/api/v1/register/{s['id']}/history", json={"type": "training", "occurred_on": f"2025-0{i}-01", "summary": f"Session {i}"}).json()["id"] for i in (1, 2)]
    r = client.post(f"/api/v1/register/{s['id']}/history/bulk", json={"entry_ids": ids, "action": "delete", "reason": "Wrong system"})
    assert r.status_code == 200
    assert client.get(f"/api/v1/register/{s['id']}/history").json()["entries"] == []


def test_tracing_recommended_rule(client, db, reg):
    reg.as_(reg.hr_lead)
    plain = new_system(client, department_id=reg.hr.id)
    assert client.get(f"/api/v1/register/{plain['id']}/history").json()["tracing"] == {"locked": True, "state": "locked", "recommended": False, "reasons": []}
    t3 = new_system(client, name="Ranker", department_id=reg.hr.id, decision_impact="consequential")
    assert client.get(f"/api/v1/register/{t3['id']}/history").json()["tracing"]["reasons"] == ["Tier 3"]
    agent = new_system(client, name="Agent", type="agent", department_id=reg.hr.id, actions=[{"action_code": "send_email"}])
    assert client.get(f"/api/v1/register/{agent['id']}/history").json()["tracing"]["reasons"] == ["an AI agent that takes actions"]
    client.post(f"/api/v1/register/{plain['id']}/history", json={"type": "incident", "occurred_on": "2025-01-01", "summary": "Wrong answer", "severity": "low"})
    tr = client.get(f"/api/v1/register/{plain['id']}/history").json()["tracing"]
    assert tr["recommended"] is True and tr["reasons"] == ["1 past incident"]
