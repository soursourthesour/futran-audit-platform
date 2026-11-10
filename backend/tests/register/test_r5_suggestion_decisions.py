"""Suggested-law decisions: dismissals logged and sent as operations, reasons from the server (review R5)."""

import pytest
from sqlalchemy import select

from app.register.models import RegisterSystem, RegisterSystemLaw
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


def test_dismissing_and_restoring_a_suggestion_is_logged_and_works_by_operation(client, lib, reg, db):
    reg.as_(reg.caico)
    s = new_system(client, **HIRING, department_id=reg.hr.id, run_location=NYC, data_locations=[{"country": "US", "region": "US-IL"}])
    sug = _sugg(client, s["id"])
    il, ll = sug["HB 3773, amending the Illinois Human Rights Act"], sug["NYC Local Law 144"]
    r = client.patch(f"/api/v1/register/{s['id']}", json={"dismiss_law_ids": [il["regulation_id"]]})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/v1/register/{s['id']}", json={"dismiss_law_ids": [ll["regulation_id"]]})
    assert set(r.json()["dismissed_law_ids"]) == {il["regulation_id"], ll["regulation_id"]}  # added to, not replaced
    r = client.patch(f"/api/v1/register/{s['id']}", json={"undismiss_law_ids": [il["regulation_id"]]})
    assert r.json()["dismissed_law_ids"] == [ll["regulation_id"]]
    rows = [c for c in client.get(f"/api/v1/register/{s['id']}/changes").json() if c["field"] == "law_suggestions"]
    texts = [c["new_value"] for c in rows]
    assert any(t.startswith("Removed suggestion") and "HB 3773" in t for t in texts)
    assert any(t.startswith("Restored suggestion") and "HB 3773" in t for t in texts)
    assert any("Local Law 144" in t for t in texts)


def test_accepting_a_suggestion_stores_the_servers_reason(client, lib, reg, db):
    reg.as_(reg.caico)
    s = new_system(client, **HIRING, department_id=reg.hr.id, run_location=NYC)
    ll = _sugg(client, s["id"])["NYC Local Law 144"]
    r = client.post(f"/api/v1/register/{s['id']}/laws", json={"regulation_id": ll["regulation_id"], "source": "suggested", "suggestion_reason": "Anything I like"})
    assert r.status_code == 200, r.text
    link = db.scalar(select(RegisterSystemLaw).where(RegisterSystemLaw.register_system_id == s["id"]))
    assert link.source == "suggested" and link.reason == ll["reason"]


def test_a_law_the_server_does_not_suggest_cannot_be_accepted_as_suggested(client, lib, reg, db):
    reg.as_(reg.caico)
    s = new_system(client, **HIRING, department_id=reg.hr.id, run_location=NYC)
    other = find_law(db, "US-IL", "HB 3773")
    r = client.post(f"/api/v1/register/{s['id']}/laws", json={"regulation_id": other.id, "source": "suggested", "suggestion_reason": "Made up"})
    assert r.status_code == 422, r.text
    r = client.post("/api/v1/register", json={**HIRING, "department_id": reg.hr.id, "run_location": NYC, "regulation_ids": [other.id], "law_reasons": {other.id: "Made up"}})
    assert r.status_code == 422, r.text


def test_new_system_stores_the_servers_reason_for_an_accepted_suggestion(client, lib, reg, db):
    reg.as_(reg.caico)
    ll144 = find_law(db, "US-NYC", "Local Law 144")
    s = new_system(client, **HIRING, department_id=reg.hr.id, run_location=NYC, regulation_ids=[ll144.id], law_reasons={ll144.id: "Anything"})
    link = db.scalar(select(RegisterSystemLaw).where(RegisterSystemLaw.register_system_id == s["id"]))
    assert link.source == "suggested" and link.reason.startswith("Runs in New York City")


def test_save_with_places_and_accepted_suggestion_in_one_request(client, lib, reg, db):
    reg.as_(reg.caico)
    s = new_system(client, **HIRING, department_id=reg.hr.id)
    ll144 = find_law(db, "US-NYC", "Local Law 144")
    r = client.patch(f"/api/v1/register/{s['id']}", json={"run_location": NYC, "accept_suggested_law_ids": [ll144.id]})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["run_location"] == NYC
    law = next(x for x in got["laws"] if x["short_name"] == "NYC Local Law 144")
    assert law["reason"].startswith("Runs in New York City")


def test_a_refused_acceptance_saves_nothing_from_the_request(client, lib, reg, db):
    reg.as_(reg.caico)
    s = new_system(client, **HIRING, department_id=reg.hr.id)
    other = find_law(db, "US-IL", "HB 3773")
    r = client.patch(f"/api/v1/register/{s['id']}", json={"run_location": NYC, "accept_suggested_law_ids": [other.id]})
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.get(RegisterSystem, s["id"]).run_location is None


def test_accepting_needs_the_right_to_add_laws(client, lib, reg, db):
    reg.as_(reg.caico)
    s = new_system(client, **HIRING, department_id=reg.hr.id, run_location=NYC)
    ll = _sugg(client, s["id"])["NYC Local Law 144"]
    reg.as_(reg.contrib)
    r = client.patch(f"/api/v1/register/{s['id']}", json={"accept_suggested_law_ids": [ll["regulation_id"]]})
    assert r.status_code in (403, 404)
