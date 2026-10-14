import pytest
import yaml

from app.scoring import engine
from app.scoring.engine import FactorInputs, Methodology

M = Methodology.from_yaml(yaml.safe_load(open("seeds/risk_methodology_v1.yaml")))
ATS = {"decision_type": 3, "consequence": 4, "protected_classes": 5, "data_sensitivity": 3, "regulated_context": 5, "volume": 3, "system_type": 3, "exposure": 5}
ATS_DOMAINS = {"governance": 3, "data": 2, "model": 2, "bias": 1, "oversight": 3, "security": 3, "incident": 2, "vendor_risk": 2}


def test_worked_example_ats():
    inherent, rows = engine.inherent(FactorInputs(ATS), M)
    assert inherent == 76.0 and [r.points for r in rows] == [12, 16, 15, 9, 10, 6, 3, 5]
    m = engine.maturity(ATS_DOMAINS, "vendor", "full", M)
    assert m == 2.25
    assert engine.control_effectiveness(m) == 0.3125
    residual = engine.residual(inherent, m, M)
    assert residual == 58.2 and engine.band(residual, M) == "high"
    kos = engine.knockouts({"6.2.01": "no", "3.3.07": "yes", "5.1a.05": "high"}, M)
    assert [k.code for k in kos] == ["no_bias_testing", "null_compliance_high"] and {k.force for k in kos} == {"high"}
    assert engine.final_rating("high", kos, eu_prohibited=False) == "high"


def test_eu_high_floor_70():
    low = {k: 1 for k in ATS}
    inherent, _ = engine.inherent(FactorInputs(low), M)
    assert inherent == 20.0
    assert engine.inherent(FactorInputs(low, eu_classification="high"), M)[0] == 70.0
    assert engine.inherent(FactorInputs(ATS, eu_classification="high"), M)[0] == 76.0


def test_prohibited_forces_critical():
    kos = engine.knockouts({"3.3.08": "prohibited"}, M)
    assert [k.code for k in kos] == ["eu_prohibited"]
    assert engine.final_rating("low", kos, eu_prohibited=True) == "critical"
    assert engine.final_rating("low", [], eu_prohibited=True) == "critical"


def test_phi_vendor_no_baa_critical():
    kos = engine.knockouts({"5.3.02": "baa_not_in_place"}, M)
    assert [(k.code, k.force) for k in kos] == [("phi_vendor_no_baa", "critical")]
    assert engine.final_rating("medium", kos, eu_prohibited=False) == "critical"


def test_light_rescaled_weights_sum_to_1():
    for build in ("in_house", "vendor", "open_source_customized", "hybrid"):
        w = engine.domain_weights(build, "light", M)
        assert set(w) == {"governance", "data", "oversight", "vendor_risk"}
        assert sum(w.values()) == pytest.approx(1.0)
        assert sum(engine.domain_weights(build, "full", M).values()) == pytest.approx(1.0)
    assert engine.domain_weights("hybrid", "full", M) == engine.domain_weights("in_house", "full", M)
    # in-house light: four domains of 0.15, 0.15, 0.15, 0.10 → rescaled over 0.55
    w = engine.domain_weights("in_house", "light", M)
    assert w["vendor_risk"] == pytest.approx(0.10 / 0.55)
    assert engine.maturity({"governance": 3, "data": 3, "oversight": 3, "vendor_risk": 3}, "in_house", "light", M) == 3.0


def test_proposed_domain_minus_open_findings_min_1():
    assert [engine.proposed_domain_score(p, 0) for p in (0, 19.9, 20, 39, 40, 59, 60, 79, 80, 100)] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert engine.proposed_domain_score(85, 1) == 4
    assert engine.proposed_domain_score(85, 9) == 1
    assert engine.proposed_domain_score(10, 2) == 1


def test_factor_scores_from_answers():
    answers = {"3.3.02": "human_assisted", "3.3.05s": "4", "3.3.07": "yes", "5.1.02": "no", "5.1.03": "yes", "5.1.04": "no", "3.3.06": "yes", "3.3.04": 2000, "3.2.01": ["ml", "nlp"], "3.1.10": "client_facing_decision"}
    f = engine.factor_scores(answers, M)
    assert f == ATS
    assert engine.factor_scores({"3.2.01": ["rule_based", "agentic"], "3.3.04": 100000}, M)["system_type"] == 5
    assert engine.factor_scores({"3.3.04": 100000}, M)["volume"] == 5
    assert engine.factor_scores({}, M)["data_sensitivity"] is None
    inherent, rows = engine.inherent(FactorInputs({**ATS, "volume": None}), M)
    assert inherent is None and [r.key for r in rows if r.score is None] == ["volume"]


def test_residual_bands():
    assert [engine.band(x, M) for x in (75, 74.9, 50, 49.9, 25, 24.9, 0)] == ["critical", "high", "high", "medium", "medium", "low", "low"]
    assert engine.residual(100, 5, M) == 25.0 and engine.residual(100, 1, M) == 100.0
