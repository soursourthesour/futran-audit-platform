"""Governance roles on register systems, the requirements checklist and the go-live gate (spec §24.1–§24.3, §27.2)."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.laws.models import Regulation
from app.regmaster.models import LawRoleMap, LawVersion, Requirement, RoleCatalog
from app.register.models import GovernanceRoleAssignment, RegisterSystem
from tests.register.conftest import new_system

ROLES = [  # code, number, name, level, default stage, extra checks
    ("accountable_executive", 1, "Accountable executive", "company", "development", None),
    ("records_retention_owner", 9, "Records retention owner", "company", "go_live", None),
    ("ai_system_owner", 10, "AI System Owner", "system", "development", None),
    ("human_oversight_person", 12, "Human oversight person", "system", "go_live", "oversight_confirmations"),
    ("stop_disengage_authority", 13, "Stop / disengage authority", "agent", "go_live", None),
    ("bias_testing_lead", 17, "Bias testing lead / independent auditor", "system", "go_live", None),
    ("worker_representative_contact", 21, "Worker representative contact", "system", "go_live", None),
    ("technical_owner", 11, "Technical owner", "system", "go_live", None),
]


@pytest.fixture
def cat(db, matrix):
    regs = list(db.scalars(select(Regulation).where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None)).order_by(Regulation.short_name)))
    law_a, law_b = regs[0], regs[1]
    roles = {}
    for code, n, name, level, stage, extra in ROLES:
        r = RoleCatalog(code=code, number=n, name=name, level=level, default_stage=stage, main_sources="NIST AI RMF", extra_checks=extra, description=f"{name} duties")
        db.add(r)
        roles[code] = r
    db.flush()
    va = LawVersion(regulation_id=law_a.id, version_no=1, status="in_force")
    vb = LawVersion(regulation_id=law_b.id, version_no=1, status="in_force")
    db.add_all([va, vb])
    db.flush()
    law_a.current_version_id, law_b.current_version_id = va.id, vb.id
    req_a1 = Requirement(law_version_id=va.id, code="A-01", order=1, text="Bias audit within the past 12 months", needed_by_stage="go_live", citation="§ 20-871")
    req_a2 = Requirement(law_version_id=va.id, code="A-02", order=2, text="Keep records for three years", needed_by_stage="ongoing")
    req_dev = Requirement(law_version_id=va.id, code="A-03", order=3, text="Developer documentation", needed_by_stage="development", applies_to=["developer"])
    db.add_all([req_a1, req_a2, req_dev])
    db.add_all([
        LawRoleMap(law_version_id=va.id, role_id=roles["bias_testing_lead"].id, level="required", needed_by_stage="go_live", basis_text="Annual bias audit"),
        LawRoleMap(law_version_id=va.id, role_id=roles["human_oversight_person"].id, level="recommended", needed_by_stage="ongoing"),
        LawRoleMap(law_version_id=va.id, role_id=roles["records_retention_owner"].id, level="required", needed_by_stage="go_live"),
        LawRoleMap(law_version_id=vb.id, role_id=roles["human_oversight_person"].id, level="required", needed_by_stage="go_live", basis_text="Art. 14, 26(2)"),
        LawRoleMap(law_version_id=vb.id, role_id=roles["stop_disengage_authority"].id, level="required", needed_by_stage="go_live"),
        LawRoleMap(law_version_id=vb.id, role_id=roles["ai_system_owner"].id, level="required", needed_by_stage="development"),
        LawRoleMap(law_version_id=vb.id, role_id=roles["technical_owner"].id, level="required", needed_by_stage="go_live", applies_to=["developer"]),
        LawRoleMap(law_version_id=vb.id, role_id=roles["worker_representative_contact"].id, level="recommended", needed_by_stage="go_live"),
    ])
    db.commit()
    return SimpleNamespace(a=law_a, b=law_b, va=va, vb=vb, roles=roles, req_a1=req_a1, req_a2=req_a2, req_dev=req_dev)


def _rows(client, sid):
    r = client.get(f"/api/v1/register/{sid}/roles")
    assert r.status_code == 200, r.text
    return {x["code"]: x for x in r.json()["rows"]}


def _system(client, reg, cat, laws=("a",), **kw):
    reg.as_(reg.hr_lead)
    s = new_system(client, department_id=reg.hr.id, stage="in_development", **kw)
    for l in laws:
        assert client.post(f"/api/v1/register/{s['id']}/laws", json={"regulation_id": getattr(cat, l).id}).status_code == 200
    return s


def test_required_roles_follow_the_laws(client, db, reg, cat):
    s = _system(client, reg, cat)
    rows = _rows(client, s["id"])
    assert "stop_disengage_authority" not in rows  # agents only
    assert rows["bias_testing_lead"]["requirement"] == "required" and rows["bias_testing_lead"]["needed_by"] == "go_live"
    assert rows["human_oversight_person"]["requirement"] == "recommended"
    assert rows["accountable_executive"]["requirement"] == "recommended" and rows["accountable_executive"]["required_by"] == ["NIST AI RMF"]
    assert rows["records_retention_owner"]["level"] == "company"
    # adding a law recalculates at once; the stricter level and earlier stage win, and both sources show
    client.post(f"/api/v1/register/{s['id']}/laws", json={"regulation_id": cat.b.id})
    rows = _rows(client, s["id"])
    hop = rows["human_oversight_person"]
    assert hop["requirement"] == "required" and hop["needed_by"] == "go_live" and set(hop["required_by"]) >= {cat.a.short_name, cat.b.short_name}
    assert rows["ai_system_owner"]["requirement"] == "required"
    # a bought system: developer-only duties sit with the vendor
    assert rows["technical_owner"]["requirement"] == "recommended"
    summary = client.get(f"/api/v1/register/{s['id']}").json()["roles"]
    assert summary["required"] == 4 and summary["filled"] == 0


def test_in_house_system_takes_developer_duties(client, db, reg, cat):
    s = _system(client, reg, cat, laws=("b",), sourcing="in_house")
    assert _rows(client, s["id"])["technical_owner"]["requirement"] == "required"


def test_assign_statuses_and_validation(client, db, reg, cat):
    s = _system(client, reg, cat, laws=("a", "b"))
    rid = cat.roles["human_oversight_person"].id
    url = f"/api/v1/register/{s['id']}/roles/{rid}"
    assert client.put(url, json={"status": "assigned"}).json()["errors"][0]["field"] == "user_id"
    assert client.put(url, json={"status": "external"}).json()["errors"][0]["field"] == "external_party"
    assert client.put(url, json={"status": "pending_committee"}).json()["errors"][0]["field"] == "target_date"
    r = client.put(url, json={"status": "assigned", "user_id": reg.hr_user.id, "backup_user_id": reg.hr_lead.id, "effective_from": "2026-11-02",
                              "training_completed": True, "has_authority_to_override": True, "notes": "Reviews flagged answers weekly."})
    assert r.status_code == 200, r.text
    row = _rows(client, s["id"])["human_oversight_person"]
    assert row["status"] == "assigned" and row["filled"] and row["assignment"]["user"]["name"] == "Hana Ito" and row["assignment"]["training_completed"] is True
    a = db.scalar(select(GovernanceRoleAssignment).where(GovernanceRoleAssignment.register_system_id == s["id"], GovernanceRoleAssignment.role_id == rid))
    assert a.backup_user_id == reg.hr_lead.id
    changes = client.get(f"/api/v1/register/{s['id']}/changes").json()
    assert any(c["field"] == "role:human_oversight_person" and c["new_value"].startswith("Assigned: Hana Ito") for c in changes)


def test_not_applicable_rules(client, db, reg, cat):
    s = _system(client, reg, cat, laws=("a", "b"))
    req = f"/api/v1/register/{s['id']}/roles/{cat.roles['human_oversight_person'].id}"
    rec = f"/api/v1/register/{s['id']}/roles/{cat.roles['worker_representative_contact'].id}"
    assert client.put(req, json={"status": "not_applicable", "reason": "No decisions"}).status_code == 403
    assert client.put(rec, json={"status": "not_applicable"}).status_code == 422
    assert client.put(rec, json={"status": "not_applicable", "reason": "Not a high-risk system"}).status_code == 200
    reg.as_(reg.caico)
    assert client.put(req, json={"status": "not_applicable", "reason": "Makes no decisions about people"}).status_code == 200
    reg.as_(reg.admin)
    assert client.put(rec, json={"status": "no_such_person"}).status_code == 403


def test_company_roles_inherited_and_overridden(client, db, reg, cat):
    s = _system(client, reg, cat)
    rid = cat.roles["records_retention_owner"].id
    assert client.put(f"/api/v1/governance/company-roles/{rid}", json={"status": "assigned", "user_id": reg.hr_user.id}).status_code == 403
    assert client.put(f"/api/v1/register/{s['id']}/roles/{rid}", json={"status": "assigned", "user_id": reg.hr_user.id}).status_code == 403
    reg.as_(reg.caico)
    r = client.put(f"/api/v1/governance/company-roles/{rid}", json={"status": "assigned", "user_id": reg.caico.id})
    assert r.status_code == 200, r.text
    row = _rows(client, s["id"])["records_retention_owner"]
    assert row["inherited"] is True and row["assignment"]["user"]["name"] == "Maria Lopez" and row["filled"]
    assert client.put(f"/api/v1/register/{s['id']}/roles/{rid}", json={"status": "assigned", "user_id": reg.hr_user.id, "override": True}).status_code == 422
    r = client.put(f"/api/v1/register/{s['id']}/roles/{rid}", json={"status": "assigned", "user_id": reg.hr_user.id, "override": True, "override_reason": "HR keeps its own records"})
    assert r.status_code == 200
    row = _rows(client, s["id"])["records_retention_owner"]
    assert row["inherited"] is False and row["assignment"]["override"] is True and row["assignment"]["user"]["name"] == "Hana Ito"
    page = client.get("/api/v1/governance/company-roles").json()
    rr = next(x for x in page["rows"] if x["code"] == "records_retention_owner")
    assert rr["applies_to"] == 1 and rr["overrides"] == 1


def test_go_live_gate_enforced_in_api(client, db, reg, cat):
    s = _system(client, reg, cat, laws=("a",))
    sid = s["id"]
    r = client.post(f"/api/v1/register/{sid}/go-live/submit")
    assert r.status_code == 409
    blockers = [e["message"] for e in r.json()["errors"]]
    assert any(b.startswith("Bias testing lead") for b in blockers) and any("Records retention owner" in b for b in blockers)
    assert any("A-01" in b for b in blockers)  # the go-live requirement is not met
    assert client.get(f"/api/v1/register/{sid}").json()["gate"]["state"] == "not_due"
    # fill everything required at go-live; the company-wide role comes from the AI Compliance Officer
    client.put(f"/api/v1/register/{sid}/roles/{cat.roles['bias_testing_lead'].id}", json={"status": "external", "external_party": "Futran Solutions", "external_contact": "audit@futran.test"})
    client.put(f"/api/v1/register/{sid}/requirements/{cat.req_a1.id}", json={"status": "met", "note": "Audit of 14 Sep 2026"})
    reg.as_(reg.caico)
    client.put(f"/api/v1/governance/company-roles/{cat.roles['records_retention_owner'].id}", json={"status": "pending_committee", "target_date": "2026-12-15"})
    reg.as_(reg.hr_lead)
    r = client.post(f"/api/v1/register/{sid}/go-live/submit")
    assert r.status_code == 409 and "pending committee" in r.json()["detail"].lower()
    reg.as_(reg.caico)
    client.put(f"/api/v1/governance/company-roles/{cat.roles['records_retention_owner'].id}", json={"status": "assigned", "user_id": reg.caico.id})
    reg.as_(reg.hr_lead)
    r = client.post(f"/api/v1/register/{sid}/go-live/submit")
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "ready_for_go_live" and r.json()["gate"]["state"] == "awaiting_approval"
    assert client.post(f"/api/v1/register/{sid}/go-live/decide", json={"approve": True}).status_code == 403  # Department Heads cannot approve
    # a gap opening after submission still stops the approval
    reg.as_(reg.caico)
    client.put(f"/api/v1/governance/company-roles/{cat.roles['records_retention_owner'].id}", json={"status": "no_such_person"})
    r = client.post(f"/api/v1/register/{sid}/go-live/decide", json={"approve": True})
    assert r.status_code == 409
    client.put(f"/api/v1/governance/company-roles/{cat.roles['records_retention_owner'].id}", json={"status": "assigned", "user_id": reg.caico.id})
    r = client.post(f"/api/v1/register/{sid}/go-live/decide", json={"approve": True, "comment": "Approved by the committee"})
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "live" and r.json()["gate"]["state"] == "live_clear" and r.json()["live_since"]


def test_caico_cannot_approve_own_submission(client, db, reg, cat):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, stage="ready_for_go_live")
    assert client.post(f"/api/v1/register/{s['id']}/go-live/submit").status_code == 200
    assert client.post(f"/api/v1/register/{s['id']}/go-live/decide", json={"approve": True}).status_code == 403


def test_return_needs_comment(client, db, reg, cat):
    reg.as_(reg.hr_lead)
    s = new_system(client, department_id=reg.hr.id, stage="ready_for_go_live")
    client.post(f"/api/v1/register/{s['id']}/go-live/submit")
    reg.as_(reg.caico)
    assert client.post(f"/api/v1/register/{s['id']}/go-live/decide", json={"approve": False}).status_code == 422
    r = client.post(f"/api/v1/register/{s['id']}/go-live/decide", json={"approve": False, "comment": "Name the oversight person first"})
    assert r.status_code == 200 and r.json()["go_live"]["requested_at"] is None


def test_requirements_checklist(client, db, reg, cat):
    s = _system(client, reg, cat, laws=("a",))
    r = client.get(f"/api/v1/register/{s['id']}/requirements")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert [x["code"] for x in rows] == ["A-01", "A-02"]  # developer-only requirement left out for a bought system
    assert rows[0]["status"] == "not_met" and rows[0]["gate"] is True and rows[1]["gate"] is False
    e = client.post(f"/api/v1/register/{s['id']}/history", json={"type": "bias_test", "occurred_on": "2026-09-14", "summary": "Independent audit", "details": {"tester_type": "independent", "result": "passed"}}).json()
    r = client.put(f"/api/v1/register/{s['id']}/requirements/{cat.req_a1.id}", json={"status": "met", "history_entry_ids": [e["id"]]})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/register/{s['id']}/requirements").json()
    assert got["met"] == 1 and got["total"] == 2 and got["rows"][0]["history_entries"][0]["id"] == e["id"]
    assert client.put(f"/api/v1/register/{s['id']}/requirements/{cat.req_a2.id}", json={"status": "not_applicable"}).status_code == 422
    assert client.put(f"/api/v1/register/{s['id']}/requirements/{cat.req_dev.id}", json={"status": "met"}).status_code == 404


def test_requirement_status_carries_to_next_law_version(client, db, reg, cat):
    s = _system(client, reg, cat, laws=("a",))
    client.put(f"/api/v1/register/{s['id']}/requirements/{cat.req_a1.id}", json={"status": "met", "note": "Done"})
    v2 = LawVersion(regulation_id=cat.a.id, version_no=2, status="in_force")
    db.add(v2)
    db.flush()
    db.add(Requirement(law_version_id=v2.id, code="A-01", order=1, text="Bias audit within the past 12 months (amended)", needed_by_stage="go_live"))
    cat.a.current_version_id = v2.id
    db.commit()
    rows = client.get(f"/api/v1/register/{s['id']}/requirements").json()["rows"]
    assert rows[0]["status"] == "met" and rows[0]["carried_from_previous_version"] is True


def test_bulk_roles_with_conflicts(client, db, reg, cat):
    a = _system(client, reg, cat, laws=("b",), name="Résumé screening")
    b = _system(client, reg, cat, laws=("b",), name="Benefits agent", type="agent")
    rid = cat.roles["human_oversight_person"].id
    client.put(f"/api/v1/register/{a['id']}/roles/{rid}", json={"status": "assigned", "user_id": reg.hr_lead.id})
    body = {"system_ids": [a["id"], b["id"]], "roles": [{"role_id": rid, "status": "assigned", "user_id": reg.hr_user.id, "on_conflict": "keep"}], "reason": "Oversight before go-live", "preview": True}
    pv = client.post("/api/v1/register/bulk", json=body).json()
    conflicts = [c for x in pv["systems"] for c in x["conflicts"]]
    assert len(conflicts) == 1 and conflicts[0]["current"] == "Priya Shah"
    r = client.post("/api/v1/register/bulk", json=body | {"preview": False})
    assert r.status_code == 200, r.text
    rows_a, rows_b = _rows(client, a["id"]), _rows(client, b["id"])
    assert rows_a["human_oversight_person"]["assignment"]["user"]["name"] == "Priya Shah"  # kept
    assert rows_b["human_oversight_person"]["assignment"]["user"]["name"] == "Hana Ito"
    client.post("/api/v1/register/bulk", json=body | {"preview": False, "roles": [{"role_id": rid, "status": "assigned", "user_id": reg.hr_user.id, "on_conflict": "add"}]})
    extra = _rows(client, a["id"])["human_oversight_person"]["assignment"]["extra_users"]
    assert [u["name"] for u in extra] == ["Hana Ito"]
    client.post("/api/v1/register/bulk", json=body | {"preview": False, "roles": [{"role_id": rid, "status": "assigned", "user_id": reg.hr_user.id, "on_conflict": "replace"}]})
    assert _rows(client, a["id"])["human_oversight_person"]["assignment"]["user"]["name"] == "Hana Ito"
    # stop authority is an agent role: it applies to the agent only
    r = client.post("/api/v1/register/bulk", json={"system_ids": [a["id"], b["id"]], "roles": [{"role_id": cat.roles["stop_disengage_authority"].id, "status": "no_such_person"}], "reason": "x"})
    assert r.json()["systems_changed"] == 1


def test_committee_member_covers_role_and_appears_in_choices(client, db, reg, cat):
    reg.as_(reg.caico)
    r = client.post("/api/v1/governance/committee/members", json={"user_id": reg.admin.id, "committee_role": "chair", "covers_role_id": cat.roles["accountable_executive"].id})
    assert r.status_code == 200 and r.json()["covers_role"] == "Accountable executive"
    s = new_system(client, department_id=reg.hr.id)
    people = client.get(f"/api/v1/register/{s['id']}/roles").json()["people"]
    assert next(p for p in people if p["id"] == reg.admin.id)["committee_role"] == "Chair"


def test_company_roles_page(client, db, reg, cat):
    _system(client, reg, cat, laws=("a",))
    reg.as_(reg.caico)
    page = client.get("/api/v1/governance/company-roles").json()
    assert [x["code"] for x in page["rows"]] == ["accountable_executive", "records_retention_owner"]
    assert page["kpis"]["systems"] == 1 and page["kpis"]["roles_no_person"] == 0
    hr = next(d for d in page["by_department"] if d["department"] == "Human Resources")
    assert hr["systems"] == 1
    assert db.scalar(select(RegisterSystem)) is not None


def test_suggested_laws_come_from_applicability(client, db, reg, cat):
    from app.regmaster.models import ClientLawApplicability

    db.add(ClientLawApplicability(organization_id=reg.org.id, regulation_id=cat.a.id, law_version_id=cat.va.id, in_scope=True, reason_text="Hires in New York City"))
    db.add(ClientLawApplicability(organization_id=reg.org.id, regulation_id=cat.b.id, law_version_id=cat.vb.id, in_scope=False, reason_text="No operations there"))
    db.commit()
    reg.as_(reg.hr_lead)
    s = new_system(client, department_id=reg.hr.id)
    got = client.get(f"/api/v1/register/{s['id']}").json()["suggested_laws"]
    assert got == [{"regulation_id": cat.a.id, "short_name": cat.a.short_name, "reason": "Hires in New York City"}]
    client.post(f"/api/v1/register/{s['id']}/laws", json={"regulation_id": cat.a.id})
    assert client.get(f"/api/v1/register/{s['id']}").json()["suggested_laws"] == []


def test_role_catalog_for_bulk_edit(client, db, reg, cat):
    reg.as_(reg.hr_lead)
    rows = client.get("/api/v1/register/role-catalog").json()
    assert [r["code"] for r in rows][:2] == ["accountable_executive", "records_retention_owner"]
    assert {r["level"] for r in rows} == {"company", "system", "agent"} and rows[0]["name"] == "Accountable executive"
