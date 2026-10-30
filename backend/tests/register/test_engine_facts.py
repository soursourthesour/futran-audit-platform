"""§25.4: the applicability engine pre-fills scope answers from the client's AI systems, including the register, and
re-runs when a register system is created, its decision impact or type changes, or its laws change: once per request."""
import pytest
from sqlalchemy import select

from app.reference.jurisdictions import by_code
from app.regmaster import engine
from app.regmaster.models import ClientGeography, ClientLawApplicability
from app.regmaster.seed import find_law, seed_regmaster
from tests.register.conftest import new_system


@pytest.fixture
def nyc(matrix, reg):
    db = matrix
    seed_regmaster(db)
    db.add(ClientGeography(organization_id=reg.org.id, jurisdiction_id=by_code(db, "US-NYC").id, basis="office", source="manual"))
    db.flush()
    engine.run(db, reg.org.id)
    db.commit()
    return find_law(db, "US-NYC", "Local Law 144")


def _row(db, org, law):
    db.expire_all()
    return db.scalar(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org.id, ClientLawApplicability.regulation_id == law.id))


@pytest.fixture
def runs(monkeypatch):
    calls = []
    real = engine.run

    def counted(db, org_id, actor_id=None):
        calls.append(org_id)
        return real(db, org_id, actor_id)

    monkeypatch.setattr(engine, "run", counted)
    return calls


def test_register_system_making_hiring_decisions_brings_the_law_in(client, db, reg, nyc, runs):
    assert "to confirm" in _row(db, reg.org, nyc).reason_text  # nothing known yet
    reg.as_(reg.caico)
    new_system(client, name="Résumé screening", department_id=reg.hr.id, decision_impact="consequential")
    row = _row(db, reg.org, nyc)
    assert row.in_scope and "Résumé screening" in row.reason_text and "to confirm" not in row.reason_text
    assert runs == [reg.org.id]  # once for the request


def test_register_with_no_decisions_takes_the_law_out_and_an_edit_brings_it_back(client, db, reg, nyc, runs):
    reg.as_(reg.caico)
    s = new_system(client, name="Meeting notes", type="genai_chat_tool", sourcing="vendor", department_id=reg.hr.id, decision_impact="none")
    row = _row(db, reg.org, nyc)
    assert not row.in_scope and "employment" in row.reason_text
    runs.clear()
    r = client.patch(f"/api/v1/register/{s['id']}", json={"decision_impact": "consequential", "purpose": "Ranks applicants for recruiters.", "reason": "Now screens applicants"})
    assert r.status_code == 200, r.text
    assert _row(db, reg.org, nyc).in_scope
    assert runs == [reg.org.id]


def test_an_edit_that_changes_no_fact_does_not_re_run(client, db, reg, nyc, runs):
    reg.as_(reg.caico)
    s = new_system(client, name="Meeting notes", department_id=reg.hr.id, decision_impact="none")
    runs.clear()
    client.patch(f"/api/v1/register/{s['id']}", json={"users_description": "All of HR", "reason": "Wider use"})
    assert runs == []


def test_adding_a_law_re_runs_once(client, db, reg, nyc, runs):
    reg.as_(reg.caico)
    s = new_system(client, name="Meeting notes", department_id=reg.hr.id, decision_impact="none")
    runs.clear()
    r = client.post(f"/api/v1/register/{s['id']}/laws", json={"regulation_id": nyc.id, "reason": "Used for interviews in New York"})
    assert r.status_code == 200, r.text
    assert runs == [reg.org.id]


def test_retired_systems_are_not_facts(client, db, reg, nyc):
    reg.as_(reg.caico)
    s = new_system(client, name="Résumé screening", department_id=reg.hr.id, decision_impact="consequential")
    assert _row(db, reg.org, nyc).in_scope and "Résumé screening" in _row(db, reg.org, nyc).reason_text
    r = client.post(f"/api/v1/register/{s['id']}/retire", json={"reason": "Replaced"})
    assert r.status_code == 200, r.text
    assert "Résumé screening" not in (_row(db, reg.org, nyc).reason_text or "")
