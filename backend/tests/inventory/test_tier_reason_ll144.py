"""BUG-02: the Tier 3 reason names NYC Local Law 144 only for employment decisions in New York City."""
from app.inventory.service import tier_reason

LL144 = "Local Law 144"


def test_a_consequential_use_case_outside_new_york_city_does_not_mention_ll144():
    reason = tier_reason("consequential", ["pii"], [], text="Credit scoring for consumer loans in Germany")
    assert "decisions about people" in reason
    assert LL144 not in reason


def test_the_default_call_does_not_mention_ll144():
    assert LL144 not in tier_reason("consequential", [], [])


def test_employment_use_outside_new_york_city_does_not_mention_ll144():
    assert LL144 not in tier_reason("consequential", [], [], text="Résumé screening for Berlin roles", in_nyc=False)


def test_non_employment_use_in_new_york_city_does_not_mention_ll144():
    assert LL144 not in tier_reason("consequential", [], [], text="Fraud scoring of card payments", in_nyc=True)


def test_employment_use_in_new_york_city_mentions_ll144():
    reason = tier_reason("consequential", [], [], text="Résumé screening: ranks applicants for recruiters", in_nyc=True)
    assert "decisions about people" in reason and LL144 in reason


def test_an_aedt_determined_in_scope_mentions_ll144():
    assert LL144 in tier_reason("consequential", [], [], aedt_determination="in_scope")


def test_lower_tier_reasons_never_mention_ll144():
    for args in (("informs", ["pii"], []), ("none", [], [])):
        assert LL144 not in tier_reason(*args, text="Hiring", in_nyc=True)


def test_in_nyc_reads_the_client_locations_when_no_geographies_exist(db):
    """BUG-K02: a New York client set up before the law library has a location but no geography rows yet."""
    from app.engagements.models import ClientLocation
    from app.inventory.service import in_nyc
    from app.reference.models import Jurisdiction
    from tests.factories import make_org

    nyc = Jurisdiction(code="US-NYC", name="New York City", level="city")
    berlin = Jurisdiction(code="DE-BE", name="Berlin", level="state")
    db.add_all([nyc, berlin])
    abc, meridian, gone = make_org(db, name="ABC Corp"), make_org(db, name="Meridian GmbH"), make_org(db, name="Closed office")
    db.flush()
    db.add_all([ClientLocation(organization_id=abc.id, site_name="HQ", city="New York", country_code="US", jurisdiction_ids=[nyc.id]),
                ClientLocation(organization_id=meridian.id, site_name="HQ", city="Berlin", country_code="DE", jurisdiction_ids=[berlin.id]),
                ClientLocation(organization_id=gone.id, site_name="Old", city="New York", country_code="US", jurisdiction_ids=[nyc.id], in_scope=False)])
    db.flush()
    assert in_nyc(db, abc.id) is True
    assert in_nyc(db, meridian.id) is False
    assert in_nyc(db, gone.id) is False  # a site taken out of scope does not count
