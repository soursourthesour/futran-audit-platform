"""Review fixes: everyone who touched a proposal is barred from approving it; free-text terms need P-6; guardrails at send
use the current price list; the independence flag is recomputed; converting keeps the estimate's prices; a failing
hand-off never loses the acceptance."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden
from app.proposals import approvals, sending
from app.proposals import service as ps

TO = [{"name": "Dana Buyer", "email": "dana@acme.example"}]


def _line(db, p, code):
    return next(ln for ln in ps.lines(db, p) if ln.catalog_code == code)


def _rules(db, p):
    return {r["rule"]: r for r in ps.needed(db, p)}


@pytest.fixture
def draft(db, pw):
    p = ps.create_blank(db, pw.opp, pw.sales)
    ps.add_line(db, pw.sales, p, "L-01", 1)
    ps.add_line(db, pw.sales, p, "M-03a", 1)
    db.commit()
    return p


# ---- 1. self-approval
def test_manager_who_set_the_discount_cannot_approve_it(db, pw, draft):
    ps.update_terms(db, pw.manager, draft, {"discount_recurring_pct": 10})
    ps.update_line(db, pw.sales, draft, _line(db, draft, "L-01").id, {"deliverables_text": "Tailored for Acme."})  # the rep edits last
    [req] = approvals.request(db, pw.sales, draft)
    with pytest.raises(Forbidden):
        approvals.decide(db, pw.manager, req, "approve", "")
    assert approvals.queue(db, pw.manager, "mine") == []


def test_dual_role_person_who_changed_a_quantity_cannot_approve(db, pw, draft):
    from app.tenancy.service import assign_role

    assign_role(db, pw.sales2, "sales_manager")
    ps.update_line(db, pw.sales2, draft, _line(db, draft, "M-03a").id, {"qty": 2})
    ps.update_terms(db, pw.sales, draft, {"discount_recurring_pct": 10})
    [req] = approvals.request(db, pw.sales, draft)
    with pytest.raises(Forbidden):
        approvals.decide(db, pw.sales2, req, "approve", "")
    approvals.decide(db, pw.manager, req, "approve", "")


def test_creator_of_v1_cannot_approve_v2(db, pw, settings):
    v1 = ps.create_blank(db, pw.opp, pw.manager)
    ps.add_line(db, pw.manager, v1, "L-01", 1)
    sending.send(db, settings, pw.manager, v1, recipients=TO)
    v2 = ps.new_version(db, pw.sales, v1)
    ps.update_terms(db, pw.sales, v2, {"discount_recurring_pct": 10})
    [req] = approvals.request(db, pw.sales, v2)
    with pytest.raises(Forbidden):
        approvals.decide(db, pw.manager, req, "approve", "")


# ---- 2. free-text terms
def test_free_text_payment_terms_and_sla_need_p6_and_count_in_the_fingerprint(db, pw, draft):
    ps.update_terms(db, pw.sales, draft, {"terms": {"payment_terms": "Payment within 120 days of invoice."}})
    assert "P-6" in _rules(db, draft)
    [req] = approvals.request(db, pw.sales, draft)
    approvals.decide(db, pw.approver, req, "approve", "")
    assert approvals.unmet(db, draft) == []
    ps.update_terms(db, pw.sales, draft, {"terms": {"payment_terms": "Payment within 180 days of invoice."}})
    assert approvals.unmet(db, draft)[0]["state"] == "outdated"
    ps.update_terms(db, pw.sales, draft, {"terms": {"payment_terms": "", "sla": "99.99% uptime with credits"}})
    assert "P-6" in _rules(db, draft)
    ps.update_terms(db, pw.sales, draft, {"terms": {"sla": "", "start_on": "2027-01-04"}})
    fp = draft.terms.copy()
    from app.proposals import guardrails

    before = guardrails.fingerprint(draft, ps.lines(db, draft))
    ps.update_terms(db, pw.sales, draft, {"terms": {"start_on": "2027-02-01"}})
    assert guardrails.fingerprint(draft, ps.lines(db, draft)) != before and fp != draft.terms


# ---- 3. current price list at send
def test_send_checks_the_current_price_list_and_offers_an_update(db, pw, settings, draft):
    from app.catalog.service import items_by_codes

    it = items_by_codes(db, ["L-01"])["L-01"]
    it.low, it.list_price, it.high = 11000, 11500, 14000
    db.flush()
    assert _rules(db, draft)["P-4"]["codes"] == ["L-01"]  # the kept 8,500 is below the new Low
    assert [c["code"] for c in ps.price_changes(db, draft)] == ["L-01"]
    with pytest.raises(Conflict) as exc:
        sending.send(db, settings, pw.sales, draft, recipients=TO)
    assert "P-4" in exc.value.detail
    ps.update_to_current_prices(db, pw.sales, draft)
    assert _line(db, draft, "L-01").unit_price_used == 11500 and ps.price_changes(db, draft) == []
    assert "P-4" not in _rules(db, draft)
    sending.send(db, settings, pw.sales, draft, recipients=TO)
    assert draft.status == "sent"


def test_a_price_now_proposed_needs_p1(db, pw, draft):
    from app.catalog.service import items_by_codes

    items_by_codes(db, ["L-01"])["L-01"].price_status = "proposed"
    db.flush()
    assert _rules(db, draft)["P-1"]["codes"] == ["L-01"]


# ---- 4. independence recomputed
def test_prospect_that_became_an_audit_client_gets_the_independence_rules(db, pw, settings, draft):
    from app.engagements.models import Engagement
    from app.proposals import document

    ps.add_line(db, pw.sales, draft, "M-07a", 1)
    assert draft.independence["flag"] is False
    db.add(Engagement(organization_id=pw.prospect.id, client_id=pw.prospect.id, name="Acme AI audit", status="in_progress", stage=3, audit_ref="FSL-AI-AUD-2026-888"))
    db.flush()
    with pytest.raises(Conflict) as exc:
        sending.send(db, settings, pw.sales, draft, recipients=TO)
    assert "I-2" in exc.value.detail
    assert draft.independence["flag"] is True and "## Independence statement" in document.markdown(db, draft)


def test_opening_the_builder_refreshes_the_flag(db, pw, draft):
    from app.engagements.models import Engagement

    db.add(Engagement(organization_id=pw.prospect.id, client_id=pw.prospect.id, name="Acme AI audit", status="initiated", stage=2, audit_ref="FSL-AI-AUD-2026-889"))
    db.commit()
    body = pw.as_(pw.sales).get(f"/api/v1/sales/proposals/{draft.id}").json()
    assert body["independence"]["flag"] is True and "independence" in [s["key"] for s in body["sections"]]


# ---- 5. convert keeps the estimate's prices
def test_convert_keeps_the_estimates_saved_prices(db, pw, estimate):
    from app.catalog.service import items_by_codes

    items_by_codes(db, ["A-02b"])["A-02b"].list_price = 36000
    db.flush()
    p = ps.create_from_estimate(db, estimate, pw.sales)
    assert _line(db, p, "A-02b").unit_price_used == 35000
    assert [c["code"] for c in ps.price_changes(db, p)] == ["A-02b"]


# ---- 6. a failing hand-off keeps the acceptance
def test_a_database_error_in_the_handoff_never_loses_the_acceptance(db, pw, settings, draft, monkeypatch):
    from app.commercial import handoff
    from app.proposals.models import Acceptance, ProposalEvent

    def broken(db, p, a, actor):
        db.add(Acceptance(proposal_id=p.id, name="dup", title="dup", email="d@x.example"))  # unique per proposal: fails on flush
        db.flush()

    monkeypatch.setattr(handoff, "create_from_acceptance", broken)
    seen = []
    real = sending.new_token
    monkeypatch.setattr(sending, "new_token", lambda: seen.append(real()) or seen[-1])
    sending.send(db, settings, pw.sales, draft, recipients=TO)
    db.commit()
    r = pw.client.post(f"/api/v1/public/p/{seen[0]}/accept", data={"name": "Dana Buyer", "title": "COO", "email": "dana@acme.example", "authorised": "true"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.scalar(select(Acceptance).where(Acceptance.proposal_id == draft.id)).name == "Dana Buyer"
    assert db.scalar(select(ProposalEvent).where(ProposalEvent.proposal_id == draft.id, ProposalEvent.kind == "handoff_failed"))
    assert timedelta  # noqa: B018
