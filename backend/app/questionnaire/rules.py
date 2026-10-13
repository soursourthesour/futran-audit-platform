"""Applicability and finding rules for the question bank (pure functions, no database).

Rule grammar (JSON):
  {"q": code, "eq": v} | {"q": code, "in": [...]} | {"q": code, "contains": v} | {"q": code, "empty": true}
  {"system": "built_by"|"depth", "eq"|"in": ...}
  {"engagement": <fact name>, "eq"|"in": ...}
  {"all": [rules]} | {"any": [rules]} | {"not": rule}

Finding rules: {"when": {"in": [...]} | {"lt": n} | {"gt": n} | {"older_than_months": n},
                "severity": ..., "title": ..., "if": rule?, "unless": rule?, "null_compliance": bool?}
Golden rule 2: an answer with status `not_yet_in_place` counts as "No" — it always triggers the finding.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class SystemContext:
    built_by: str = "in_house"
    depth: str = "full"


@dataclass
class EngagementFacts:
    eu_in_scope: bool = False
    gdpr_in_scope: bool = False
    hipaa_in_scope: bool = False
    dpdp_in_scope: bool = False
    bias_audit_in_scope: bool = False
    industry: str | None = None
    extra: dict = field(default_factory=dict)

    def get(self, name: str):
        if hasattr(self, name) and name != "extra":
            return getattr(self, name)
        return self.extra.get(name)


def _compare(value: Any, rule: dict) -> bool:
    if "eq" in rule:
        return value == rule["eq"]
    if "in" in rule:
        return value in rule["in"]
    if "contains" in rule:
        return isinstance(value, (list, tuple, set)) and rule["contains"] in value
    if "empty" in rule:
        empty = value in (None, "", [], {})
        return empty if rule["empty"] else not empty
    return bool(value)


def is_applicable(rule: dict | None, answers: dict[str, Any], system: SystemContext, facts: EngagementFacts) -> bool:
    if not rule:
        return True
    if "all" in rule:
        return all(is_applicable(r, answers, system, facts) for r in rule["all"])
    if "any" in rule:
        return any(is_applicable(r, answers, system, facts) for r in rule["any"])
    if "not" in rule:
        return not is_applicable(rule["not"], answers, system, facts)
    if "q" in rule:
        return _compare(answers.get(rule["q"]), rule)
    if "system" in rule:
        return _compare(getattr(system, rule["system"], None), rule)
    if "engagement" in rule:
        return _compare(facts.get(rule["engagement"]), rule)
    raise ValueError(f"Unknown rule: {rule}")


@dataclass
class FindingDraft:
    severity: str
    title: str
    not_yet_in_place: bool = False
    null_compliance: bool = False


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month) - (1 if later.day < earlier.day else 0)


def _matches(when: dict, value: Any, today: date) -> bool:
    if "in" in when:
        return value in when["in"]
    if "lt" in when or "gt" in when:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return False
        return num < when["lt"] if "lt" in when else num > when["gt"]
    if "older_than_months" in when:
        if not value:
            return False
        try:
            d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        except ValueError:
            return False
        return _months_between(d, today) >= when["older_than_months"]
    return False


def evaluate_finding(
    rule: dict | None,
    value: Any,
    status: str,
    answers: dict[str, Any],
    system: SystemContext,
    facts: EngagementFacts,
    today: date | None = None,
) -> FindingDraft | None:
    """Return a draft finding when the answer matches the rule (spec §18.1 golden rules 2 and 6)."""
    if not rule or status in ("na", "unanswered"):
        return None
    if rule.get("if") and not is_applicable(rule["if"], answers, system, facts):
        return None
    if rule.get("unless") and is_applicable(rule["unless"], answers, system, facts):
        return None
    nyip = status == "not_yet_in_place"
    if nyip or _matches(rule["when"], value, today or date.today()):
        return FindingDraft(severity=rule["severity"], title=rule["title"], not_yet_in_place=nyip, null_compliance=bool(rule.get("null_compliance")))
    return None
