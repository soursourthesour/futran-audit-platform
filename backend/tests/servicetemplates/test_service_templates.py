"""G-06 service template library (Release 2 B6): one template per engagement type with versions; the Futran Admin
maintains them and the Chief Auditor approves a version before use. Seeded only with what the spec gives."""
from types import SimpleNamespace

import pytest

from app.servicetemplates import service as svc
from app.servicetemplates.types import NEW_ENGAGEMENT_TYPES
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def w(db, client):
    from app.questionnaire.seed import load_question_bank
    from app.reference.frameworks import load_frameworks

    load_frameworks(db)
    load_question_bank(db)
    f = make_org(db, type="futran")
    ns = SimpleNamespace(client=client, db=db)
    ns.admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    ns.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    ns.both = make_user(db, f, roles=["admin", "chief_auditor"], name="Bo Both", email="bo@futran.test")
    ns.auditor = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    org = make_org(db, name="ABC Corp")
    ns.caico = make_user(db, org, roles=["caico"], name="Maria", email="maria@abc.test")
    svc.seed(db)
    db.commit()
    ns.as_ = lambda u: login_as(client, db, u)
    return ns


def _row(page, t):
    return next(r for r in page["types"] if r["engagement_type"] == t)


def test_every_engagement_type_is_listed_with_its_template_and_the_original_types_are_in_use(w):
    w.as_(w.admin)
    r = w.client.get("/api/v1/service-templates")
    assert r.status_code == 200, r.text
    page = r.json()
    assert {x["engagement_type"] for x in page["types"]} >= set(NEW_ENGAGEMENT_TYPES) | {"initial_assessment", "ll144_bias_audit"}
    assert _row(page, "initial_assessment")["status_label"] == "In use (v0.6.1)"
    cop = _row(page, "copilot_readiness")
    assert cop["template"]["content_owner"] == "Microsoft practice" and cop["latest"]["status"] == "draft" and cop["latest"]["catalog_codes"] == ["X-04"]
    assert _row(page, "vendor_sponsored_audit")["latest"] is None and _row(page, "vendor_sponsored_audit")["status_label"] == "Not started"
    assert page["can_manage"] and not page["can_approve"]
    w.as_(w.auditor)
    assert w.client.get("/api/v1/service-templates").status_code == 403
    w.as_(w.caico)
    assert w.client.get("/api/v1/service-templates").status_code in (403, 404)


def test_seeded_content_is_what_the_spec_gives(w):
    copilot = svc.latest_version(w.db, "copilot_readiness")
    assert [c["text"] for c in copilot.checklists] == ["Oversharing report", "Sensitivity labels", "DLP for Copilot", "Restricted content discovery", "Audit logging",
                                                       "Usage policy", "User training"]
    eu = svc.latest_version(w.db, "eu_ai_act_readiness")
    codes = [c["code"] for c in eu.checklists]
    assert codes[:5] == ["Art. 4", "Art. 14", "Art. 26", "Art. 27", "Art. 50"]
    assert {"Art. 9", "Art. 15", "Art. 17", "Art. 43", "Art. 72", "Art. 73"} <= set(codes)
    assert {d["date"] for d in eu.key_dates} == {"2027-12-02", "2028-08-02"} and "2026/1744" in eu.key_dates[0]["source"]
    iso = svc.latest_version(w.db, "iso42001_readiness")
    assert [c["code"] for c in iso.checklists][:7] == ["4", "5", "6", "7", "8", "9", "10"] and any(c["code"] == "A.10.4" for c in iso.checklists)
    assert all(c.get("evidence") for c in iso.checklists)
    vdd = svc.latest_version(w.db, "vendor_due_diligence")
    assert vdd.question_codes == [f"9.2.0{i}" for i in range(1, 9)]
    assert [q["code"] for q in svc.questions(w.db, vdd)] == vdd.question_codes  # resolved through the question bank engine
    ll = svc.latest_version(w.db, "ll144_applicability")
    assert ll.sections[0]["title"].startswith("8-case staffing applicability map") and any("10 business days" in c["text"] for c in ll.checklists)
    ma = svc.latest_version(w.db, "ma_due_diligence")
    assert [s["title"] for s in ma.sections] == ["Target AI inventory", "Regulatory exposure", "Open litigation", "Red-flag summary"]
    svc.seed(w.db)  # idempotent
    assert len(svc.versions(w.db, svc.template_for(w.db, "copilot_readiness"))) == 1


def test_the_admin_edits_and_submits_and_the_chief_auditor_approves_before_use(w):
    v = svc.latest_version(w.db, "copilot_readiness")
    w.as_(w.admin)
    r = w.client.put(f"/api/v1/service-template-versions/{v.id}", json={"deliverables": ["Readiness report", "Copilot entry in the AI register"], "default_stages": ["Licences and usage", "Site risk", "Rollout waves"]})
    assert r.status_code == 200, r.text
    assert svc.approved_version(w.db, "copilot_readiness") is None
    assert w.client.post(f"/api/v1/service-template-versions/{v.id}/approve", json={}).status_code == 403
    assert w.client.post(f"/api/v1/service-template-versions/{v.id}/submit").status_code == 200
    w.as_(w.chief)
    r = w.client.post(f"/api/v1/service-template-versions/{v.id}/approve", json={"note": "Checked against the Microsoft blueprint."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["approved_by"] == "Cara Chief"
    w.db.expire_all()
    assert svc.approved_version(w.db, "copilot_readiness").id == v.id
    assert [c["text"] for c in svc.checklist_for(w.db, "copilot_readiness")][0] == "Oversharing report"
    w.as_(w.admin)
    assert w.client.put(f"/api/v1/service-template-versions/{v.id}", json={"deliverables": []}).status_code == 409  # approved versions do not change
    r = w.client.post(f"/api/v1/service-templates/{v.template_id}/versions")
    assert r.status_code == 200 and r.json()["version"] == "0.2" and r.json()["status"] == "draft"


def test_nobody_approves_a_version_they_wrote_or_submitted(w):
    v = svc.latest_version(w.db, "ma_due_diligence")
    w.as_(w.both)
    w.client.put(f"/api/v1/service-template-versions/{v.id}", json={"deliverables": ["Red-flag memo"]})
    w.client.post(f"/api/v1/service-template-versions/{v.id}/submit")
    r = w.client.post(f"/api/v1/service-template-versions/{v.id}/approve", json={})
    assert r.status_code in (403, 409)


def test_the_chief_auditor_can_return_a_version_with_a_reason(w):
    v = svc.latest_version(w.db, "iso42001_readiness")
    w.as_(w.admin)
    w.client.post(f"/api/v1/service-template-versions/{v.id}/submit")
    w.as_(w.chief)
    assert w.client.post(f"/api/v1/service-template-versions/{v.id}/return", json={"note": ""}).status_code == 422
    r = w.client.post(f"/api/v1/service-template-versions/{v.id}/return", json={"note": "Add the evidence each Annex A control needs."})
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["returned_note"].startswith("Add the evidence")


def test_a_template_can_be_started_for_a_type_without_one(w):
    w.as_(w.admin)
    t = _row(w.client.get("/api/v1/service-templates").json(), "vendor_sponsored_audit")["template"]
    r = w.client.post(f"/api/v1/service-templates/{t['id']}/versions")
    assert r.status_code == 200 and r.json()["version"] == "0.1"
