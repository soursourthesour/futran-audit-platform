import pytest
from sqlalchemy import select

from app.engagements.models import Engagement
from app.questionnaire.seed import load_question_bank
from app.questionnaire.service import Target, save_response
from app.reference.catalogs import load_catalogs
from app.scoring import service as scoring
from app.scoring.models import EngagementScorecard, SystemRiskScore
from app.systems.models import AISystem
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401

ATS_ANSWERS = {"3.3.02": "human_assisted", "3.3.05s": "4", "3.3.07": "yes", "5.1.02": "no", "5.1.03": "yes", "5.1.04": "no", "3.3.06": "yes", "3.3.04": 2000, "3.2.01": ["ml"], "3.1.10": "client_facing_decision",
               "6.2.01": "no", "5.1a.05": "high"}
ATS_DOMAINS = {"governance": 3, "data": 2, "model": 2, "bias": 1, "oversight": 3, "security": 3, "incident": 2, "vendor_risk": 2}


@pytest.fixture
def ats(client, db, inv, people):
    """ABC Corp SYS-001, vendor-built ATS résumé screening, with the worked example's answers."""
    load_question_bank(db)
    load_catalogs(db)
    cid, e, maria, hr, *_ = inv
    e = db.get(Engagement, e.id)
    s = db.scalar(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.reference_id == "SYS-001"))
    s.built_by, s.department_id, s.name = "vendor", hr.id, "ATS résumé screening"
    db.flush()
    e.type = "ll144_bias_audit"  # so §5.1a (null-compliance) applies
    for code, v in ATS_ANSWERS.items():
        save_response(db, people["aud"], Target(e, s), code, {"value": v, "status": "answered", "source_person_name": "Lee Park", "source_person_title": "HR systems lead"}, futran=True)
    db.commit()
    return cid, e, maria, s


def _all_domains(db, people, s, scores):
    latest = scoring.latest(db, s)
    for d, v in scores.items():
        prop = latest.domain_scores_proposed.get(d)
        rationale = None if prop is not None and abs(prop - v) <= 1 else "Set from interviews and evidence review."
        scoring.set_final_domain_score(db, people["chief"], s, d, v, rationale)  # the Lead Auditor


def test_abc_sys001_scores_to_worked_example(client, db, ats, people):
    cid, e, maria, s = ats
    latest = scoring.latest(db, s)
    assert latest.inherent == 76.0 and latest.maturity is None and latest.computed_rating is None
    assert set(latest.knockouts_triggered) == {"no_bias_testing", "null_compliance_high"}
    assert latest.final_rating == "high"  # knock-outs force at least High before maturity is known
    _all_domains(db, people, s, ATS_DOMAINS)
    latest = scoring.latest(db, s)
    assert (latest.maturity, latest.residual, latest.computed_rating, latest.final_rating) == (2.25, 58.2, "high", "high")
    assert latest.methodology_version == "1.0"
    db.expire_all()
    assert db.get(AISystem, s.id).status == "scored"


def test_rationale_required_when_diff_gt_1(client, db, ats, people):
    cid, e, maria, s = ats
    login_as(client, db, people["chief"])
    prop = scoring.latest(db, s).domain_scores_proposed["governance"]
    far = 5 if prop <= 2 else 1
    r = client.put(f"/api/v1/systems/{s.id}/score/domains/governance", json={"score": far})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "rationale"
    assert client.put(f"/api/v1/systems/{s.id}/score/domains/governance", json={"score": far, "rationale": "Committee minutes reviewed."}).status_code == 200
    near = min(5, prop + 1)
    assert client.put(f"/api/v1/systems/{s.id}/score/domains/data", json={"score": near}).status_code == 200
    assert client.put(f"/api/v1/systems/{s.id}/score/domains/data", json={"score": 7}).status_code == 422
    assert client.put(f"/api/v1/systems/{s.id}/score/domains/astrology", json={"score": 3}).status_code == 404
    login_as(client, db, maria)
    assert client.put(f"/api/v1/systems/{s.id}/score/domains/data", json={"score": 3}).status_code in (403, 404)


def test_override_needs_lead_auditor_and_rationale(client, db, ats, people):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    assert client.put(f"/api/v1/systems/{s.id}/score/override", json={"rating": "critical", "rationale": "x"}).status_code == 403
    login_as(client, db, people["chief"])
    assert client.put(f"/api/v1/systems/{s.id}/score/override", json={"rating": "critical", "rationale": ""}).status_code == 422
    r = client.put(f"/api/v1/systems/{s.id}/score/override", json={"rating": "critical", "rationale": "Shortlists every applicant in NYC."})
    assert r.status_code == 200 and r.json()["final_rating"] == "critical"
    # the override survives later recalculation
    save_response(db, people["aud"], Target(db.get(Engagement, e.id), db.get(AISystem, s.id)), "3.3.04", {"value": 2500, "status": "answered", "source_person_name": "Lee Park", "source_person_title": "HR"}, futran=True)
    assert scoring.latest(db, s).final_rating == "critical"


def test_locked_score_not_recalculated(client, db, ats, people):
    cid, e, maria, s = ats
    _all_domains(db, people, s, ATS_DOMAINS)
    scoring.lock_scores(db, db.get(Engagement, e.id))
    db.commit()
    before = db.query(SystemRiskScore).count()
    locked = scoring.latest(db, s)
    assert locked.locked_at is not None and db.get(AISystem, s.id).status == "locked"
    scoring.recalculate(db, db.get(AISystem, s.id))
    assert db.query(SystemRiskScore).count() == before and scoring.latest(db, s).id == locked.id
    login_as(client, db, people["chief"])
    assert client.put(f"/api/v1/systems/{s.id}/score/domains/data", json={"score": 2}).status_code == 409


def test_client_cannot_view_score_before_stage7(client, db, ats, people):
    cid, e, maria, s = ats
    login_as(client, db, maria)
    assert client.get(f"/api/v1/systems/{s.id}/score").status_code == 403
    assert client.get(f"/api/v1/clients/{cid}/scorecard").status_code == 403
    db.get(Engagement, e.id).stage = 7
    db.commit()
    r = client.get(f"/api/v1/systems/{s.id}/score")
    assert r.status_code == 200 and r.json()["inherent"] == 76.0
    login_as(client, db, people["aud"])
    assert client.get(f"/api/v1/systems/{s.id}/score").status_code == 200


def test_rollup_highest_rating(client, db, ats, people):
    cid, e, maria, s = ats
    _all_domains(db, people, s, ATS_DOMAINS)
    e = db.get(Engagement, e.id)
    other = db.scalar(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.reference_id == "SYS-002"))
    other.built_by = "in_house"
    low = {"3.3.02": "analytics_only", "3.3.05s": "1", "3.3.07": "no", "5.1.02": "no", "5.1.03": "no", "5.1.04": "no", "3.3.06": "no", "3.3.04": 50, "3.2.01": ["rule_based"], "3.1.10": "internal_only"}
    for code, v in low.items():
        save_response(db, people["aud"], Target(e, other), code, {"value": v, "status": "answered", "source_person_name": "A", "source_person_title": "B"}, futran=True)
    _all_domains(db, people, other, {d: 4 for d in ("governance", "data", "model", "bias", "oversight", "security", "incident", "vendor_risk")})
    sc = scoring.engagement_rollup(db, e)
    a, b = scoring.latest(db, s), scoring.latest(db, other)
    assert b.final_rating == "low" and sc.overall_rating == "high"
    assert sc.overall_maturity == pytest.approx((a.inherent * a.maturity + b.inherent * b.maturity) / (a.inherent + b.inherent), abs=0.01)
    assert db.query(EngagementScorecard).count() == 1 and e.overall_rating == "high"
