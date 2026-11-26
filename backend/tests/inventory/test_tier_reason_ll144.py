"""BUG-02: the Tier 3 reason names NYC Local Law 144 only for employment decisions in New York City."""
from app.inventory.service import tier_reason
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401

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


# ---- From the 20 Nov hand-off build (BUG-02 fix rounds 1 and 2): phrase-level employment terms, Futran's AEDT
# determination both ways, and the department's name
NOT_EMPLOYMENT = ("24 hr fraud monitoring", "Policy termination model", "Candidate drug compounds", "Credit applicant scoring",
                  "Scores candidate songs for the company talent show", "Screening loan applicants", "Hire purchase approvals",
                  "Promotion recommendations for the spring sale", "Third-party risk scoring", "Shirt size recommendations")
EMPLOYMENT_USES = ("Candidate screening", "Candidate ranking", "Interview scoring", "Video interview analysis (HireVue)", "Talent acquisition matching",
                   "Hire prediction", "Screening applicants for open roles", "Employee promotion recommendations", "Ranks job applicants before recruiter review",
                   "Applicant screening", "Résumé screening: ranks applicants for recruiters", "Hiring assistant")


def test_words_that_are_not_about_employment_do_not_name_ll144():
    for text in NOT_EMPLOYMENT:
        assert LL144 not in tier_reason("consequential", [], [], text=text, in_nyc=True), text


def test_the_hiring_uses_ll144_is_aimed_at_still_name_it():
    for text in EMPLOYMENT_USES:
        assert LL144 in tier_reason("consequential", [], [], text=text, in_nyc=True), text


def test_an_aedt_determined_out_of_scope_does_not_name_ll144():
    assert LL144 not in tier_reason("consequential", [], [], text="Candidate screening", in_nyc=True, aedt_determination="out_of_scope")


def test_the_preview_uses_the_use_cases_aedt_determination_and_department(client, db, inv):
    from sqlalchemy import select

    from app.inventory.models import UseCase
    from app.tenancy.models import Department
    from tests.factories import login_as
    from tests.inventory.test_named_users import _uc

    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Operations"})
    ops = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "Operations"))
    uc = _uc(client, cid, ops, [copilot["id"]], name="Shift scheduler", purpose="Assigns warehouse shifts", decision_impact="consequential",
             usage=[{"role_name": "Supervisor", "headcount": 2, "frequency": "daily"}])
    db.get(UseCase, uc["id"]).aedt_determination = "in_scope"  # Futran decided it is an AEDT
    db.commit()
    detail = client.get(f"/api/v1/use-cases/{uc['id']}").json()
    assert LL144 in detail["tier_reason"]
    body = {"decision_impact": "consequential", "data_categories": ["none"], "tool_ids": [copilot["id"]], "name": "Shift scheduler",
            "purpose": "Assigns warehouse shifts", "department_id": ops.id}
    r = client.post(f"/api/v1/clients/{cid}/use-cases/tier-preview", json=body | {"use_case_id": uc["id"]})
    assert r.status_code == 200 and r.json()["reason"] == detail["tier_reason"]
    assert LL144 not in client.post(f"/api/v1/clients/{cid}/use-cases/tier-preview", json=body).json()["reason"]
    # a department whose name is about employment counts, as on the detail page
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Human Resources"})
    hr2 = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "Human Resources"))
    from app.inventory.service import in_nyc

    assert in_nyc(db, cid)
    r = client.post(f"/api/v1/clients/{cid}/use-cases/tier-preview", json=body | {"department_id": hr2.id})
    assert LL144 in r.json()["reason"]
