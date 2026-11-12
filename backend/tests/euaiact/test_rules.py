"""G-08 rules: deadlines come from the data file (and match spec v0.4 §5 B6), applicable articles follow role and
classification, and the FRIA applies only where Art. 27(1) puts it."""
from datetime import date

from app.euaiact import rules


def test_deadlines_are_the_spec_dates_and_live_in_the_data_file():
    assert rules.deadline_for("high_risk_annex_iii", today=date(2026, 11, 11))["date"] == date(2027, 12, 2)
    assert rules.deadline_for("high_risk_annex_i", today=date(2026, 11, 11))["date"] == date(2028, 8, 2)
    assert "2026/1744" in rules.deadline_for("high_risk_annex_iii")["source"]
    d = rules.deadline_for("transparency", today=date(2026, 11, 11))
    assert d["in_force"] is True and d["label"] == "In force"
    assert rules.deadline_for("high_risk_annex_iii", today=date(2026, 11, 11))["label"] == "2 Dec 2027"
    assert rules.deadline_for(None)["date"] is None


def test_dates_change_with_the_data(monkeypatch):
    data = rules.data()
    patched = dict(data, deadlines=dict(data["deadlines"], high_risk_annex_iii={"date": date(2028, 1, 15), "source": "test"}))
    monkeypatch.setattr(rules, "data", lambda: patched)
    assert rules.deadline_for("high_risk_annex_iii", today=date(2026, 11, 11))["date"] == date(2028, 1, 15)


def _keys(role, cls, **kw):
    return [o["key"] for o in rules.applicable(role, cls, **kw)]


def test_provider_of_annex_iii_system_has_the_provider_duties():
    keys = _keys("provider", "high_risk_annex_iii")
    assert keys == ["art4", "art9", "art10", "art11", "art12", "art13", "art14", "art15", "art17", "art43", "art47", "art49", "art72", "art73"]
    # a provider that also uses it adds the deployer duties; the FRIA only where Art. 27 applies
    both = _keys("provider", "high_risk_annex_iii", also_deployer=True, fria=True)
    assert {"art26_1", "art26_2", "art27", "art86"} <= set(both) and both.count("art4") == 1


def test_deployer_importer_distributor_and_lighter_classes():
    assert _keys("deployer", "high_risk_annex_iii") == ["art4", "art26_1", "art26_2", "art26_5", "art26_6", "art26_7", "art26_11", "art86", "art73"]
    assert "art27" in _keys("deployer", "high_risk_annex_iii", fria=True)
    assert _keys("importer", "high_risk_annex_i") == ["art23"]
    assert _keys("distributor", "high_risk_annex_iii") == ["art24"]
    assert _keys("deployer", "transparency") == ["art4", "art50_3"]
    assert _keys("deployer", "minimal") == ["art4"]
    assert _keys("provider", "gpai") == ["art4", "art50_1", "art53"]
    assert _keys("deployer", "prohibited") == ["art4", "art5"]
    assert _keys(None, None) == []


def test_fria_required_for_deployers_where_article_27_says():
    assert rules.fria_required("deployer", False, "high_risk_annex_iii", "credit", False)
    assert rules.fria_required("deployer", False, "high_risk_annex_iii", "insurance", False)
    assert not rules.fria_required("deployer", False, "high_risk_annex_iii", "employment", False)
    assert rules.fria_required("deployer", False, "high_risk_annex_iii", "employment", True)  # public body or public service
    assert not rules.fria_required("deployer", False, "high_risk_annex_iii", "critical_infrastructure", True)
    assert not rules.fria_required("provider", False, "high_risk_annex_iii", "credit", False)
    assert rules.fria_required("provider", True, "high_risk_annex_iii", "credit", False)  # also deploys it
    assert not rules.fria_required("deployer", False, "high_risk_annex_i", "credit", False)


def test_article_refs_and_cover():
    assert rules.article_refs("EU AI Act Art. 4 (as amended by Reg. (EU) 2026/1744)") == ["4"]
    assert rules.article_refs("EU AI Act Art. 14, 26(2)") == ["14", "26(2)"]
    assert rules.article_refs("EU AI Act Art. 50(3)–(4)") == ["50(3)"]
    assert rules.article_refs("EU AI Act Art. 11(1), Annex IV") == ["11(1)"]
    assert rules.covers("73(2)", "73") and rules.covers("26", "26(1)") and rules.covers("26(1)", "26(1)")
    assert not rules.covers("14(4)(e)", "14(1)") and not rules.covers("26(1)", "26(2)") and not rules.covers("1", "10")
