"""Spec §4.5: the seeded mapping rules turn answers into suggested lines with a quantity and a reason."""
from app.scoping import rules
from app.scoping.bank import STARTER
from app.scoping.rules import Ans

LABELS = {q["code"]: {o["value"]: o["label"] for o in q.get("options", [])} for q in STARTER}


def run(answers: dict, catalog=None):
    a = {k: (v if isinstance(v, Ans) else Ans(v)) for k, v in answers.items()}
    return {line["code"]: line for line in rules.evaluate(rules.seed_definitions(), a, labels=LABELS, catalog=catalog)}


def test_every_spec_row_is_seeded_and_every_question_code_it_reads_is_in_the_bank():
    defs = rules.seed_definitions()
    assert len({d["code"].rstrip("abcdef") for d in defs}) == 19  # the 19 rows of spec §4.5
    bank = {q["code"] for q in STARTER}
    for d in defs:
        assert rules.question_codes(d) <= bank, d["code"]


def test_audit_tier_follows_total_ai_systems_with_the_answer_in_the_reason():
    assert run({"SQ-C.07": Ans(6, "estimate")})["A-02a"]["reason"] == "Because SQ-C.07 = 6 (estimate)"
    assert "A-02b" in run({"SQ-C.07": 12}) and "A-02a" not in run({"SQ-C.07": 12})
    assert "A-02c" in run({"SQ-C.07": 51}) and "A-02b" not in run({"SQ-C.07": 51})


def test_unknown_system_count_adds_a_discovery_sweep_sized_by_sources_ticked():
    lines = run({"SQ-C.07": Ans(None, "unknown"), "SQ-C.11": ["okta_entra", "m365", "expense"]})
    assert lines["A-05"]["qty"] == 3 and not any(c.startswith("A-02") for c in lines)
    assert "Okta / Entra ID, Microsoft 365, Expense export" in lines["A-05"]["reason"]
    # partial inventory with nothing ticked still proposes one source
    assert run({"SQ-C.10": "partial"})["A-05"]["qty"] == 1
    assert "A-05" not in run({"SQ-C.10": "full", "SQ-C.07": 4})


def test_quantity_rules_for_states_vendors_and_attestation_bands():
    lines = run({"SQ-B.06": 3, "SQ-C.08": 4, "SQ-B.01": 600})
    assert lines["A-04"]["qty"] == 2 and lines["A-08a"]["qty"] == 4 and lines["A-06b"]["qty"] == 1
    assert "A-04" not in run({"SQ-B.06": 1})
    assert run({"SQ-C.08": 12})["A-08b"]["qty"] == 1
    assert "A-06a" in run({"SQ-B.01": 250}) and "A-06c" in run({"SQ-B.01": 1001})


def test_ll144_lines_need_aedts_and_nyc():
    lines = run({"SQ-D.02": 2, "SQ-D.04": "yes"})
    assert lines["L-01"]["qty"] == 1 and lines["L-02"]["qty"] == 1  # 1 + (AEDTs - 1)
    assert "L-01" not in run({"SQ-D.02": 2, "SQ-D.04": "no"})
    assert "L-02" not in run({"SQ-D.02": 1, "SQ-D.04": "yes"})
    thin = run({"SQ-D.02": 2, "SQ-D.06": "little"})
    assert thin["L-04"]["qty"] == 2 and thin["L-05"]["qty"] == 1 and thin["A-09"]["qty"] == 1
    assert run({"SQ-D.07": "staffing", "SQ-D.08": 5})["L-09"]["qty"] == 5
    assert run({"SQ-D.09": ["IL", "CO"]})["L-08"]["qty"] == 2


def test_monitor_plan_alert_packs_retention_agents_and_extras():
    assert "M-01b" in run({"SQ-F.01": "monitor", "SQ-C.07": 20})
    assert "M-01d" in run({"SQ-F.01": "monitor_plus", "SQ-C.07": 8})
    assert "M-01a" not in run({"SQ-F.01": "no", "SQ-C.07": 8})
    assert "M-03a" in run({"SQ-B.07": ["NY", "NJ"]})
    assert "M-06c" in run({"SQ-F.02": "7"}) and "M-06d" in run({"SQ-F.02": "10"})
    agents = run({"SQ-G.01": 2, "SQ-G.02": 3, "SQ-G.03": "autonomous", "SQ-G.04": ["update_records"]})
    assert agents["AA-01"]["qty"] == 5 and agents["AW-02b"]["qty"] == 5 and "AW-02a" not in agents and agents["AW-01"]["qty"] == 1
    assert "X-04" in run({"SQ-C.12": ["m365_copilot"]}) and "X-04" in run({"SQ-H.01": "yes"})
    assert run({"SQ-B.08": "yes", "SQ-C.09": 2})["X-03"]["qty"] == 2 and "X-03" not in run({"SQ-B.08": "no", "SQ-C.09": 2})
    assert "X-05" in run({"SQ-A.01": "ma"})
    assert run({"SQ-E.01": 3})["A-11"]["qty"] == 3


def test_extra_systems_above_the_tier_included_count_need_the_catalog():
    class Item:
        def __init__(self, inc):
            self.included_quantities = inc

    assert "A-03" not in run({"SQ-C.07": 30})  # no catalog: nothing to compare against
    assert run({"SQ-C.07": 30}, catalog={"A-02b": Item({"ai_systems": 25})})["A-03"]["qty"] == 5


def test_inactive_and_pending_rules_do_not_run():
    defs = rules.seed_definitions()
    for d in defs:
        if d["line_code"] == "X-05":
            d["active"] = False
    assert not any(line["code"] == "X-05" for line in rules.evaluate(defs, {"SQ-A.01": Ans("ma")}, labels=LABELS))
