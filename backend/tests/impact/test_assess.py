"""The live part of screen 28: proposed tier (§11, the register's rules), required depth and laws matched (§10.3, the
applicability engine's scope tests plus the law matrix's geography and AI feature)."""
import pytest
from sqlalchemy import select

from app.impact.assess import assess, project_features
from app.reference.models import Jurisdiction


@pytest.fixture
def geo(db, lit):
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(db)
    db.commit()
    return {j.code: j.id for j in db.scalars(select(Jurisdiction).where(Jurisdiction.code.in_(["US-NYC", "US-NY", "US-CA", "US-IL", "US-UT", "US-CO"])))}


CHATBOT = {"project_name": "Customer support chatbot", "purpose": "Answer customer questions about orders and refunds; hand off to an agent on request.",
           "system_type": "genai_chat_tool", "sourcing": "vendor", "data_categories": ["personal"], "data_subjects": ["customers"], "decision_impact": "informs",
           "public_facing": True}
SCREENER = {"project_name": "Interview scheduling and screening assistant", "purpose": "Ranks applicants for recruiter review and books interviews.",
            "system_type": "vendor_app", "sourcing": "vendor", "data_categories": ["personal"], "data_subjects": ["candidates"], "decision_impact": "consequential",
            "public_facing": False}


def test_a_consequential_project_is_tier_3_and_needs_the_full_assessment(db, geo):
    out = assess(db, SCREENER | {"jurisdiction_ids": [geo["US-NYC"]]})
    assert out["tier"] == 3 and "decisions about people" in out["tier_reason"]
    assert out["depth"] == "full" and "6.2" in out["depth_sections"]


def test_personal_data_in_a_public_chatbot_is_tier_2_light_plus_genai_security(db, geo):
    out = assess(db, CHATBOT | {"jurisdiction_ids": [geo["US-NY"], geo["US-IL"], geo["US-CA"]]})
    assert out["tier"] == 2 and out["depth"] == "light"
    assert {"3.1", "5.1", "7.2", "9.2", "8.1"} <= set(out["depth_sections"]) and "6.2" not in out["depth_sections"]
    assert "8.1.05" in out["depth_text"]


def test_no_personal_data_and_no_decisions_is_tier_1(db, geo):
    out = assess(db, CHATBOT | {"data_categories": [], "data_subjects": ["none"], "decision_impact": "none", "public_facing": False, "system_type": "embedded_feature",
                                "purpose": "Summarises internal meeting notes", "jurisdiction_ids": [geo["US-CA"]]})
    assert out["tier"] == 1 and out["depth"] == "baseline" and out["depth_sections"][:1] == ["3.1"]


def test_ll144_matches_a_hiring_tool_used_for_new_york_city_roles(db, geo):
    laws = {x["name"]: x for x in assess(db, SCREENER | {"jurisdiction_ids": [geo["US-NYC"]]})["laws"]}
    assert laws["NYC Local Law 144"]["matched"] is True
    assert any(x["matched"] and "NIST" in x["name"] for x in laws.values())  # the Futran default framework


def test_ll144_does_not_match_without_new_york_city_users(db, geo):
    laws = {x["name"]: x for x in assess(db, SCREENER | {"jurisdiction_ids": [geo["US-CA"]]})["laws"]}
    assert not laws.get("NYC Local Law 144", {}).get("matched")
    assert laws["FEHA automated-decision system regulations"]["matched"] is True  # California employment AI rules


def test_state_privacy_law_matches_by_geography_and_feature(db, geo):
    laws = assess(db, CHATBOT | {"jurisdiction_ids": [geo["US-CA"]]})["laws"]
    matched = {x["name"] for x in laws if x["matched"]}
    assert "CCPA/CPRA" in matched
    assert not {n for n in matched if n.startswith("No ")}  # placeholder rows of the matrix are never laws
    assert all(x["reason"] for x in laws)


def test_features_follow_the_intake(db):
    assert "employment_hiring" in project_features(SCREENER) and "consequential_decisions_admt" in project_features(SCREENER)
    assert project_features(CHATBOT) == ["privacy_profiling"]
    assert "health_insurance" in project_features(CHATBOT | {"data_categories": ["health"]})
    assert "biometrics_pricing" in project_features(CHATBOT | {"data_categories": ["biometric"]})
    assert "chatbots_minors" in project_features(CHATBOT | {"data_categories": ["children"]})


def test_answering_questions_about_prices_is_not_algorithmic_pricing(db):
    assert "biometrics_pricing" not in project_features(CHATBOT | {"purpose": "Answers questions about products and pricing on the website."})
    assert "biometrics_pricing" in project_features(CHATBOT | {"purpose": "Sets personalized pricing for each visitor."})


def test_near_misses_are_only_the_curated_laws_with_scope_tests(db, geo):
    near = [x for x in assess(db, CHATBOT | {"jurisdiction_ids": [geo["US-CA"]]})["laws"] if not x["matched"]]
    assert all("Privacy Act" not in x["name"] for x in near)  # other states' privacy laws are not listed as near misses
