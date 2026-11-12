"""SM-15 totals and the §4.7 guardrail warnings, checked against the Estimator design (Governed package, A-02a at $13,500)."""
import pytest

from app.catalog import guardrails, pricing

GOVERNED = [("A-02a", 1, 13500), ("A-05", 3, None), ("A-06b", 1, None), ("A-08a", 3, None), ("M-07a", 2, None), ("M-01a", 1, None), ("M-03a", 1, None), ("M-06a", 1, None)]


@pytest.fixture
def lines(db, seeded):
    return pricing.price_lines(db, [{"code": c, "qty": q, "edited_price": p} for c, q, p in GOVERNED])


def test_line_values_follow_the_design(lines):
    by = {ln["code"]: ln for ln in lines}
    assert by["A-02a"]["unit_price_used"] == 13500 and by["A-02a"]["edited"] is True and by["A-02a"]["value_difference"] == -1500
    assert by["A-05"]["line_value"] == 4500 and by["A-05"]["edited"] is False
    assert by["M-03a"]["line_value"] == 16800 and by["M-03a"]["periods_per_year"] == 4
    assert by["A-05"]["assumption"].startswith("Delivered by Futran consultants")
    assert by["A-02a"]["deliverables"].startswith("AI inventory")


def test_totals_match_the_design(lines):
    t = pricing.totals(lines, 0)
    assert t == {"one_time": 39500, "recurring_y1": 31200, "discount": 0, "y1_total": 70700, "arr": 31200}


def test_discount_applies_to_recurring_only(lines):
    t = pricing.totals(lines, 10)
    assert t["discount"] == 3120 and t["y1_total"] == 39500 + 31200 - 3120 and t["arr"] == 31200 - 3120


def test_percent_items_are_computed_against_the_lines_they_apply_to():
    lines = [
        {"code": "A-02a", "basis": "$", "billing": "one_time", "qty": 1, "periods_per_year": 1, "unit_price_used": 15000, "product": "Audit"},
        {"code": "M-01a", "basis": "$", "billing": "annual", "qty": 1, "periods_per_year": 1, "unit_price_used": 12000, "product": "Monitor"},
        {"code": "T-02", "basis": "%", "billing": "annual", "qty": 1, "periods_per_year": 1, "unit_price_used": 10, "applies_to": ["Monitor"], "product": "Terms"},
        {"code": "A-14", "basis": "%", "billing": "one_time", "qty": 1, "periods_per_year": 1, "unit_price_used": 50, "applies_to": ["A-02a"], "product": "Audit"},
    ]
    pricing.compute(lines)
    by = {ln["code"]: ln for ln in lines}
    assert by["T-02"]["line_value"] == 1200 and by["A-14"]["line_value"] == 7500
    assert pricing.totals(lines, 0)["recurring_y1"] == 13200


def test_proposed_prices_need_the_pricing_approver(lines):
    got = guardrails.needed_approvals(lines, 0, {})
    p1 = next(g for g in got if g["rule"] == "P-1")
    assert p1["approver_role"] == "pricing_approver" and p1["codes"] == ["A-02a", "A-05", "A-06b", "M-01a", "M-06a"]
    assert not [g for g in got if g["rule"] in ("P-4", "P-5")]  # A-02a at $13,500 is inside $12,000–18,000
    p8 = next(g for g in got if g["rule"] == "P-8")
    assert p8["kind"] == "note" and p8["codes"] == ["A-05"]
    assert "1 line edited, still inside the Low–High range" in guardrails.summary(lines, got)


@pytest.mark.parametrize("discount,rule,role", [(10, "P-2", "sales_manager"), (15, "P-2", "sales_manager"), (15.5, "P-3", "pricing_approver")])
def test_discount_rules(lines, discount, rule, role):
    got = {g["rule"]: g for g in guardrails.needed_approvals(lines, discount, {})}
    assert got[rule]["approver_role"] == role
    assert ("P-3" in got) == (rule == "P-3") and ("P-2" in got) == (rule == "P-2")


def test_the_manager_limit_is_a_parameter(lines):
    got = {g["rule"] for g in guardrails.needed_approvals(lines, 12, {}, discount_limit_pct=10)}
    assert "P-3" in got and "P-2" not in got


def test_below_low_above_high_and_one_time_discount(db, seeded):
    lines = pricing.price_lines(db, [{"code": "A-02a", "qty": 1, "edited_price": 11000}, {"code": "L-01", "qty": 1, "edited_price": 13000}])
    got = {g["rule"]: g for g in guardrails.needed_approvals(lines, 0, {"discount_one_time_pct": 5})}
    assert got["P-4"]["codes"] == ["A-02a"] and got["P-4"]["approver_role"] == "pricing_approver"
    assert got["P-5"]["codes"] == ["L-01"] and got["P-5"]["approver_role"] == "sales_manager"
    assert got["P-3"]["approver_role"] == "pricing_approver"


@pytest.mark.parametrize("terms", [{"payment_days": 45}, {"custom_liability": "Cap at 2x fees"}, {"sla_credits": True}])
def test_custom_terms(lines, terms):
    got = {g["rule"]: g for g in guardrails.needed_approvals(lines, 0, terms)}
    assert got["P-6"]["approver_role"] == "pricing_approver"


def test_payment_30_days_is_standard(lines):
    assert "P-6" not in {g["rule"] for g in guardrails.needed_approvals(lines, 0, {"payment_days": 30})}


def test_roadmap_lines_are_blocked():
    got = guardrails.needed_approvals([{"code": "M-09", "sellable_status": "roadmap", "price_status": "proposed", "unit_price_used": 4800, "low": 3600, "high": 6000}], 0, {})
    assert [(g["rule"], g["kind"]) for g in got] == [("P-7", "blocked")]
