"""Fixes from the R5 review (coordinator, 12 Nov): change orders billed once, fees and hours banks kept to the right
people, partly returned weeks, A-03 counted once per system, ordered engagements only for the add-system hook, the
incident engagement no longer backdated, finishing a failed hand-off, independence before staffing, existing Trust
Center and API use kept, and change-order price approvals by the guardrail rules."""
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.commercial import commercials, handoff, plans
from app.commercial.models import ChangeOrder, EngagementCommercial, HoursBank, Order, OrderLine, Retainer, TimeEntry
from app.core.errors import Conflict
from app.engagements.models import Engagement, EngagementTeam
from app.systems.models import AISystem, SystemAdditionRequest
from tests.commercial.conftest import STANDARD_LINES, line, proposal_for
from tests.factories import make_user

MON = date(2026, 11, 9)


def _ordered(cw, fee=43500):
    from app.commercial.handoff import default_milestones

    o = Order(organization_id=cw.org.id, ref="ORD-0188", status="active")
    cw.db.add(o)
    cw.db.flush()
    cw.db.add(OrderLine(organization_id=cw.org.id, order_id=o.id, catalog_code="A-02b", description="Audit, 11–50 systems", qty=1, unit_price=35000, line_value=35000,
                        engagement_id=cw.engagement.id))
    cw.db.add(EngagementCommercial(organization_id=cw.org.id, engagement_id=cw.engagement.id, order_id=o.id, fee_total=fee, milestones=default_milestones(fee)))
    cw.db.commit()
    return o


def _raise(cw, code, qty, **kw):
    cw.as_(cw.em)
    r = cw.client.post(f"/api/v1/e/{cw.engagement.id}/change-orders", json={"code": code, "qty": qty, "reason": "Scope grew", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _client_approves(cw, co_id):
    cw.as_(cw.caico)
    r = cw.client.post(f"/api/v1/change-orders/{co_id}/decide", json={"approve": True})
    assert r.status_code == 200, r.text


def _addition(cw, name="Vendor chatbot"):
    req = SystemAdditionRequest(organization_id=cw.org.id, engagement_id=cw.engagement.id, requested_by=cw.auditor.id,
                                payload={"name": name, "built_by": "vendor", "use_case_ids": []}, reason="Found in the sweep", status="pending")
    cw.db.add(req)
    cw.db.commit()
    cw.as_(cw.em)
    r = cw.client.post(f"/api/v1/system-requests/{req.id}/decide", json={"approve": True})
    assert r.status_code == 200, r.text
    return r.json()


# 1 ---------------------------------------------------------------------------------------------------------------
def test_an_approved_change_order_is_billed_exactly_once(cw, fake_catalog):
    _ordered(cw)
    co = _raise(cw, "A-04", 2)
    _client_approves(cw, co["id"])
    period = date.today().strftime("%Y-%m")
    rows = plans.billing_rows(cw.db, period, cw.org.id)
    amounts = [float(r[11]) for r in rows]
    assert amounts.count(2400.0) == 1, rows
    cw.as_(cw.em)
    ms = cw.client.get(f"/api/v1/e/{cw.engagement.id}/commercial").json()["milestones"]
    assert [m["amount"] for m in ms if m["trigger"] == "change_order"] == [2400]
    # editing the fee split keeps the change-order milestone and does not bill it again
    r = cw.client.put(f"/api/v1/e/{cw.engagement.id}/commercial", json={"fee_total": 45900, "milestones": [{"label": "All on report", "trigger": "sign_off_7", "pct": 100}]})
    assert r.status_code == 200, r.text
    ms = r.json()["milestones"]
    assert [m["amount"] for m in ms] == [43500, 2400]
    assert [float(r[11]) for r in plans.billing_rows(cw.db, period, cw.org.id)].count(2400.0) == 1


# 2 ---------------------------------------------------------------------------------------------------------------
def _won(cw):
    p, a = proposal_for(cw, STANDARD_LINES())
    handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.db.commit()
    return cw.db.scalar(select(HoursBank)), cw.db.scalar(select(Retainer))


def test_auditors_never_see_retainer_fees_and_only_log_to_their_clients(cw, fake_catalog):
    bank, ret = _won(cw)
    cw.as_(cw.auditor)  # on Harbor Health's audit team, not Acme's
    banks = cw.client.get("/api/v1/staff/hours-banks").json()
    assert "monthly_fee" not in str(banks) and "hourly_rate" not in str(banks)
    targets = {t["key"] for t in cw.client.get(f"/api/v1/staff/time/{MON.isoformat()}").json()["targets"]}
    assert f"bank:{bank.id}" not in targets and f"retainer:{ret.id}" not in targets
    r = cw.client.put(f"/api/v1/staff/time/{MON.isoformat()}", json={"rows": [{"target": f"bank:{bank.id}", "activity": "advisory", "billable": True,
                                                                               "hours": {MON.isoformat(): 2}}]})
    assert r.status_code == 422
    # once on an Acme engagement, the auditor may log to its bank, still without seeing fees
    e = cw.db.scalar(select(Engagement).where(Engagement.client_id == cw.prospect.id, Engagement.type == "initial_assessment"))
    cw.db.add(EngagementTeam(organization_id=e.client_id, engagement_id=e.id, user_id=cw.auditor.id, role="auditor"))
    cw.db.commit()
    targets = {t["key"] for t in cw.client.get(f"/api/v1/staff/time/{MON.isoformat()}").json()["targets"]}
    assert f"bank:{bank.id}" in targets
    assert "$" not in str(cw.client.get(f"/api/v1/staff/hours-banks").json())
    cw.as_(cw.sales)
    assert "hourly_rate" in str(cw.client.get("/api/v1/staff/hours-banks").json())


# 3 ---------------------------------------------------------------------------------------------------------------
def test_a_week_partly_returned_and_partly_approved_can_be_fixed_and_resubmitted(cw):
    eng = f"engagement:{cw.engagement.id}"
    cw.as_(cw.auditor)
    rows = [{"target": eng, "activity": "fieldwork", "billable": True, "hours": {MON.isoformat(): 4}},
            {"target": "internal", "activity": "other", "billable": False, "hours": {MON.isoformat(): 2}}]
    assert cw.client.put(f"/api/v1/staff/time/{MON.isoformat()}", json={"rows": rows}).status_code == 200
    cw.client.post(f"/api/v1/staff/time/{MON.isoformat()}/submit")
    cw.as_(cw.em)  # approves the engagement time
    assert cw.client.post(f"/api/v1/staff/time/{MON.isoformat()}/decide", json={"user_id": cw.auditor.id, "approve": True}).status_code == 200
    cw.as_(cw.chief)  # returns the internal time
    assert cw.client.post(f"/api/v1/staff/time/{MON.isoformat()}/decide", json={"user_id": cw.auditor.id, "approve": False, "note": "Say what it was"}).status_code == 200
    cw.as_(cw.auditor)
    week = cw.client.get(f"/api/v1/staff/time/{MON.isoformat()}").json()
    assert sorted((r["target"], r["locked"]) for r in week["rows"]) == [(eng, True), ("internal", False)]
    fixed = [{"target": "internal", "activity": "other", "billable": False, "note": "Methodology", "hours": {MON.isoformat(): 2.5}}]
    r = cw.client.put(f"/api/v1/staff/time/{MON.isoformat()}", json={"rows": fixed})
    assert r.status_code == 200, r.text
    assert cw.client.post(f"/api/v1/staff/time/{MON.isoformat()}/submit").status_code == 200
    entries = list(cw.db.scalars(select(TimeEntry).where(TimeEntry.deleted_at.is_(None))))
    assert sorted((t.activity, t.hours, t.status) for t in entries) == [("fieldwork", 4, "approved"), ("other", 2.5, "submitted")]


# 4 ---------------------------------------------------------------------------------------------------------------
def test_a_manual_a03_change_order_covers_the_system_added_later(cw, fake_catalog):
    _ordered(cw)
    co = _raise(cw, "A-03", 1)
    _client_approves(cw, co["id"])
    before = len(list(cw.db.scalars(select(AISystem).where(AISystem.engagement_id == cw.engagement.id))))
    assert _addition(cw)["status"] == "approved"  # covered by the approved A-03: added at once, no second change order
    assert len(list(cw.db.scalars(select(ChangeOrder)))) == 1
    assert len(list(cw.db.scalars(select(AISystem).where(AISystem.engagement_id == cw.engagement.id)))) == before + 1
    # the next system needs its own change order
    assert _addition(cw, "Second tool")["status"] == "co_pending"
    assert len(list(cw.db.scalars(select(ChangeOrder)))) == 2


# 5 ---------------------------------------------------------------------------------------------------------------
def test_typing_a_fee_on_an_engagement_without_an_order_keeps_todays_addition_rule(cw, fake_catalog):
    cw.as_(cw.em)
    assert cw.client.put(f"/api/v1/e/{cw.engagement.id}/commercial", json={"fee_total": 20000}).status_code == 200
    assert _addition(cw)["status"] == "approved"
    assert cw.db.scalar(select(ChangeOrder)) is None


# 6 ---------------------------------------------------------------------------------------------------------------
def test_incident_engagement_is_a_real_dated_draft_and_does_not_hide_the_renewal(cw, fake_catalog):
    from app.sales.scan import _renewal_items
    from app.servicetemplates.types import ENGAGEMENT_TYPES
    from app.tenancy.people import current_engagement

    assert ENGAGEMENT_TYPES["incident_response"] == "Incident response"
    done = datetime.utcnow() - timedelta(days=330)
    cw.engagement.status, cw.engagement.completed_at = "completed", done
    cw.engagement.created_at = done - timedelta(days=60)
    r = Retainer(organization_id=cw.org.id, code="M-12a", type="incident_response", monthly_fee=1000, hourly_rate=350, status="standing")
    cw.db.add(r)
    cw.db.commit()
    cw.as_(cw.chief)
    assert cw.client.post(f"/api/v1/staff/retainers/{r.id}/activate", json={"reason": "Data leak"}).status_code == 200
    cw.db.expire_all()
    inc = cw.db.get(Engagement, cw.db.get(Retainer, r.id).incident_engagement_id)
    assert inc.type == "incident_response" and inc.status == "draft" and inc.created_at > cw.engagement.created_at
    # the Chief Auditor approves it; even live and later completed it is never the client's current audit nor a newer one
    assert cw.client.post(f"/api/v1/staff/retainers/{r.id}/approve-incident").status_code == 200
    cw.db.expire_all()
    assert cw.db.get(Engagement, inc.id).status == "in_progress"
    inc = cw.db.get(Engagement, inc.id)
    inc.status, inc.completed_at = "completed", datetime.utcnow()
    cw.db.commit()
    assert current_engagement(cw.db, cw.org) is None or current_engagement(cw.db, cw.org).type != "incident_response"
    items = _renewal_items(cw.db, date.today())
    assert any(i.ref.startswith(f"renewal:{cw.engagement.id}") for i in items), items


def test_the_activator_must_pass_the_independence_checks(cw, fake_catalog):
    r = Retainer(organization_id=cw.org.id, code="M-12a", type="incident_response", monthly_fee=1000, hourly_rate=350, status="standing",
                 officer_user_id=cw.chief.id)
    cw.db.add(r)
    cw.db.commit()
    cw.as_(cw.chief)
    resp = cw.client.post(f"/api/v1/staff/retainers/{r.id}/activate", json={"reason": "Leak"})
    assert resp.status_code == 409
    cw.db.expire_all()
    assert cw.db.get(Retainer, r.id).status == "standing"


# 7 ---------------------------------------------------------------------------------------------------------------
def test_finish_a_failed_hand_off_from_sm13(cw, fake_catalog):
    from app.proposals.models import Acceptance, Proposal, ProposalLine

    p = Proposal(thread_id="t1", opportunity_id=cw.opp.id, organization_id=cw.prospect.id, version=1, status="accepted", terms={"term_years": 1})
    cw.db.add(p)
    cw.db.flush()
    cw.db.add(ProposalLine(proposal_id=p.id, catalog_code="A-02b", name="Audit, 11–50 systems", qty=1, unit_price_used=35000, line_value=35000, billing="one_time"))
    cw.db.add(Acceptance(proposal_id=p.id, name="Dana Diaz", title="COO", email="dana@acme.example", authorised_confirmed=True))
    cw.db.commit()
    url = f"/api/v1/sales/opportunities/{cw.opp.id}/handoff"
    cw.as_(cw.sales2)  # not the owner
    assert cw.client.post(url).status_code == 403
    cw.as_(cw.sales)
    assert cw.client.get(url).status_code == 404
    r = cw.client.post(url)
    assert r.status_code == 200, r.text
    assert r.json()["items"][1]["kind"] == "order"
    assert cw.client.post(url).json()["id"] == r.json()["id"]  # idempotent
    assert len(list(cw.db.scalars(select(Order)))) == 1


# 8 ---------------------------------------------------------------------------------------------------------------
def test_drafts_with_separate_team_lines_cannot_be_staffed_or_approved_before_the_chief_auditor_confirms(cw, fake_catalog):
    from app.engagements.team import check_separate_team
    from app.commercial.handoff import require_independence_confirmed

    p, a = proposal_for(cw, [line("A-02b", 1, 35000), line("X-01", 1, 6000, value=72000)])
    h = handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.db.commit()
    e = cw.db.scalar(select(Engagement).where(Engagement.client_id == cw.prospect.id))
    try:
        check_separate_team(cw.db, cw.prospect.id, cw.auditor.id)
        raise AssertionError("staffing was allowed")
    except Conflict as exc:
        assert "separate delivery team" in str(exc.detail)
    try:
        require_independence_confirmed(cw.db, e)
        raise AssertionError("approval was allowed")
    except Conflict:
        pass
    handoff.confirm_independence(cw.db, cw.chief, h, [cw.sales2.id], None)
    check_separate_team(cw.db, cw.prospect.id, cw.auditor.id)
    require_independence_confirmed(cw.db, e)


# 9 ---------------------------------------------------------------------------------------------------------------
def test_an_existing_trust_center_and_api_clients_survive_an_order_without_them(cw, fake_catalog):
    from app.publicapi.models import ApiClient
    from app.trust.models import TrustCenterPage

    body = {"slug": "harbor", "title": "How Harbor governs AI", "intro": "We use AI.", "contact_email": "ai@harbor.example", "live": True}
    cw.as_(cw.caico)
    assert cw.client.put("/api/v1/trust/page", json=body).status_code == 200
    cw.as_(cw.client_admin)
    assert cw.client.post("/api/v1/admin/api/clients", json={"name": "HR system", "scopes": ["inventory:read"]}).status_code == 200
    # Harbor now buys monitoring with no Trust Center or API lines
    cw.opp.organization_id = cw.org.id
    cw.db.commit()
    p, a = proposal_for(cw, [line("M-01e", 1, 36000)])
    handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.db.commit()
    assert cw.db.scalar(select(TrustCenterPage)) is not None and cw.db.scalar(select(ApiClient)) is not None
    cw.as_(cw.caico)
    assert cw.client.put("/api/v1/trust/page", json=body | {"title": "Updated"}).status_code == 200
    cw.as_(cw.client_admin)
    assert cw.client.post("/api/v1/admin/api/clients", json={"name": "Second", "scopes": ["inventory:read"]}).status_code == 200


# 10 --------------------------------------------------------------------------------------------------------------
def test_price_below_low_needs_the_pricing_approver_and_the_client_never_sees_list_price(cw, fake_catalog):
    _ordered(cw)
    mgr = make_user(cw.db, cw.futran, roles=["sales_manager"], name="Mia Manager", email="mia@futran.test")
    pa = make_user(cw.db, cw.futran, roles=["pricing_approver"], name="Pat Pricing", email="pat@futran.test")
    cw.db.commit()
    co = _raise(cw, "A-03", 1, unit_price=500)  # Low is 600: P-4
    assert co["status"] == "awaiting_futran_approval"
    cw.as_(mgr)
    assert cw.client.post(f"/api/v1/change-orders/{co['id']}/price-decision", json={"approve": True}).status_code == 403
    cw.as_(pa)
    assert cw.client.post(f"/api/v1/change-orders/{co['id']}/price-decision", json={"approve": True}).status_code == 200
    # a price above High (P-5) is the Sales Manager's
    co2 = _raise(cw, "A-03", 1, unit_price=950)
    cw.as_(pa)
    assert cw.client.post(f"/api/v1/change-orders/{co2['id']}/price-decision", json={"approve": True}).status_code == 403
    cw.as_(mgr)
    assert cw.client.post(f"/api/v1/change-orders/{co2['id']}/price-decision", json={"approve": True}).status_code == 200
    # an edited price inside Low–High needs nobody
    assert _raise(cw, "A-03", 1, unit_price=700)["status"] == "awaiting_client"
    cw.as_(cw.caico)
    lst = cw.client.get("/api/v1/change-orders").json()
    assert lst and "list_price" not in str(lst) and "approver" not in str(lst)


# 11 --------------------------------------------------------------------------------------------------------------
def test_a_one_time_discount_reaches_the_order_the_engagement_fees_and_the_billing_export(cw, fake_catalog):
    p, a = proposal_for(cw, [line("A-02b", 1, 35000), line("A-05", 3, 1500)], discount_one_time_pct=20)
    p.totals = {"one_time": 39500, "one_time_discount": 7900, "one_time_net": 31600, "y1_total": 31600}
    h = handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.db.commit()
    order = cw.db.get(Order, h.order_id)
    gross = sum(ln.line_value for ln in cw.db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)))
    assert order.discount_one_time_pct == 20 and gross * (1 - order.discount_one_time_pct / 100) == 31600
    fees = sum(c.fee_total for c in cw.db.scalars(select(EngagementCommercial)))
    assert fees == 31600 and h.year1_value == 31600
    for com in cw.db.scalars(select(EngagementCommercial)):  # both milestones reached this month
        com.milestones = [m | {"reached_on": date.today().isoformat()} for m in com.milestones]
    cw.db.commit()
    rows = plans.billing_rows(cw.db, date.today().strftime("%Y-%m"), cw.prospect.id)
    assert sum(float(r[11]) for r in rows) == 31600, rows
