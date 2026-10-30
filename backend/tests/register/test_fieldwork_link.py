"""The audit fieldwork side: an engagement's system can be taken from the client's register, and auditors read its bias
tests and history (read-only)."""
from sqlalchemy import select

from app.register.models import RegisterSystem
from app.systems.models import AISystem, SystemAdditionRequest
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401


def _register_system(client, db, maria, hr):
    login_as(client, db, maria)
    r = client.post("/api/v1/register", json={"name": "TalentRank", "type": "vendor_app", "sourcing": "vendor", "vendor_name": "TalentRank Inc.", "department_id": hr.id,
                                              "owner_user_id": maria.id, "stage": "in_development", "decision_impact": "consequential"})
    assert r.status_code == 200, r.text
    s = r.json()
    client.post(f"/api/v1/register/{s['id']}/bias-tests", json={"tested_on": "2025-09-14", "tester_type": "independent", "tester_name": "Audit firm", "result": "passed", "unknown_share": 12})
    client.post(f"/api/v1/register/{s['id']}/history", json={"type": "incident", "occurred_on": "2025-06-02", "summary": "Career gaps ranked lower", "severity": "medium"})
    return s


def test_auditor_adds_system_from_register_and_facts_are_copied(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    s = _register_system(client, db, maria, hr)
    login_as(client, db, people["aud"])
    reg = client.get(f"/api/v1/clients/{cid}/systems").json()
    opt = next(o for o in reg["register_options"] if o["id"] == s["id"])
    assert opt["name"] == "TalentRank" and opt["built_by"] == "vendor" and opt["vendor_id"] and opt["department_id"] == hr.id and opt["linked_to"] is None
    r = client.post(f"/api/v1/clients/{cid}/systems", json={"register_system_id": s["id"], "name": "", "built_by": "vendor", "reason": "In the client's register"})
    assert r.status_code == 200, r.text
    login_as(client, db, people["em"])
    req = db.scalar(select(SystemAdditionRequest).where(SystemAdditionRequest.status == "pending"))
    assert client.post(f"/api/v1/system-requests/{req.id}/decide", json={"approve": True}).status_code == 200
    db.expire_all()
    a = db.scalar(select(AISystem).where(AISystem.register_system_id == s["id"]))
    assert a is not None and a.name == "TalentRank" and a.vendor_id == opt["vendor_id"] and a.department_id == hr.id and a.owner_user_id == maria.id
    login_as(client, db, people["aud"])
    reg = client.get(f"/api/v1/clients/{cid}/systems").json()
    row = next(x for x in reg["systems"] if x["id"] == a.id)
    assert row["register_system"]["reference"] == "AIS-001"
    assert next(o for o in reg["register_options"] if o["id"] == s["id"])["linked_to"] == row["reference_id"]


def test_register_system_must_be_the_clients(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    other = RegisterSystem(organization_id="someone-else", reference="AIS-001", name="X", type="vendor_app", sourcing="vendor", stage="proposed")
    db.add(other)
    db.commit()
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/clients/{cid}/systems", json={"register_system_id": other.id, "name": "X", "built_by": "vendor", "reason": "x"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "register_system_id"


def test_auditor_reads_bias_tests_and_history_read_only(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    s = _register_system(client, db, maria, hr)
    sys0 = db.scalars(select(AISystem).where(AISystem.engagement_id == e.id)).first()
    sys0.register_system_id = s["id"]
    db.commit()
    login_as(client, db, people["aud"])
    r = client.get(f"/api/v1/systems/{sys0.id}/register-record")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["system"]["reference"] == "AIS-001" and body["system"]["stage_label"] == "In development / procurement"
    assert [b["tested_on"] for b in body["bias_tests"]] == ["2025-09-14"] and body["bias_tests"][0]["unknown_share"] == 12
    assert {h["type"] for h in body["history"]} == {"bias_test", "incident"}
    login_as(client, db, people["aud2"])  # not on the team
    assert client.get(f"/api/v1/systems/{sys0.id}/register-record").status_code == 404
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/register/{s['id']}/history", json={"type": "training", "occurred_on": "2025-01-01", "summary": "x"}).status_code == 404


def test_register_record_empty_when_not_linked(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    sys0 = db.scalars(select(AISystem).where(AISystem.engagement_id == e.id)).first()
    login_as(client, db, people["aud"])
    assert client.get(f"/api/v1/systems/{sys0.id}/register-record").json() == {"system": None, "bias_tests": [], "history": [], "statement": None}
