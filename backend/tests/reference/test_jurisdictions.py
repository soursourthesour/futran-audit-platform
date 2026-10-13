import pytest

from app.reference.jurisdictions import resolve_jurisdictions, seed_iso, upsert_city
from app.reference.models import Jurisdiction


@pytest.fixture
def seeded(db):
    seed_iso(db)
    return db


def codes(js):
    return [j.code for j in js]


def test_seed_creates_countries_subdivisions_and_eu(seeded):
    db = seeded
    us = db.query(Jurisdiction).filter_by(code="US").one()
    assert us.level == "country" and us.name == "United States"
    ny = db.query(Jurisdiction).filter_by(code="US-NY").one()
    assert ny.level == "state" and ny.parent_id == us.id
    eu = db.query(Jurisdiction).filter_by(code="EU").one()
    assert eu.level == "supranational"
    nyc = db.query(Jurisdiction).filter_by(code="US-NYC").one()
    assert nyc.level == "city" and nyc.parent_id == ny.id


def test_resolve_manhattan(seeded):
    assert codes(resolve_jurisdictions(seeded, "US", "US-NY", "Manhattan")) == ["US-NYC", "US-NY", "US"]


def test_resolve_by_state_name_and_new_york_city(seeded):
    assert codes(resolve_jurisdictions(seeded, "US", "New York", "New York City")) == ["US-NYC", "US-NY", "US"]


def test_resolve_berlin(seeded):
    assert codes(resolve_jurisdictions(seeded, "DE", "DE-BE", "Berlin")) == ["DE-BE", "DE", "EU"]


def test_resolve_bangalore(seeded):
    assert codes(resolve_jurisdictions(seeded, "IN", "Karnataka", "Bengaluru")) == ["IN-KA", "IN"]


def test_resolve_unknown_city_skips_city(seeded):
    assert codes(resolve_jurisdictions(seeded, "US", "US-IL", "Chicago")) == ["US-IL", "US"]


def test_resolve_country_only(seeded):
    assert codes(resolve_jurisdictions(seeded, "GB", None, None)) == ["GB"]


def test_admin_added_city_resolves(seeded):
    upsert_city(seeded, "US-IL", "Chicago", aliases=["Chicago, IL"])
    assert codes(resolve_jurisdictions(seeded, "US", "US-IL", "chicago"))[0] == "US-IL-CHICAGO"


def test_seed_iso_idempotent(seeded):
    n = seeded.query(Jurisdiction).count()
    seed_iso(seeded)
    assert seeded.query(Jurisdiction).count() == n
