"""Guardrails P-1 to P-8 and I-1 to I-4, approval requests and decisions (spec §4.7, SM-11)."""
import pytest

from app.core.errors import Conflict, Forbidden, Invalid
from app.proposals import approvals
from app.proposals import service as ps
from tests.proposals.conftest import add_item


def _rules(db, p):
    return {r["rule"]: r for r in ps.needed(db, p)}


def _code(db, p, code):
    return next(ln for ln in ps.lines(db, p) if ln.catalog_code == code)


@pytest.fixture
def prop(db, pw):
    p = ps.create_blank(db, pw.opp, pw.sales)
    ps.add_line(db, pw.sales, p, "L-01", 1)  # existing price, 8,500 (Low 8,500, High 12,000)
    ps.add_line(db, pw.sales, p, "M-03a", 1)  # existing, quarterly
    db.commit()
    return p


def test_clean_proposal_needs_nothing(db, pw, prop):
    assert [r for r in ps.needed(db, prop) if r["kind"] != "note"] == []
    assert approvals.unmet(db, prop) == []


def test_pricing_rules(db, pw, prop):
    ps.add_line(db, pw.sales, prop, "A-06b", 1)  # Proposed price
    assert _rules(db, prop)["P-1"]["approver_role"] == "pricing_approver"
    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 10})
    assert _rules(db, prop)["P-2"]["approver_role"] == "sales_manager"
    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 18})
    r = _rules(db, prop)
    assert "P-2" not in r and r["P-3"]["approver_role"] == "pricing_approver"
    ps.update_line(db, pw.sales, prop, _code(db, prop, "L-01").id, {"override_price": 8000})
    assert _rules(db, prop)["P-4"]["codes"] == ["L-01"]
    ps.update_line(db, pw.sales, prop, _code(db, prop, "L-01").id, {"override_price": 13000})
    assert _rules(db, prop)["P-5"]["approver_role"] == "sales_manager"
    ps.update_terms(db, pw.sales, prop, {"terms": {"payment_days": 60}})
    assert "payment in 60 days" in _rules(db, prop)["P-6"]["message"]
    ps.add_line(db, pw.sales, prop, "M-09", 1)
    assert _rules(db, prop)["P-7"]["kind"] == "note"  # shown as optional with no price, not a blocker
    ps.add_line(db, pw.sales, prop, "A-05", 2)
    assert _rules(db, prop)["P-8"]["kind"] == "note"


def test_discount_limit_is_the_price_list_setting(db, pw, prop):
    from app.catalog.models import CatalogSetting

    db.add(CatalogSetting(key="platform", manager_discount_limit_pct=20))
    db.flush()
    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 18})
    assert "P-2" in _rules(db, prop) and "P-3" not in _rules(db, prop)


def test_request_and_approve_then_edit_makes_it_outdated(db, pw, prop):
    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 10})
    reqs = approvals.request(db, pw.sales, prop)
    assert [r.rule for r in reqs] == ["P-2"] and prop.status == "awaiting_approval"
    assert approvals.unmet(db, prop)[0]["state"] == "pending"
    approvals.decide(db, pw.manager, reqs[0], "approve", "Fine for a 2-year deal")
    assert prop.status == "approved" and approvals.unmet(db, prop) == []
    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 12})
    assert prop.status == "draft" and approvals.unmet(db, prop)[0]["state"] == "outdated"
    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 10})  # back to what was approved
    assert prop.status == "approved"


def test_requesting_twice_does_not_duplicate(db, pw, prop):
    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 10})
    approvals.request(db, pw.sales, prop)
    assert approvals.request(db, pw.sales, prop) == []


def test_nobody_approves_their_own_proposal(db, pw, prop):
    ps.update_terms(db, pw.manager, prop, {"discount_recurring_pct": 10})  # the manager edited this version
    [req] = approvals.request(db, pw.sales, prop)
    with pytest.raises(Forbidden):
        approvals.decide(db, pw.manager, req, "approve", "")
    owner_mgr = pw.manager
    from app.tenancy.service import assign_role

    assign_role(db, pw.sales, "sales_manager")
    with pytest.raises(Forbidden):
        approvals.decide(db, pw.sales, req, "approve", "")  # the rep who built it, even holding the role
    assert owner_mgr is not None


def test_approver_must_hold_the_rule_role(db, pw, prop):
    ps.add_line(db, pw.sales, prop, "A-06b", 1)
    [req] = approvals.request(db, pw.sales, prop)
    assert req.rule == "P-1"
    with pytest.raises(Forbidden):
        approvals.decide(db, pw.manager, req, "approve", "")  # Sales Manager can't approve proposed prices
    approvals.decide(db, pw.approver, req, "approve", "")
    assert req.status == "approved" and req.approver_id == pw.approver.id


def test_pricing_approver_covers_sales_manager_rules(db, pw, prop):
    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 10})
    [req] = approvals.request(db, pw.sales, prop)
    approvals.decide(db, pw.approver, req, "approve", "")
    assert req.status == "approved"


def test_return_needs_a_note_and_notifies_the_owner(db, pw, prop):
    from sqlalchemy import select

    from app.notifications.models import Notification

    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 10})
    [req] = approvals.request(db, pw.sales, prop)
    assert db.scalar(select(Notification).where(Notification.user_id == pw.manager.id, Notification.kind == "proposal_approval_needed"))
    with pytest.raises(Invalid):
        approvals.decide(db, pw.manager, req, "return", " ")
    approvals.decide(db, pw.manager, req, "return", "Keep it at 5%")
    assert req.status == "returned" and prop.status == "draft"
    n = db.scalar(select(Notification).where(Notification.user_id == pw.sales.id, Notification.kind == "proposal_approval_decided"))
    assert n and "returned" in n.title
    with pytest.raises(Conflict):
        approvals.decide(db, pw.manager, req, "approve", "")


def test_independence_rules_for_an_audit_client(db, pw):
    from app.findings.models import Finding

    add_item(db, "M-12x", name="Bias remediation sprint", list_price=9000, remediation_of=["6"])
    db.add(Finding(organization_id=pw.audit_client.id, engagement_id=pw.engagement.id, ref="F-001", title="Impact ratio below 0.80", severity="high",
                   template_section="6.2"))
    db.flush()
    p = ps.create_blank(db, pw.audit_opp, pw.sales)
    for code in ("M-12x", "M-07a", "AA-02"):
        ps.add_line(db, pw.sales, p, code, 1)
    add_item(db, "X-01", name="Fractional AI Governance Officer", billing="monthly", periods_per_year=12, list_price=6000)
    ps.add_line(db, pw.sales, p, "X-01", 1)
    r = _rules(db, p)
    assert r["I-1"]["codes"] == ["M-12x"] and r["I-1"]["approver_role"] == "chief_auditor"
    assert r["I-2"]["codes"] == ["M-07a", "AA-02"]
    assert r["I-3"]["codes"] == ["X-01"]
    assert r["I-4"]["kind"] == "note"
    reqs = {q.rule: q for q in approvals.request(db, pw.sales, p)}
    with pytest.raises(Forbidden):
        approvals.decide(db, pw.approver, reqs["I-1"], "approve", "ok")
    with pytest.raises(Invalid):
        approvals.decide(db, pw.chief, reqs["I-1"], "approve", "")  # I-1 needs a note
    approvals.decide(db, pw.chief, reqs["I-1"], "approve", "Finding closed in fieldwork; separate team")


def test_no_independence_rules_for_a_prospect(db, pw):
    p = ps.create_blank(db, pw.opp, pw.sales)
    ps.add_line(db, pw.sales, p, "M-07a", 1)
    assert not any(r["rule"].startswith("I-") for r in ps.needed(db, p))


def test_queue_by_rule_and_tab(db, pw, prop):
    ps.add_line(db, pw.sales, prop, "A-06b", 1)
    ps.update_terms(db, pw.sales, prop, {"discount_recurring_pct": 18})
    approvals.request(db, pw.sales, prop)
    mine = approvals.queue(db, pw.approver, "mine")
    assert sorted(i["rule"] for i in mine) == ["P-1", "P-3"]
    assert approvals.queue(db, pw.manager, "mine") == []
    assert approvals.queue(db, pw.chief, "independence") == []
    item = mine[0]
    assert item["company"] == "Acme Staffing LLC" and item["version"] == 1 and item["requested_by"] == "Raj Mehta"
    detail = approvals.detail(db, pw.approver, item["id"])
    assert any(ln["code"] == "A-06b" and ln["low"] == 3000 and ln["list"] == 4000 for ln in detail["lines"])
    assert detail["can_decide"] is True and "margin_note" in detail
