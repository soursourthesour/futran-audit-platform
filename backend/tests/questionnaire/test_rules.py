from datetime import date

from app.questionnaire.rules import EngagementFacts, SystemContext, evaluate_finding, is_applicable

SYS_VENDOR = SystemContext(built_by="vendor", depth="full")
SYS_INHOUSE = SystemContext(built_by="in_house", depth="full")


def facts(**kw):
    return EngagementFacts(**kw)


def test_none_rule_always_applies():
    assert is_applicable(None, {}, SYS_VENDOR, facts())


def test_hipaa_applicability_hidden_without_health():
    rule = {"any": [{"engagement": "hipaa_in_scope", "eq": True}, {"q": "5.1.02", "eq": "yes"}]}
    assert not is_applicable(rule, {"5.1.02": "no"}, SYS_INHOUSE, facts())
    assert is_applicable(rule, {"5.1.02": "yes"}, SYS_INHOUSE, facts())
    assert is_applicable(rule, {}, SYS_INHOUSE, facts(hipaa_in_scope=True))


def test_contains_for_multi_choice():
    rule = {"q": "3.2.01", "contains": "genai_llm"}
    assert is_applicable(rule, {"3.2.01": ["ml", "genai_llm"]}, SYS_INHOUSE, facts())
    assert not is_applicable(rule, {"3.2.01": ["ml"]}, SYS_INHOUSE, facts())


def test_engagement_in_and_not():
    assert is_applicable({"engagement": "industry", "in": ["banking"]}, {}, SYS_INHOUSE, facts(industry="banking"))
    assert not is_applicable({"not": {"engagement": "eu_in_scope", "eq": True}}, {}, SYS_INHOUSE, facts(eu_in_scope=True))


def test_system_rule():
    assert is_applicable({"system": "built_by", "in": ["vendor", "hybrid"]}, {}, SYS_VENDOR, facts())
    assert not is_applicable({"system": "depth", "eq": "light"}, {}, SYS_VENDOR, facts())


def test_finding_in_rule():
    rule = {"when": {"in": ["no"]}, "severity": "high", "title": "No encryption"}
    d = evaluate_finding(rule, "no", "answered", {}, SYS_INHOUSE, facts())
    assert d.severity == "high" and d.title == "No encryption"
    assert evaluate_finding(rule, "yes", "answered", {}, SYS_INHOUSE, facts()) is None


def test_not_yet_in_place_triggers_finding():
    rule = {"when": {"in": ["no"]}, "severity": "high", "title": "No bias testing"}
    d = evaluate_finding(rule, "yes", "not_yet_in_place", {}, SYS_INHOUSE, facts())
    assert d is not None and d.not_yet_in_place


def test_na_status_never_triggers():
    rule = {"when": {"in": ["no"]}, "severity": "high", "title": "x"}
    assert evaluate_finding(rule, None, "na", {}, SYS_INHOUSE, facts()) is None


def test_null_compliance_high_rule():
    rule = {"when": {"in": ["high"]}, "severity": "high", "title": "Null compliance", "null_compliance": True}
    d = evaluate_finding(rule, "high", "answered", {}, SYS_INHOUSE, facts())
    assert d.severity == "high" and d.null_compliance is True


def test_lt_rule_for_disparate_impact():
    rule = {"when": {"lt": 0.8}, "severity": "high", "title": "DIR"}
    assert evaluate_finding(rule, 0.72, "answered", {}, SYS_INHOUSE, facts())
    assert evaluate_finding(rule, "0.85", "answered", {}, SYS_INHOUSE, facts()) is None


def test_older_than_months():
    rule = {"when": {"older_than_months": 12}, "severity": "medium", "title": "Old pen test"}
    assert evaluate_finding(rule, "2025-01-15", "answered", {}, SYS_INHOUSE, facts(), today=date(2026, 10, 13))
    assert evaluate_finding(rule, "2026-06-01", "answered", {}, SYS_INHOUSE, facts(), today=date(2026, 10, 13)) is None


def test_unless_and_if_conditions():
    rule = {"when": {"in": ["no"]}, "severity": "high", "title": "No bias testing", "unless": {"q": "3.3.07", "eq": "no"}}
    assert evaluate_finding(rule, "no", "answered", {"3.3.07": "no"}, SYS_INHOUSE, facts()) is None
    assert evaluate_finding(rule, "no", "answered", {"3.3.07": "yes"}, SYS_INHOUSE, facts())
    rule2 = {"when": {"in": ["no"]}, "severity": "high", "title": "Validation", "if": {"q": "6.3.01", "eq": "yes"}}
    assert evaluate_finding(rule2, "no", "answered", {"6.3.01": "no"}, SYS_INHOUSE, facts()) is None
    assert evaluate_finding(rule2, "no", "answered", {"6.3.01": "yes"}, SYS_INHOUSE, facts())
