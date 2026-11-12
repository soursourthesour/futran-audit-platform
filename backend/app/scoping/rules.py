"""Mapping rules (spec §4.5): data that turns questionnaire answers into suggested line items.

A rule is a dict (the MappingRule row's live columns):

    {"code": "MR-01a", "line_code": "A-02a", "order": 10, "active": True,
     "inputs": {"all": [{"q": "SQ-C.07", "op": "between", "value": [0, 10]}]},
     "qty_formula": {"const": 1},
     "reason_template": "Because SQ-C.07 = {SQ-C.07} ({SQ-C.07.confidence})"}

Conditions: {"q": code | [codes summed], "op": eq | ne | lt | lte | gt | gte | between | in | includes | any_ticked |
unknown, "value": ...}, combined with {"all": [...]} or {"any": [...]}. An unanswered or unknown answer fails every
condition except `unknown`.

Quantities: {"const": n}; {"answer": code, "add": k, "min": m}; {"count": code, "min": m} (options ticked);
{"sum": [codes], "min": m}; {"first": [codes], "min": m} (the first one answered); {"excess_included": {"q": code,
"tiers": [[line, low, high], ...], "key": "ai_systems"}} (the answer above the included quantity of the tier's catalog
item). A quantity of zero or less, or one that cannot be worked out, proposes nothing.

Reasons: `{SQ-C.07}` is the answer as shown, `{SQ-C.07.confidence}` its confidence, `{qty}` the quantity.
"""
import re
from dataclasses import dataclass

UNKNOWN_TEXT = "unknown"


@dataclass
class Ans:
    value: object = None
    confidence: str = "confirmed"
    source: str = "rep"

    @property
    def known(self) -> bool:
        return self.confidence != "unknown" and self.value is not None and self.value != "" and self.value != []


def _num(a: Ans | None) -> float | None:
    if a is None or not a.known:
        return None
    try:
        return float(a.value)
    except (TypeError, ValueError):
        return None


def _value(answers: dict, q) -> Ans | None:
    if isinstance(q, list):  # a sum of counts
        nums = [_num(answers.get(c)) for c in q]
        if all(n is None for n in nums):
            return None
        return Ans(sum(n or 0 for n in nums))
    return answers.get(q)


def check(cond: dict, answers: dict) -> bool:
    if "all" in cond:
        return all(check(c, answers) for c in cond["all"])
    if "any" in cond:
        return any(check(c, answers) for c in cond["any"])
    a = _value(answers, cond.get("q"))
    op, want = cond.get("op"), cond.get("value")
    if op == "unknown":
        return a is not None and a.confidence == "unknown"
    if a is None or not a.known:
        return False
    v = a.value
    if op in ("eq", "ne"):
        same = str(v) == str(want)
        return same if op == "eq" else not same
    if op == "in":
        return str(v) in {str(w) for w in want or []}
    if op == "includes":
        return isinstance(v, list) and want in v
    if op == "any_ticked":
        return isinstance(v, list) and len(v) > 0
    n = _num(a) if not isinstance(cond.get("q"), list) else float(v)
    if n is None:
        if isinstance(v, list) and op in ("gte", "gt", "lte", "lt", "between", "count_between"):
            n = float(len(v))  # a ticked list compared by how many are ticked
        else:
            return False
    if op == "lt":
        return n < float(want)
    if op == "lte":
        return n <= float(want)
    if op == "gt":
        return n > float(want)
    if op == "gte":
        return n >= float(want)
    if op in ("between", "count_between"):
        lo, hi = (want or [None, None])[:2]
        return (lo is None or n >= float(lo)) and (hi is None or n <= float(hi))
    return False


def _included(item, key: str) -> float | None:
    inc = getattr(item, "included_quantities", None) if item is not None else None
    if isinstance(inc, dict) and inc.get(key) is not None:
        try:
            return float(inc[key])
        except (TypeError, ValueError):
            return None
    return None


def quantity(formula: dict, answers: dict, catalog: dict | None = None) -> int | None:
    lo = formula.get("min")
    if "const" in formula:
        return int(formula["const"])
    n: float | None = None
    if "answer" in formula:
        n = _num(answers.get(formula["answer"]))
        if n is not None:
            n += float(formula.get("add", 0))
    elif "count" in formula:
        a = answers.get(formula["count"])
        n = float(len(a.value)) if a is not None and a.known and isinstance(a.value, list) else 0.0
    elif "sum" in formula:
        s = _value(answers, list(formula["sum"]))
        n = _num(s)
    elif "first" in formula:
        for c in formula["first"]:
            n = _num(answers.get(c))
            if n is not None:
                break
    elif "excess_included" in formula:
        spec = formula["excess_included"]
        total = _num(answers.get(spec["q"]))
        if total is None or not catalog:
            return None
        for line, low, high in spec.get("tiers", []):
            if (low is None or total >= low) and (high is None or total <= high):
                inc = _included(catalog.get(line), spec.get("key", "ai_systems"))
                return int(total - inc) if inc is not None and total > inc else None
        return None
    if n is None:
        n = float(lo) if lo is not None else None
    elif lo is not None:
        n = max(n, float(lo))
    return int(n) if n is not None else None


def show(code: str, a: Ans | None, labels: dict) -> str:
    if a is None or not a.known:
        return UNKNOWN_TEXT if a is not None and a.confidence == "unknown" else "not answered"
    names = labels.get(code, {})
    if isinstance(a.value, list):
        return ", ".join(names.get(v, str(v)) for v in a.value) or "none"
    if isinstance(a.value, float) and a.value.is_integer():
        return f"{int(a.value):,}"
    if isinstance(a.value, int):
        return f"{a.value:,}"
    return names.get(str(a.value), str(a.value))


def reason(template: str, answers: dict, labels: dict, qty: int | None) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key == "qty":
            return str(qty if qty is not None else "")
        if key.endswith(".confidence"):
            a = answers.get(key[: -len(".confidence")])
            return a.confidence if a is not None else "not answered"
        if key.endswith(".count"):
            a = answers.get(key[: -len(".count")])
            return str(len(a.value)) if a is not None and isinstance(a.value, list) else "0"
        return show(key, answers.get(key), labels)

    return re.sub(r"\{([A-Za-z0-9.\-]+)\}", sub, template or "")


def question_codes(rule: dict) -> set[str]:
    out: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("q", "answer", "count") and isinstance(v, str):
                    out.add(v)
                elif k in ("q", "sum", "first") and isinstance(v, list):
                    out.update(x for x in v if isinstance(x, str))
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(rule.get("inputs") or {})
    walk(rule.get("qty_formula") or {})
    out.update(re.findall(r"\{(SQ-[A-Z]+\.\d+)", rule.get("reason_template") or ""))
    return out


def evaluate(defs: list[dict], answers: dict, *, labels: dict | None = None, catalog: dict | None = None) -> list[dict]:
    """The lines the active, approved rules propose, in rule order; one line per line code (the first rule wins)."""
    labels = labels or {}
    out: list[dict] = []
    seen: set[str] = set()
    for d in sorted(defs, key=lambda r: (r.get("order", 0), r["code"])):
        if not d.get("active", True) or d.get("status", "approved") != "approved" or d["line_code"] in seen:
            continue
        if not check(d.get("inputs") or {"all": []}, answers):
            continue
        qty = quantity(d.get("qty_formula") or {"const": 1}, answers, catalog)
        if qty is None or qty <= 0:
            continue
        seen.add(d["line_code"])
        out.append({"code": d["line_code"], "qty": qty, "reason": reason(d.get("reason_template", ""), answers, labels, qty), "rule_code": d["code"]})
    return out


# ---- the rules seeded in v1 (spec §4.5). Band limits not given by the spec or the designs carry a note.
def _r(code, line, inputs, qty, why, note=None) -> dict:
    return {"code": code, "line_code": line, "inputs": inputs, "qty_formula": qty, "reason_template": why, "note": note}


def _q(q, op, value=None) -> dict:
    return {"q": q, "op": op, "value": value}


ONE = {"const": 1}
C07 = "Because SQ-C.07 = {SQ-C.07} ({SQ-C.07.confidence})"
AGENTS = ["SQ-G.01", "SQ-G.02"]
THIN = {"all": [_q("SQ-D.06", "in", ["little", "none"])]}
NYC = [_q("SQ-D.04", "eq", "yes")]

SEED: list[dict] = [
    _r("MR-01a", "A-02a", {"all": [_q("SQ-C.07", "between", [0, 10])]}, ONE, C07),
    _r("MR-01b", "A-02b", {"all": [_q("SQ-C.07", "between", [11, 50])]}, ONE, C07),
    _r("MR-01c", "A-02c", {"all": [_q("SQ-C.07", "gt", 50)]}, ONE, C07),
    _r("MR-02", "A-03", {"all": [_q("SQ-C.07", "gte", 1)]},
       {"excess_included": {"q": "SQ-C.07", "tiers": [["A-02a", 0, 10], ["A-02b", 11, 50], ["A-02c", 51, None]], "key": "ai_systems"}},
       "SQ-C.07 = {SQ-C.07}: {qty} above the systems the audit tier includes",
       "Reads the tier's included AI systems from the price list (included quantities, key ai_systems)."),
    _r("MR-03", "A-05", {"any": [_q("SQ-C.10", "in", ["partial", "none"]), _q("SQ-C.07", "unknown")]}, {"count": "SQ-C.11", "min": 1},
       "Inventory: {SQ-C.10}; AI systems: {SQ-C.07}; {SQ-C.11.count} sources ticked ({SQ-C.11})"),
    _r("MR-04a", "A-06a", {"all": [_q("SQ-B.01", "between", [1, 250])]}, ONE, "SQ-B.01 = {SQ-B.01} employees",
       "Bands follow the price list: A-06b is 251–1,000 employees."),
    _r("MR-04b", "A-06b", {"all": [_q("SQ-B.01", "between", [251, 1000])]}, ONE, "SQ-B.01 = {SQ-B.01} employees"),
    _r("MR-04c", "A-06c", {"all": [_q("SQ-B.01", "gt", 1000)]}, ONE, "SQ-B.01 = {SQ-B.01} employees"),
    _r("MR-05", "A-04", {"all": [_q("SQ-B.06", "gt", 1)]}, {"answer": "SQ-B.06", "add": -1}, "SQ-B.06 = {SQ-B.06} states; the audit includes 1"),
    _r("MR-06a", "A-08a", {"all": [_q("SQ-C.08", "between", [1, 9])]}, {"answer": "SQ-C.08"}, "SQ-C.08 = {SQ-C.08} AI vendors"),
    _r("MR-06b", "A-08b", {"all": [_q("SQ-C.08", "gte", 10)]}, ONE, "SQ-C.08 = {SQ-C.08} AI vendors"),
    _r("MR-07a", "L-01", {"all": [_q("SQ-D.02", "gte", 1), *NYC]}, ONE, "SQ-D.02 = {SQ-D.02} AEDTs and hires in NYC"),
    _r("MR-07b", "L-02", {"all": [_q("SQ-D.02", "gte", 2), *NYC]}, {"answer": "SQ-D.02", "add": -1},
       "SQ-D.02 = {SQ-D.02} AEDTs; L-01 covers the first tool"),
    _r("MR-08a", "L-04", THIN, {"answer": "SQ-D.02", "min": 1}, "Hiring data: {SQ-D.06}; one per AEDT ({SQ-D.02})"),
    _r("MR-08b", "L-05", THIN, ONE, "Hiring data: {SQ-D.06}"),
    _r("MR-08c", "A-09", THIN, ONE, "Hiring data: {SQ-D.06}"),
    _r("MR-09", "L-09", {"all": [_q("SQ-D.07", "eq", "staffing")]}, {"answer": "SQ-D.08", "min": 1}, "Staffing business; SQ-D.08 = {SQ-D.08} end-clients"),
    _r("MR-10", "L-08", {"all": [_q("SQ-D.09", "any_ticked")]}, {"count": "SQ-D.09"}, "Also hires in {SQ-D.09}"),
    _r("MR-11", "A-11", {"all": [_q("SQ-E.01", "gte", 1)]}, {"answer": "SQ-E.01"}, "SQ-E.01 = {SQ-E.01} high-risk systems need an impact assessment"),
    *[_r(f"MR-12{letter}", f"M-01{letter}", {"all": [_q("SQ-F.01", "eq", plan), _q("SQ-C.07", "between", band)]}, ONE,
         "Interested in {SQ-F.01}; SQ-C.07 = {SQ-C.07} systems",
         "Assumed: M-01a–c are Monitor and M-01d–f Monitor Plus, each by the audit tier (up to 10, 11–50, over 50 systems).")
      for letter, plan, band in (("a", "monitor", [0, 10]), ("b", "monitor", [11, 50]), ("c", "monitor", [51, None]),
                                 ("d", "monitor_plus", [0, 10]), ("e", "monitor_plus", [11, 50]), ("f", "monitor_plus", [51, None]))],
    _r("MR-13a", "M-03a", {"all": [_q("SQ-B.07", "count_between", [1, 3])]}, ONE, "{SQ-B.07.count} jurisdictions ticked ({SQ-B.07})",
       "M-03a is 1–3 states (price list). The M-03b and M-03c bands (4–10, over 10) are placeholders until the price list is loaded."),
    _r("MR-13b", "M-03b", {"all": [_q("SQ-B.07", "count_between", [4, 10])]}, ONE, "{SQ-B.07.count} jurisdictions ticked ({SQ-B.07})",
       "Placeholder band (4–10 states): check against the price list."),
    _r("MR-13c", "M-03c", {"all": [_q("SQ-B.07", "count_between", [11, None])]}, ONE, "{SQ-B.07.count} jurisdictions ticked ({SQ-B.07})",
       "Placeholder band (over 10 states): check against the price list."),
    _r("MR-14a", "M-06c", {"all": [_q("SQ-F.02", "eq", "7")]}, ONE, "Records kept {SQ-F.02}"),
    _r("MR-14b", "M-06d", {"all": [_q("SQ-F.02", "eq", "10")]}, ONE, "Records kept {SQ-F.02}"),
    _r("MR-15a", "AA-01", {"all": [_q(AGENTS, "gte", 1)]}, {"sum": AGENTS}, "{SQ-G.01} agents live and {SQ-G.02} planned"),
    _r("MR-15b", "AA-02", {"all": [_q(AGENTS, "gte", 1)]}, {"sum": AGENTS}, "{SQ-G.01} agents live and {SQ-G.02} planned"),
    _r("MR-15c", "AW-02a", {"all": [_q(AGENTS, "gte", 1), _q("SQ-G.03", "in", ["suggest", "approve"])]}, {"sum": AGENTS},
       "{SQ-G.01} live and {SQ-G.02} planned; autonomy: {SQ-G.03}", "AW-02a for agents a person approves; AW-02b for agents that act on their own."),
    _r("MR-15d", "AW-02b", {"all": [_q(AGENTS, "gte", 1), _q("SQ-G.03", "eq", "autonomous")]}, {"sum": AGENTS},
       "{SQ-G.01} live and {SQ-G.02} planned; autonomy: {SQ-G.03}"),
    _r("MR-15e", "AW-04", {"all": [_q(AGENTS, "gte", 1)]}, {"sum": AGENTS}, "{SQ-G.01} agents live and {SQ-G.02} planned"),
    _r("MR-16", "AW-01", {"all": [_q("SQ-G.04", "any_ticked")]}, ONE, "Agents can: {SQ-G.04}"),
    _r("MR-17", "X-04", {"any": [_q("SQ-H.01", "eq", "yes"), _q("SQ-C.12", "includes", "m365_copilot")]}, ONE,
       "Copilot rollout: {SQ-H.01}; embedded AI includes {SQ-C.12}"),
    _r("MR-18", "X-03", {"all": [_q("SQ-B.08", "eq", "yes"), _q("SQ-C.09", "gte", 1)]}, {"answer": "SQ-C.09"},
       "EU exposure and SQ-C.09 = {SQ-C.09} high-risk systems", "Counts every high-risk system; the starter bank has no separate EU count."),
    _r("MR-19", "X-05", {"all": [_q("SQ-A.01", "eq", "ma")]}, ONE, "Trigger: {SQ-A.01}"),
]


def seed_definitions() -> list[dict]:
    """Fresh copies of the seeded rules, in order, as live rule dicts."""
    import copy

    return [{**copy.deepcopy(r), "order": (i + 1) * 10, "active": True, "status": "approved"} for i, r in enumerate(SEED)]
