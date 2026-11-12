"""SM-14 flags a mapping rule (R3's MappingRule) that points to a retired item or a code not on the price list."""
import pytest

from app.catalog import service


def test_rules_pointing_to_retired_or_missing_items_are_flagged(db, seeded, staff):
    models = pytest.importorskip("app.scoping.models")
    for code, line in (("MR-1", "A-02a"), ("MR-2", "M-07a"), ("MR-3", "Z-99")):
        db.add(models.MappingRule(code=code, line_code=line, inputs={}, qty_formula={}, reason_template="because"))
    db.flush()
    assert {f["rule_code"]: f["problem"] for f in service.rule_flags(db)} == {"MR-3": "Not on the price list"}
    service.retire_item(db, staff["owner"], "M-07a", reason="Replaced")
    assert {f["rule_code"]: f["problem"] for f in service.rule_flags(db)} == {"MR-2": "Retired item", "MR-3": "Not on the price list"}
