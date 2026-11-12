"""Which approvals a proposal built from these lines would need (spec §4.7, pricing rules P-1 to P-8).

Shared with the Proposal builder (R4): `needed_approvals(lines, discount_recurring_pct, terms)`. Saving is never
blocked by these; they say what a proposal needs before it can be sent. Independence rules (I-1 to I-4) are R4's.

Each line is a dict with: code, price_status, sellable_status, unit_price_used, low, high (as priced by
`catalog.pricing.price_line`). `terms` may hold payment_days, custom_liability, sla_credits, discount_one_time_pct.
Each result: {rule, kind ("approval" | "blocked" | "note"), approver_role, approver, codes, message}."""

DEFAULT_MANAGER_DISCOUNT_LIMIT = 15.0  # user's default for R2-Q1; the platform setting is catalog.service.settings(db)
APPROVERS = {"pricing_approver": "Pricing Approver", "sales_manager": "Sales Manager"}
STANDARD_PAYMENT_DAYS = 30


def _codes(lines, test) -> list[str]:
    return list(dict.fromkeys(ln["code"] for ln in lines if test(ln)))


def _rule(rule: str, role: str | None, codes: list[str], message: str, kind: str = "approval") -> dict:
    return {"rule": rule, "kind": kind, "approver_role": role, "approver": APPROVERS.get(role) if role else None, "codes": codes, "message": message}


def _list(codes: list[str]) -> str:
    return ", ".join(codes)


def needed_approvals(lines: list[dict], discount_recurring_pct: float | None, terms: dict | None, *,
                     discount_limit_pct: float = DEFAULT_MANAGER_DISCOUNT_LIMIT) -> list[dict]:
    terms = terms or {}
    d = float(discount_recurring_pct or 0)
    out: list[dict] = []
    priced = [ln for ln in lines if ln.get("sellable_status") != "roadmap"]

    p1 = _codes(priced, lambda ln: ln.get("price_status") == "proposed")
    if p1:
        out.append(_rule("P-1", "pricing_approver", p1, f"{len(p1)} line{'s use' if len(p1) != 1 else ' uses'} Proposed list prices ({_list(p1)}): "
                                                        "a proposal needs Pricing Approver sign-off before sending."))
    one_time_discount = float(terms.get("discount_one_time_pct") or 0)
    if 0 < d <= discount_limit_pct:
        out.append(_rule("P-2", "sales_manager", [], f"Discount on recurring of {d:g}% needs the Sales Manager (up to {discount_limit_pct:g}%)."))
    if d > discount_limit_pct or one_time_discount > 0:
        why = [f"discount on recurring of {d:g}% is above {discount_limit_pct:g}%"] if d > discount_limit_pct else []
        why += [f"one-time discount of {one_time_discount:g}%"] if one_time_discount > 0 else []
        out.append(_rule("P-3", "pricing_approver", [], f"The {' and the '.join(why)}: Pricing Approver."))
    p4 = _codes(priced, lambda ln: ln.get("low") is not None and ln.get("unit_price_used") is not None and ln["unit_price_used"] < ln["low"])
    if p4:
        out.append(_rule("P-4", "pricing_approver", p4, f"Price below the catalog Low on {_list(p4)}: Pricing Approver."))
    p5 = _codes(priced, lambda ln: ln.get("high") is not None and ln.get("unit_price_used") is not None and ln["unit_price_used"] > ln["high"])
    if p5:
        out.append(_rule("P-5", "sales_manager", p5, f"Price above the catalog High on {_list(p5)}: Sales Manager sanity check."))
    custom = []
    if (terms.get("payment_days") or 0) > STANDARD_PAYMENT_DAYS:
        custom.append(f"payment in {terms['payment_days']} days")
    if terms.get("custom_liability"):
        custom.append("custom liability terms")
    if terms.get("sla_credits"):
        custom.append("SLA credits")
    if custom:
        out.append(_rule("P-6", "pricing_approver", [], f"Custom terms ({', '.join(custom)}): Pricing Approver."))
    p7 = _codes(lines, lambda ln: ln.get("sellable_status") == "roadmap")
    if p7:
        out.append(_rule("P-7", None, p7, f"{_list(p7)} {'is a roadmap item' if len(p7) == 1 else 'are roadmap items'}: shown only under "
                                          "\"Optional, when available\" with no price.", kind="blocked"))
    p8 = _codes(lines, lambda ln: ln.get("sellable_status") == "manual_delivery")
    if p8:
        out.append(_rule("P-8", None, p8, f"{_list(p8)}: assumption added — delivered by Futran consultants until the platform feature ships.", kind="note"))
    return out


def summary(lines: list[dict], approvals: list[dict]) -> str:
    """One sentence for the Estimator, in the design's words."""
    parts = []
    edited = [ln for ln in lines if ln.get("edited")]
    outside = {c for a in approvals if a["rule"] in ("P-4", "P-5") for c in a["codes"]}
    inside = [ln for ln in edited if ln["code"] not in outside]
    if inside:
        n = len(inside)
        parts.append(f"{n} line{'s' if n != 1 else ''} edited, still inside the Low–High range: no extra approval.")
    for a in approvals:
        if a["kind"] == "approval":
            parts.append(f"{a['rule']} · {a['message']}")
    if not parts:
        parts.append("No approvals needed: every line is at an approved or existing list price with no discount.")
    return " ".join(parts)
