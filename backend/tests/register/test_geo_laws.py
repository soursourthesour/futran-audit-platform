"""11-03 C14: where a system runs and where the people whose data it uses are, and the laws suggested from those places
and the system's features by the law library's own scope logic (no AI)."""
import pytest
from sqlalchemy import select

from app.reference.jurisdictions import by_code
from app.register.models import RegisterSystem, RegisterSystemLaw
from app.regmaster import engine
from app.regmaster.models import ClientGeography, ClientLawApplicability, ScopeTest
from app.regmaster.seed import find_law, seed_regmaster
from tests.register.conftest import new_system

NYC = {"country": "US", "region": "US-NY", "city": "New York"}
HIRING = {"name": "Résumé screening", "purpose": "Ranks job applicants for recruiters.", "decision_impact": "consequential", "type": "vendor_app", "sourcing": "vendor",
          "data": {"data_categories": ["personal"], "data_subjects": ["candidates"]}}


@pytest.fixture
def lib(matrix, reg, client):
    seed_regmaster(matrix)
    matrix.commit()

    def no_ai(settings):  # suggestions never call a model
        raise AssertionError("the law suggestions called an AI model")

    client.app.state.ai_client_factory = no_ai
    yield matrix
    client.app.state.ai_client_factory = None


def suggest(client, **draft):
    r = client.post("/api/v1/register/law-suggestions", json=draft)
    assert r.status_code == 200, r.text
    return {x["short_name"]: x for x in r.json()}


def test_runs_in_new_york_city_and_hires(client, lib, reg):
    reg.as_(reg.hr_lead)
    out = suggest(client, **HIRING, department_id=reg.hr.id, run_location=NYC)
    ll144 = out["NYC Local Law 144"]
    assert "Runs in New York City" in ll144["reason"] and "employment decisions" in ll144["reason"] and ll144["basis"] == "scope_test"
    assert ll144["jurisdiction"] == "New York City"
    assert "HB 3773, amending the Illinois Human Rights Act" not in out


def test_people_in_illinois_bring_illinois_law_though_it_runs_in_texas(client, lib, reg):
    reg.as_(reg.hr_lead)
    out = suggest(client, **HIRING, run_location={"country": "US", "region": "US-TX"}, data_locations=[{"country": "US", "region": "US-IL"}])
    il = out["HB 3773, amending the Illinois Human Rights Act"]
    assert "people whose data it uses are in Illinois" in il["reason"]
    assert "NYC Local Law 144" not in out


def test_no_decisions_about_people_leaves_hiring_laws_out(client, lib, reg):
    reg.as_(reg.hr_lead)
    out = suggest(client, **(HIRING | {"decision_impact": "none"}), run_location=NYC)
    assert "NYC Local Law 144" not in out


def test_eu_place_brings_eu_laws(client, lib, reg):
    reg.as_(reg.hr_lead)
    out = suggest(client, **HIRING, run_location={"country": "DE"})
    assert any(k.startswith("GDPR") for k in out) and any("2024/1689" in k for k in out)
    gdpr = next(v for k, v in out.items() if k.startswith("GDPR"))
    assert "Germany" in gdpr["reason"] or "European Union" in gdpr["reason"]


def test_feature_match_for_laws_without_scope_questions(client, lib, reg):
    """A law with no scope questions is suggested when it is a law of a place the system reaches and covers one of its features."""
    reg.as_(reg.hr_lead)
    out = suggest(client, **HIRING, run_location={"country": "US", "region": "US-CA"})
    robo = out["SB 947 'No Robo Bosses Act of 2026'"]
    assert robo["basis"] == "feature" and "employment and hiring" in robo["reason"] and "California" in robo["reason"]
    assert "SB 53 Transparency in Frontier AI Act" not in out  # developers only; the system is bought
    assert "SB 1120" not in out  # health care AI: no health data


def test_no_places_no_suggestions(client, lib, reg):
    reg.as_(reg.hr_lead)
    assert suggest(client, **HIRING) == {}


def test_same_answer_as_the_scope_engine(client, lib, reg, db):
    """For every law with scope questions, the system's suggestion matches the engine's decision for a client whose only
    geography is that place and whose only AI system is this one."""
    reg.as_(reg.caico)
    for place, code in ((NYC, "US-NYC"), ({"country": "US", "region": "US-CO"}, "US-CO"), ({"country": "FR"}, "FR")):
        out = suggest(client, **HIRING, run_location=place)
        org = reg.org
        for g in db.scalars(select(ClientGeography).where(ClientGeography.organization_id == org.id)):
            db.delete(g)
        db.flush()
        db.add(ClientGeography(organization_id=org.id, jurisdiction_id=by_code(db, code).id, basis="office", source="manual"))
        sys_ = db.scalar(select(RegisterSystem).where(RegisterSystem.organization_id == org.id, RegisterSystem.name == "Résumé screening"))
        if sys_ is None:
            new_system(client, **HIRING, department_id=reg.hr.id)
        db.flush()
        engine.run(db, org.id)
        tested = set(db.scalars(select(ScopeTest.law_version_id)))
        rows = db.scalars(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org.id, ClientLawApplicability.deleted_at.is_(None),
                                                               ClientLawApplicability.law_version_id.in_(tested)))
        from app.laws.models import Regulation

        engine_in = {db.get(Regulation, r.regulation_id).short_name for r in rows if r.in_scope}
        mine = {k for k, v in out.items() if v["basis"] == "scope_test"}
        assert mine == engine_in, (code, mine, engine_in)


def test_saved_system_shows_geo_suggestions_accepts_with_reason_and_dismisses(client, lib, reg, db):
    reg.as_(reg.caico)
    s = new_system(client, **HIRING, department_id=reg.hr.id, run_location=NYC, data_locations=[{"country": "US", "region": "US-IL"}])
    assert s["run_location"] == NYC and s["run_location_label"] == "New York, New York, United States"
    sug = {x["short_name"]: x for x in client.get(f"/api/v1/register/{s['id']}").json()["suggested_laws"]}
    ll144 = sug["NYC Local Law 144"]
    r = client.post(f"/api/v1/register/{s['id']}/laws", json={"regulation_id": ll144["regulation_id"], "source": "suggested", "suggestion_reason": ll144["reason"]})
    assert r.status_code == 200
    link = db.scalar(select(RegisterSystemLaw).where(RegisterSystemLaw.register_system_id == s["id"]))
    assert link.source == "suggested" and link.reason == ll144["reason"]
    after = {x["short_name"] for x in r.json()["suggested_laws"]}
    assert "NYC Local Law 144" not in after
    il = sug["HB 3773, amending the Illinois Human Rights Act"]
    r = client.patch(f"/api/v1/register/{s['id']}", json={"dismissed_law_ids": [il["regulation_id"]]})
    assert r.status_code == 200 and il["short_name"] not in {x["short_name"] for x in r.json()["suggested_laws"]}


def test_new_system_saves_accepted_suggestions_with_their_reason(client, lib, reg, db):
    reg.as_(reg.caico)
    ll144 = find_law(db, "US-NYC", "Local Law 144")
    s = new_system(client, **HIRING, department_id=reg.hr.id, run_location=NYC, regulation_ids=[ll144.id], law_reasons={ll144.id: "Runs in New York City"})
    link = db.scalar(select(RegisterSystemLaw).where(RegisterSystemLaw.register_system_id == s["id"]))
    assert link.source == "suggested" and link.reason.startswith("Runs in New York City")  # the server's reason


def test_existing_system_without_geography_keeps_its_laws_and_old_suggestions(client, lib, reg, db):
    reg.as_(reg.caico)
    ll144 = find_law(db, "US-NYC", "Local Law 144")
    s = new_system(client, **HIRING, department_id=reg.hr.id, regulation_ids=[ll144.id])
    got = client.get(f"/api/v1/register/{s['id']}").json()
    assert [x["short_name"] for x in got["laws"]] == ["NYC Local Law 144"] and got["run_location"] is None and got["data_locations"] == []
    assert isinstance(got["suggested_laws"], list)


def test_bad_places_are_refused(client, lib, reg):
    reg.as_(reg.caico)
    r = client.post("/api/v1/register", json={"name": "X", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.hr.id, "run_location": {"country": "US", "region": "DE-BY"}})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "run_location"
    r = client.post("/api/v1/register", json={"name": "X", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.hr.id, "data_locations": [{"country": "ZZ"}]})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "data_locations"


def test_suggestions_need_a_client_user(client, lib, reg):
    client.cookies.clear()
    assert client.post("/api/v1/register/law-suggestions", json={"run_location": NYC}).status_code == 401
