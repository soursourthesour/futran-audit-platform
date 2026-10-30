"""Applicability engine (§25.4): client geographies + scope tests -> laws in and out of scope, with reasons;
required roles as the strictest union of role maps; committees as the union of committee rules."""
import pytest
from sqlalchemy import select

from app.laws.models import Regulation
from app.reference.jurisdictions import by_code
from app.regmaster import engine
from app.regmaster.models import ClientGeography, ClientLawApplicability
from app.regmaster.seed import find_law, seed_regmaster
from tests.factories import make_org


@pytest.fixture
def master(matrix):
    seed_regmaster(matrix)
    return matrix


def _geo(db, org, *codes, basis="office"):
    for c in codes:
        db.add(ClientGeography(organization_id=org.id, jurisdiction_id=by_code(db, c).id, basis=basis, source="manual"))
    db.flush()


def _row(db, org, code, pattern):
    reg = find_law(db, code, pattern)
    return db.scalar(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org.id, ClientLawApplicability.regulation_id == reg.id))


def test_geography_puts_city_law_in_scope_and_explains_out_of_scope(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-NYC")
    engine.run(db, org.id)
    ll144 = _row(db, org, "US-NYC", "Local Law 144")
    assert ll144.in_scope and "New York City" in ll144.reason_text
    co = _row(db, org, "US-CO", "^SB 26-189$")
    assert co.in_scope is False
    assert co.reason_text == "No Colorado operations or residents"


def test_country_inherits_supranational_laws(master):
    db = master
    org = make_org(db)
    _geo(db, org, "DE")
    engine.run(db, org.id)
    assert _row(db, org, "EU", "2024/1689").in_scope
    assert _row(db, org, "EU", "^GDPR").in_scope


def test_unknown_use_is_in_scope_to_confirm(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-CO")
    engine.run(db, org.id)
    co = _row(db, org, "US-CO", "^SB 26-189$")
    assert co.in_scope and "confirm" in co.reason_text.lower()


def test_answer_no_on_decisive_question_takes_law_out(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-CO")
    engine.run(db, org.id)
    reg = find_law(db, "US-CO", "^SB 26-189$")
    engine.set_answers(db, org.id, reg.id, {"2": "no"}, actor_id=None)
    co = _row(db, org, "US-CO", "^SB 26-189$")
    assert co.in_scope is False and "consequential" in co.reason_text


def test_override_survives_rerun(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-NYC")
    engine.run(db, org.id)
    reg = find_law(db, "US-NYC", "Local Law 144")
    engine.override(db, org.id, reg.id, in_scope=False, reason="Client confirmed no NYC hiring", actor_id="u1")
    engine.run(db, org.id)
    row = _row(db, org, "US-NYC", "Local Law 144")
    assert row.in_scope is False and row.override and row.reason_text == "Client confirmed no NYC hiring"


def test_required_roles_take_the_strictest_level_and_show_every_source(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-NYC", "US-IL")
    engine.run(db, org.id)
    roles = {r["code"]: r for r in engine.required_roles(db, org.id)}
    # NYC LL144 requires a bias testing lead; Illinois HB 3773 only recommends one: required wins, both shown
    bias = roles["bias_testing_lead"]
    assert bias["level"] == "required"
    assert {s["law"] for s in bias["sources"]} >= {"NYC LL144", "Illinois HB 3773"}
    assert roles["transparency_notice_owner"]["level"] == "required"


def test_earliest_stage_wins(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-CO", "US-CA")
    engine.run(db, org.id)
    roles = {r["code"]: r for r in engine.required_roles(db, org.id)}
    # records retention: Colorado ongoing, CA ADS ongoing -> ongoing; data steward: CCPA recommended development
    assert roles["records_retention_owner"]["needed_by"] == "ongoing"


def test_committees_union(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-CO", "US-NYC")
    engine.run(db, org.id)
    types = {c["committee_type"]: c for c in engine.committees(db, org.id)}
    assert types["ai_governance_committee"]["level"] == "recommended"  # NIST baseline applies to every client
    assert types["consequential_decision_rights"]["level"] == "required"


def test_rerun_when_geography_changes(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-NYC")
    engine.run(db, org.id)
    engine.add_geography(db, org.id, by_code(db, "US-CO").id, "customers", actor_id=None)
    assert _row(db, org, "US-CO", "^SB 26-189$").in_scope
