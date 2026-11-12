"""What a proposal version needs before it can be sent (spec §4.7), checked server-side at send.

Pricing rules P-1 to P-8 come from R1's shared `catalog.guardrails.needed_approvals`, so the Estimator and the builder
agree; independence rules I-1 to I-4 from `proposals.independence`. Two blockers are added here: a line with no price
(no edited price and no catalog list price) and a line that is no longer on the price list.

An approval counts only for the exact content it was given for: each request carries a fingerprint of the offered
lines (code, quantity, unit price used, statuses), the discount and the terms. Editing any of these afterwards means
the rule needs approval again."""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import guardrails as catalog_guardrails
from app.proposals import independence
from app.proposals.models import ApprovalRequest, Proposal, ProposalLine

APPROVER_LABELS = {"pricing_approver": "Pricing Approver", "sales_manager": "Sales Manager", "chief_auditor": "Chief Auditor"}
# who may decide a rule's request: a Pricing Approver also covers the Sales Manager's rules
DECIDERS = {"sales_manager": {"sales_manager", "pricing_approver"}, "pricing_approver": {"pricing_approver"}, "chief_auditor": {"chief_auditor"}}
# every term the client sees: changing any of them after an approval means asking again
FINGERPRINT_TERMS = ("payment_days", "payment_terms", "term_years", "sla", "data_region", "custom_liability", "sla_credits", "discount_one_time_pct",
                     "start_on")
FREE_TEXT_TERMS = {"payment_terms": "payment terms written out", "sla": "service levels written out"}  # not the standard values: P-6


def offered(lines: list[ProposalLine]) -> list[ProposalLine]:
    """Lines the client is offered with a price: not removed, not roadmap."""
    return [ln for ln in lines if not ln.removed_reason and ln.sellable_status != "roadmap"]


def discount_limit(db: Session) -> float:
    from app.catalog import service as cat

    return float(cat.settings(db).manager_discount_limit_pct)


def _remediation_tags(db: Session, codes: list[str]) -> dict[str, list]:
    from app.catalog.service import items_by_codes

    return {c: list(it.remediation_of or []) for c, it in items_by_codes(db, codes).items()}


def _current(db: Session, ln: ProposalLine, items: dict) -> dict:
    """The line as the guardrails see it: the price the client is offered, checked against the price list as it is now.
    A list price kept from an earlier catalog version counts as an edited price (rules P-4 and P-5 apply to it)."""
    it = items.get(ln.catalog_code)
    if it is None:
        return {"code": ln.catalog_code, "price_status": ln.price_status, "sellable_status": ln.sellable_status, "unit_price_used": ln.unit_price_used,
                "low": ln.low, "high": ln.high}
    return {"code": ln.catalog_code, "price_status": it.price_status, "sellable_status": it.sellable_status, "unit_price_used": ln.unit_price_used,
            "low": it.low, "high": it.high}


def needed(db: Session, p: Proposal, lines: list[ProposalLine]) -> list[dict]:
    from app.catalog.service import items_by_codes

    live = [ln for ln in lines if not ln.removed_reason]
    items = items_by_codes(db, [ln.catalog_code for ln in live if ln.on_catalog])
    priced = [_current(db, ln, items) for ln in live if ln.on_catalog]
    out: list[dict] = []
    missing = [ln.catalog_code for ln in live if not ln.on_catalog]
    if missing:
        out.append({"rule": "PRICE", "kind": "blocked", "approver_role": None, "approver": None, "codes": missing,
                    "message": f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not on the price list: remove {'it' if len(missing) == 1 else 'them'} to send."})
    unpriced = [ln.catalog_code for ln in offered(live) if ln.on_catalog and ln.unit_price_used is None]
    if unpriced:
        out.append({"rule": "PRICE", "kind": "blocked", "approver_role": None, "approver": None, "codes": unpriced,
                    "message": f"{', '.join(unpriced)} {'has' if len(unpriced) == 1 else 'have'} no price: enter a price or remove the line."})
    out += catalog_guardrails.needed_approvals(priced, p.discount_recurring_pct, p.terms or {}, discount_limit_pct=discount_limit(db))
    free = [label for k, label in FREE_TEXT_TERMS.items() if str((p.terms or {}).get(k) or "").strip()]
    if free:
        p6 = next((r for r in out if r["rule"] == "P-6"), None)
        if p6 is None:
            out.append({"rule": "P-6", "kind": "approval", "approver_role": "pricing_approver", "approver": "Pricing Approver", "codes": [],
                        "message": f"Custom terms ({', '.join(free)}): Pricing Approver."})
        else:
            p6["message"] = p6["message"].replace("): Pricing Approver.", f", {', '.join(free)}): Pricing Approver.")
    flag = bool((p.independence or {}).get("flag"))
    tags = _remediation_tags(db, [ln.catalog_code for ln in offered(live)])
    out += independence.rules(db, p.organization_id, [{"code": ln.catalog_code, "remediation_of": tags.get(ln.catalog_code, [])} for ln in offered(live)], flag)
    for r in out:  # P-7 is shown, not a blocker: the roadmap line sits under "Optional, when available" with no price
        if r["rule"] == "P-7":
            r["kind"] = "note"
    return out


def fingerprint(p: Proposal, lines: list[ProposalLine]) -> str:
    body = {"lines": sorted([[ln.catalog_code, ln.qty, ln.unit_price_used, ln.price_status, ln.sellable_status] for ln in offered(lines)], key=lambda x: x[0]),
            "discount": p.discount_recurring_pct or 0, "terms": {k: (p.terms or {}).get(k) for k in FINGERPRINT_TERMS}, "valid_days": p.valid_days}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def requests(db: Session, p: Proposal) -> list[ApprovalRequest]:
    return list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.proposal_id == p.id).order_by(ApprovalRequest.requested_at)))


def rule_states(db: Session, p: Proposal, lines: list[ProposalLine]) -> list[dict]:
    """Each needed rule with where its approval stands: missing | pending | approved | returned | outdated."""
    fp = fingerprint(p, lines)
    reqs = requests(db, p)
    out = []
    for r in needed(db, p, lines):
        state = None
        req = None
        if r["kind"] == "approval":
            mine = [q for q in reqs if q.rule == r["rule"] and q.status != "withdrawn"]
            current = [q for q in mine if q.fingerprint == fp]
            req = current[-1] if current else (mine[-1] if mine else None)
            if req is None:
                state = "missing"
            elif req.fingerprint != fp:
                state = "outdated"
            else:
                state = req.status
        out.append({**r, "state": state, "request_id": req.id if req else None, "note": req.note if req else None,
                    "decided_at": req.decided_at.isoformat() if req and req.decided_at else None, "approver_id": req.approver_id if req else None})
    return out


def unmet(db: Session, p: Proposal, lines: list[ProposalLine]) -> list[dict]:
    return [r for r in rule_states(db, p, lines) if r["kind"] == "blocked" or (r["kind"] == "approval" and r["state"] != "approved")]
