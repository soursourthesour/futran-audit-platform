"""Headquarters site "Same as company address" (fixes 2026-10-27, item 1b)."""
import pytest
from sqlalchemy import select

from app.engagements.models import ClientLocation
from tests.engagements.helpers import _new, _put
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def aud(db, matrix):
    f = make_org(db, type="futran")
    u = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    db.commit()
    return u


COMPANY = {"legal_name": "ABC Corp Inc.", "hq_street": "350 Fifth Avenue", "hq_city": "New York", "hq_state": "New York", "hq_postal_code": "10118", "hq_country": "US"}


def _sites(db, cid):
    db.expire_all()
    return list(db.scalars(select(ClientLocation).where(ClientLocation.organization_id == cid, ClientLocation.deleted_at.is_(None)).order_by(ClientLocation.created_at)))


def test_hq_copies_the_company_address(client, db, aud):
    login_as(client, db, aud)
    cid = _new(client)["client_id"]
    _put(client, cid, "company", COMPANY)
    out = _put(client, cid, "locations", {"hq_same_as_company": True, "locations": [
        {"site_name": "Headquarters", "country_code": "DE", "in_scope": True},
        {"site_name": "Chicago office", "city": "Chicago", "subdivision_code": "US-IL", "country_code": "US", "in_scope": True},
    ]})
    assert out["errors"] == []
    hq, chicago = _sites(db, cid)
    assert (hq.site_name, hq.street, hq.city, hq.subdivision_code, hq.country_code) == ("Headquarters", "350 Fifth Avenue", "New York", "US-NY", "US")
    assert chicago.city == "Chicago"
    w = client.get(f"/api/v1/clients/{cid}/wizard").json()
    assert w["locations"]["hq_same_as_company"] is True
    assert "New York City" in w["locations"]["locations"][0]["jurisdictions"]


def test_hq_follows_later_company_changes_while_ticked(client, db, aud):
    login_as(client, db, aud)
    cid = _new(client)["client_id"]
    _put(client, cid, "company", COMPANY)
    _put(client, cid, "locations", {"hq_same_as_company": True, "locations": [{"site_name": "Headquarters", "country_code": "US", "in_scope": True}]})
    _put(client, cid, "company", {"hq_street": "1 Wacker Drive", "hq_city": "Chicago", "hq_state": "IL", "hq_country": "US"})
    (hq,) = _sites(db, cid)
    assert (hq.street, hq.city, hq.subdivision_code) == ("1 Wacker Drive", "Chicago", "US-IL")
    # untick: the site keeps its values and stops following the company
    _put(client, cid, "locations", {"hq_same_as_company": False, "locations": [{"id": hq.id, "site_name": "Headquarters", "street": "1 Wacker Drive", "city": "Chicago", "subdivision_code": "US-IL", "country_code": "US", "in_scope": True}]})
    _put(client, cid, "company", {"hq_city": "Boston", "hq_state": "MA"})
    (hq,) = _sites(db, cid)
    assert hq.city == "Chicago"


def test_ticking_with_no_sites_creates_the_headquarters(client, db, aud):
    login_as(client, db, aud)
    cid = _new(client)["client_id"]
    _put(client, cid, "company", COMPANY)
    _put(client, cid, "locations", {"hq_same_as_company": True, "locations": []})
    (hq,) = _sites(db, cid)
    assert (hq.site_name, hq.city, hq.country_code) == ("Headquarters", "New York", "US")
