"""G-06: Engagement.type gains the ten Release 2 types (spec B6), defined once in servicetemplates.types."""
from app.servicetemplates.types import ENGAGEMENT_TYPES, NEW_ENGAGEMENT_TYPES
from tests.factories import login_as, make_org, make_user

TEN = ("vendor_due_diligence", "vendor_sponsored_audit", "ll144_applicability", "copilot_readiness", "eu_ai_act_readiness", "iso42001_readiness",
       "ma_due_diligence", "agent_assurance", "training_workshop", "advisory_retainer")


def test_the_ten_new_types_and_the_original_three_have_labels():
    assert NEW_ENGAGEMENT_TYPES == TEN
    assert tuple(ENGAGEMENT_TYPES)[:3] == ("initial_assessment", "ll144_bias_audit", "annual_review")
    assert set(TEN) <= set(ENGAGEMENT_TYPES)
    assert all(isinstance(v, str) and v and v[0].isupper() for v in ENGAGEMENT_TYPES.values())
    assert "Governix" not in " ".join(ENGAGEMENT_TYPES.values())


def test_engagements_accept_every_type(db):
    from app.engagements.service import TYPES, create_engagement
    from app.initiation.context import TYPE_LABELS

    assert set(TEN) <= set(TYPES)
    f = make_org(db, type="futran")
    chief = make_user(db, f, roles=["chief_auditor"])
    org = make_org(db, name="Acme")
    e = create_engagement(db, chief, org, name="Acme Copilot readiness", type="copilot_readiness")
    assert e.type == "copilot_readiness"
    assert TYPE_LABELS["eu_ai_act_readiness"] == ENGAGEMENT_TYPES["eu_ai_act_readiness"]


def test_the_new_client_wizard_scope_step_accepts_a_new_type(db, client):
    f = make_org(db, type="futran")
    chief = make_user(db, f, roles=["chief_auditor"])
    db.commit()
    login_as(client, db, chief)
    r = client.get("/api/v1/engagement-types")
    assert r.status_code == 200
    assert {t["value"] for t in r.json()["types"]} >= set(TEN)
    from app.engagements.wizard import SCOPE_FIELDS

    assert SCOPE_FIELDS["type"]("iso42001_readiness") == "iso42001_readiness"
