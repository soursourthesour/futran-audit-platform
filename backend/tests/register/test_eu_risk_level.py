"""EU AI Act risk level on register systems (11-25 change): worked out from the screening on the system, logged in the
change history when it moves, and overridden by a classification signed off in the EU AI Act workspace."""
from sqlalchemy import select

from app.euaiact.models import EuAiActRecord
from app.register.models import ChangeLog, RegisterSystem
from app.register import service as svc
from tests.register.conftest import new_system

CHATBOT = {"art5": ["none"], "annex_iii_area": "none", "annex_i": False, "art50": ["interacts"], "gpai": False}
SCREENER = {"art5": ["none"], "annex_iii_area": "employment", "annex_i": False, "art50": ["none"], "gpai": False}


def test_screening_sets_level_and_changes_are_logged(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, eu_screening=CHATBOT)
    assert s["eu_risk_level"] == "limited" and s["eu_risk_label"] == "Limited risk" and s["risk_tier"] == 1
    r = client.patch(f"/api/v1/register/{s['id']}", json={"eu_screening": SCREENER, "reason": "It ranks applicants."})
    assert r.status_code == 200, r.text
    assert r.json()["eu_risk_level"] == "high_risk"
    logs = db.scalars(select(ChangeLog).where(ChangeLog.register_system_id == s["id"], ChangeLog.field == "eu_risk_level")).all()
    assert [(c.old_value, c.new_value) for c in logs] == [("Limited risk", "High-risk")]


def test_unscreened_system_and_list(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id)
    assert s["eu_risk_level"] is None and s["eu_risk_label"] == "Not screened"
    rows = client.get("/api/v1/register").json()
    row = rows["systems"][0] if isinstance(rows, dict) else rows[0]
    assert row["eu_risk_label"] == "Not screened"


def test_signed_off_classification_overrides_the_screening(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, eu_screening=CHATBOT)
    row = db.get(RegisterSystem, s["id"])
    db.add(EuAiActRecord(organization_id=reg.org.id, register_system_id=row.id, role="deployer", classification="high_risk_annex_iii",
                         annex_iii_area="employment", signoff_status="signed_off"))
    db.flush()
    svc.apply_eu_level(db, row)
    assert row.eu_risk_level == "high_risk" and row.eu_risk_reason.startswith("Signed off by the legal reviewer")
    # a record not yet signed off does not count
    rec = db.scalar(select(EuAiActRecord).where(EuAiActRecord.register_system_id == row.id))
    rec.signoff_status = "draft"
    svc.apply_eu_level(db, row)
    assert row.eu_risk_level == "limited"
