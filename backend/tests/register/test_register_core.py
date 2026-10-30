from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.register.models import ChangeLog, RegisterSystem
from tests.factories import make_org, make_user
from tests.register.conftest import new_system


def test_dept_lead_adds_system_in_own_department(client, db, reg):
    reg.as_(reg.hr_lead)
    s = new_system(client, department_id=reg.hr.id, owner_user_id=reg.hr_user.id)
    assert s["reference"] == "AIS-001" and s["department"]["name"] == "Human Resources" and s["stage"] == "proposed"
    assert s["owner"]["name"] == "Hana Ito"
    row = db.get(RegisterSystem, s["id"])
    assert row.organization_id == reg.org.id and row.origin == "manual"
    assert db.scalar(select(AuditLog).where(AuditLog.object_id == s["id"], AuditLog.action == "register.create")) is not None


def test_dept_lead_cannot_add_to_other_department(client, db, reg):
    reg.as_(reg.hr_lead)
    r = client.post("/api/v1/register", json={"name": "Invoice OCR", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.fin.id})
    assert r.status_code == 403


def test_validation_messages(client, db, reg):
    reg.as_(reg.caico)
    r = client.post("/api/v1/register", json={"name": "", "type": "robot", "sourcing": "x", "stage": "live"})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["errors"]}
    assert {"name", "type", "sourcing"} <= fields


def test_live_cannot_be_set_directly(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id)
    r = client.patch(f"/api/v1/register/{s['id']}", json={"stage": "live"})
    assert r.status_code == 409 and "approval" in r.json()["detail"]
    r = client.post("/api/v1/register", json={"name": "X", "type": "vendor_app", "sourcing": "vendor", "stage": "live", "department_id": reg.hr.id})
    assert r.status_code == 409


def test_list_scoped_to_department_and_company_wide(client, db, reg):
    reg.as_(reg.caico)
    a = new_system(client, name="Résumé screening", department_id=reg.hr.id)
    b = new_system(client, name="Invoice OCR", department_id=reg.fin.id)
    c = new_system(client, name="Microsoft 365 Copilot", type="embedded_feature", company_wide=True)
    reg.as_(reg.hr_lead)
    rows = client.get("/api/v1/register").json()["systems"]
    names = {r["name"]: r for r in rows}
    assert set(names) == {"Résumé screening", "Microsoft 365 Copilot"}
    assert names["Microsoft 365 Copilot"]["can_edit"] is False and names["Résumé screening"]["can_edit"] is True
    assert client.get(f"/api/v1/register/{b['id']}").status_code == 404
    assert client.patch(f"/api/v1/register/{c['id']}", json={"purpose": "x"}).status_code == 403
    reg.as_(reg.admin)
    assert len(client.get("/api/v1/register").json()["systems"]) == 3
    reg.as_(reg.contrib)
    assert client.get("/api/v1/register").status_code == 403
    _ = a


def test_other_tenant_sees_nothing(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id)
    other = make_org(db, name="Other Co")
    o = make_user(db, other, roles=["caico"], name="Olga", email="olga@other.test")
    db.commit()
    reg.as_(o)
    assert client.get("/api/v1/register").json()["systems"] == []
    assert client.get(f"/api/v1/register/{s['id']}").status_code == 404
    assert client.patch(f"/api/v1/register/{s['id']}", json={"purpose": "x"}).status_code == 404


def test_edit_writes_field_level_change_log(client, db, reg):
    reg.as_(reg.hr_lead)
    s = new_system(client, department_id=reg.hr.id)
    r = client.patch(f"/api/v1/register/{s['id']}", json={"purpose": "Shortlists applicants.", "model_name": "RankNet", "reason": "Vendor confirmed the model."})
    assert r.status_code == 200, r.text
    logs = db.scalars(select(ChangeLog).where(ChangeLog.register_system_id == s["id"], ChangeLog.field != "created")).all()
    got = {(c.field, c.old_value, c.new_value, c.reason) for c in logs}
    assert ("purpose", "Ranks applicants for recruiters.", "Shortlists applicants.", "Vendor confirmed the model.") in got
    assert ("model_name", None, "RankNet", "Vendor confirmed the model.") in got
    hist = client.get(f"/api/v1/register/{s['id']}/changes").json()
    assert hist[0]["user"] == "Priya Shah" and {h["field_label"] for h in hist} >= {"Purpose", "Model name"}


def test_data_and_consent_and_tier(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, decision_impact="informs", data={"data_categories": ["personal"], "data_subjects": ["candidates"], "consent_basis": "consent", "retention_period": "4 years"})
    assert s["risk_tier"] == 2 and "personal" in s["risk_tier_reason"].lower()
    assert s["data"]["consent_basis"] == "consent"
    s = client.patch(f"/api/v1/register/{s['id']}", json={"decision_impact": "consequential"}).json()
    assert s["risk_tier"] == 3
    s = client.patch(f"/api/v1/register/{s['id']}", json={"decision_impact": "none", "data": {"data_categories": [], "data_subjects": ["none"], "consent_basis": "na"}}).json()
    assert s["risk_tier"] == 1


def test_agent_actions_only_for_agents(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, name="Scheduling agent", type="agent", department_id=reg.hr.id, autonomy="acts_with_approval", actions=[{"action_code": "send_email"}, {"action_code": "other", "description": "Book rooms"}])
    assert [a["action_code"] for a in s["actions"]] == ["send_email", "other"] and s["autonomy"] == "acts_with_approval"
    r = client.post("/api/v1/register", json={"name": "Chat", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.hr.id, "autonomy": "autonomous"})
    assert r.status_code == 422


def test_retire_needs_reason(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id)
    assert client.post(f"/api/v1/register/{s['id']}/retire", json={"reason": ""}).status_code == 422
    r = client.post(f"/api/v1/register/{s['id']}/retire", json={"reason": "Replaced by the new ATS."})
    assert r.status_code == 200 and r.json()["stage"] == "retired"


def test_duplicate_copies_facts_not_history(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, model_name="RankNet", data={"data_categories": ["personal"], "consent_basis": "notice_only"})
    r = client.post(f"/api/v1/register/{s['id']}/duplicate")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Résumé screening (copy)" and d["reference"] == "AIS-002" and d["model_name"] == "RankNet" and d["stage"] == "proposed"
    assert d["data"]["consent_basis"] == "notice_only"


def test_kpis(client, db, reg):
    reg.as_(reg.caico)
    new_system(client, name="A", type="agent", department_id=reg.hr.id, data={"data_categories": ["personal"], "consent_basis": "not_obtained"})
    new_system(client, name="B", department_id=reg.hr.id)
    k = client.get("/api/v1/register").json()["kpis"]
    assert k["systems"] == 2 and k["agents"] == 1 and k["consent_missing"] == 1


def test_client_admin_edits_but_cannot_change_laws(client, db, reg, matrix):
    from app.laws.models import Regulation

    law = db.scalars(select(Regulation).where(Regulation.superseded_by_id.is_(None))).first()
    reg.as_(reg.admin)
    s = new_system(client, department_id=reg.hr.id)
    assert client.post(f"/api/v1/register/{s['id']}/laws", json={"regulation_id": law.id}).status_code == 403


def test_reference_numbers_never_reused(client, db, reg):
    reg.as_(reg.caico)
    a = new_system(client, department_id=reg.hr.id)
    db.get(RegisterSystem, a["id"]).deleted_at = db.get(RegisterSystem, a["id"]).created_at
    db.commit()
    assert new_system(client, department_id=reg.hr.id)["reference"] == "AIS-002"


def test_owner_must_be_client_user(client, db, reg):
    reg.as_(reg.caico)
    other = make_org(db, name="Other Co")
    o = make_user(db, other, roles=[], name="Olga", email="olga@other.test")
    db.commit()
    r = client.post("/api/v1/register", json={"name": "X", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.hr.id, "owner_user_id": o.id})
    assert r.status_code == 422
