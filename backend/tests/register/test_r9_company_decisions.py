"""Suggestions respect the company's own decision on a law (review R9)."""

import pytest

from app.regmaster import engine
from app.regmaster.seed import find_law, seed_regmaster
from tests.register.conftest import new_system

NYC = {"country": "US", "region": "US-NY", "city": "New York"}
HIRING = {"name": "Résumé screening", "purpose": "Ranks job applicants for recruiters.", "decision_impact": "consequential", "type": "vendor_app", "sourcing": "vendor",
          "data": {"data_categories": ["personal"], "data_subjects": ["candidates"]}}


@pytest.fixture
def lib(matrix, reg, client):
    seed_regmaster(matrix)
    matrix.commit()
    return matrix


def _sugg(client, sid):
    return {x["short_name"]: x for x in client.get(f"/api/v1/register/{sid}").json()["suggested_laws"]}


def test_a_law_ruled_out_for_the_company_is_not_suggested_and_one_ruled_in_is(client, lib, reg, db):
    reg.as_(reg.caico)
    s = new_system(client, **HIRING, department_id=reg.hr.id, run_location=NYC)
    db.commit()
    ll144 = find_law(db, "US-NYC", "Local Law 144")
    engine.override(db, reg.org.id, ll144.id, False, "We do not hire in New York City.", reg.caico.id)
    db.commit()
    assert "NYC Local Law 144" not in _sugg(client, s["id"])
    r = client.post("/api/v1/register/law-suggestions", json={**HIRING, "run_location": NYC})
    assert "NYC Local Law 144" not in {x["short_name"] for x in r.json()}
    eu = find_law(db, "EU", "AI Act")
    engine.override(db, reg.org.id, eu.id, True, "Group policy.", reg.caico.id)
    db.commit()
    got = _sugg(client, s["id"])
    hit = next(v for k, v in got.items() if v["regulation_id"] == eu.id)
    assert hit["reason"].startswith("In scope for the company")
