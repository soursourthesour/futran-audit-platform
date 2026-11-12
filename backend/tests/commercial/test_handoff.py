"""SM-13: the won proposal becomes a draft client, an order with frozen prices, engagement drafts, a subscription with
entitlements, hours banks and retainers, a commission when there is a partner, and notifications — in one transaction,
with nothing sent to the client."""
from sqlalchemy import select

from app.commercial import handoff
from app.commercial.models import EngagementCommercial, Entitlement, Handoff, HoursBank, Order, OrderLine, Retainer
from app.engagements.models import ClientContact, Engagement
from app.mail.models import OutboxMessage
from app.monitoring.models import Subscription
from app.notifications.models import Notification
from app.tenancy.models import Organization
from tests.commercial.conftest import STANDARD_LINES, line, proposal_for


def _go(cw, lines=None, **terms):
    p, a = proposal_for(cw, lines or STANDARD_LINES(), **terms)
    h = handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.db.commit()
    return h


def test_prospect_becomes_a_draft_client_and_the_order_freezes_the_prices(cw, fake_catalog):
    h = _go(cw)
    org = cw.db.get(Organization, cw.prospect.id)
    assert org.status == "draft" and org.type == "client"
    order = cw.db.get(Order, h.order_id)
    assert order.organization_id == org.id and order.po_number == "PO-7788" and order.ref.startswith("ORD-")
    lines = {ln.catalog_code: ln for ln in cw.db.scalars(select(OrderLine).where(OrderLine.order_id == order.id))}
    assert set(lines) == {"A-02b", "A-05", "L-01", "M-01e", "M-11a", "M-13", "M-12a"}
    assert lines["A-05"].unit_price == 1500 and lines["A-05"].qty == 3 and not lines["A-05"].recurring
    assert lines["M-01e"].recurring and lines["M-01e"].end_on is not None
    # the catalog changing later never touches the order
    fake_catalog["A-05"].list_price = 9999
    cw.db.expire_all()
    assert cw.db.get(OrderLine, lines["A-05"].id).unit_price == 1500


def test_one_engagement_draft_per_delivery_family_with_the_wizard_prefilled(cw, fake_catalog):
    h = _go(cw)
    es = list(cw.db.scalars(select(Engagement).where(Engagement.client_id == cw.prospect.id)))
    assert sorted(e.type for e in es) == ["initial_assessment", "ll144_bias_audit"]
    assert all(e.status == "draft" for e in es)
    audit = next(e for e in es if e.type == "initial_assessment")
    com = cw.db.scalar(select(EngagementCommercial).where(EngagementCommercial.engagement_id == audit.id))
    assert com.fee_total == 35000 + 4500 and [m["amount"] for m in com.milestones] == [19750, 19750]
    codes = {ln.catalog_code for ln in cw.db.scalars(select(OrderLine).where(OrderLine.engagement_id == audit.id))}
    assert codes == {"A-02b", "A-05"}
    # the wizard opens the audit engagement (the latest for the client), with the opportunity's contacts on it
    latest = cw.db.scalar(select(Engagement).where(Engagement.client_id == cw.prospect.id).order_by(Engagement.created_at.desc()).limit(1))
    assert latest.id == audit.id
    contacts = list(cw.db.scalars(select(ClientContact).where(ClientContact.engagement_id == audit.id)))
    assert [c.email for c in contacts] == ["dana@acme.example"]
    kinds = [i["kind"] for i in h.items]
    assert kinds[:2] == ["client", "order"] and kinds.count("engagement") == 2


def test_subscription_entitlements_hours_bank_and_retainer(cw, fake_catalog):
    _go(cw, data_region="eu", support_level="Business hours")
    sub = cw.db.scalar(select(Subscription).where(Subscription.organization_id == cw.prospect.id, Subscription.end_on.is_(None)))
    assert sub.plan == "monitor_plus" and sub.tier == "11–50 systems" and sub.data_region == "eu" and sub.term_end_on is not None
    assert cw.db.get(Organization, cw.prospect.id).subscription_plan == "monitor_plus"
    ents = {e.key: e.limit for e in cw.db.scalars(select(Entitlement).where(Entitlement.subscription_id == sub.id))}
    assert ents == {"ai_systems": 50, "seats": 5, "advisor_hours": 10, "tracing_systems": 2}
    bank = cw.db.scalar(select(HoursBank).where(HoursBank.organization_id == cw.prospect.id))
    assert bank.hours_purchased == 20 and bank.code == "M-13"
    ret = cw.db.scalar(select(Retainer).where(Retainer.organization_id == cw.prospect.id))
    assert ret.type == "incident_response" and ret.monthly_fee == 1000 and ret.hourly_rate == 350 and ret.status == "standing"


def test_notifies_futran_and_sends_nothing_to_the_client(cw, fake_catalog):
    _go(cw)
    to = {(n.user_id, n.kind) for n in cw.db.scalars(select(Notification))}
    assert (cw.chief.id, "handoff_engagements") in to and (cw.fadmin.id, "handoff_client_setup") in to and (cw.fadmin.id, "handoff_billing") in to
    assert not [m for m in cw.db.scalars(select(OutboxMessage)) if any("acme.example" in t for t in m.to or [])]


def test_runs_once_per_proposal(cw, fake_catalog):
    h1 = _go(cw)
    p, a = proposal_for(cw, STANDARD_LINES())
    h2 = handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    assert h1.id == h2.id
    assert len(list(cw.db.scalars(select(Order)))) == 1 and len(list(cw.db.scalars(select(Handoff)))) == 1


def test_a_failure_leaves_nothing_behind(cw, fake_catalog, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("partner module failed")

    monkeypatch.setattr(handoff, "_commission", boom)
    p, a = proposal_for(cw, STANDARD_LINES())
    try:
        handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    except RuntimeError:
        pass
    cw.db.commit()
    assert cw.db.scalar(select(Order)) is None and cw.db.scalar(select(Engagement).where(Engagement.client_id == cw.prospect.id)) is None
    assert cw.db.get(Organization, cw.prospect.id).status == "prospect"


def test_partner_line_says_not_needed_without_a_partner(cw, fake_catalog):
    h = _go(cw)
    item = next(i for i in h.items if i["kind"] == "commission")
    assert item["status"] == "Not needed"


def test_works_without_the_catalog_from_the_proposal_lines_alone(cw):
    h = _go(cw, [line("A-02b", 1, 35000), line("M-01e", 1, 36000, periods=1)])
    order_lines = {ln.catalog_code: ln for ln in cw.db.scalars(select(OrderLine).where(OrderLine.order_id == h.order_id))}
    assert order_lines["M-01e"].recurring and not order_lines["A-02b"].recurring
    assert any(i["kind"] == "engagement" for i in h.items)


def test_fractional_officer_and_separate_team_lines_need_independence_confirmation(cw, fake_catalog):
    h = _go(cw, [line("A-02b", 1, 35000), line("X-01", 1, 6000, value=72000)])
    assert h.needs_separate_team == ["X-01"]
    ret = cw.db.scalar(select(Retainer).where(Retainer.organization_id == cw.prospect.id))
    assert ret.type == "fractional_officer" and ret.monthly_hours == 16


def test_entitlements_from_a_price_list_row_without_an_entitlement_key(cw, fake_catalog):
    """The starter price list names the tier in the item ("Monitor, up to 10 systems"; "Alert packs, 1–3 states") and
    uses its own words for included quantities ({"systems": 50, "docs": 5}); only entitlement keys become limits."""
    from app.commercial import catalog as cat

    fake_catalog["M-01a"] = cat.Item(code="M-01a", name="Monitor, up to 10 systems", billing="annual", periods_per_year=1, list_price=12000)
    fake_catalog["M-03a"] = cat.Item(code="M-03a", name="Alert packs, 1–3 states", billing="quarterly", periods_per_year=4, list_price=4200)
    fake_catalog["M-06a"] = cat.Item(code="M-06a", name="Evidence vault, base", billing="annual", periods_per_year=1, list_price=2400,
                                     included_quantities={"gb": 50, "docs": 5})
    _go(cw, [line("M-01a", 1, 12000, periods=1, value=12000), line("M-03a", 1, 4200, periods=4, value=16800), line("M-06a", 1, 2400, periods=1, value=2400)])
    sub = cw.db.scalar(select(Subscription).where(Subscription.organization_id == cw.prospect.id, Subscription.end_on.is_(None)))
    ents = {e.key: e.limit for e in cw.db.scalars(select(Entitlement).where(Entitlement.subscription_id == sub.id))}
    assert sub.plan == "monitor" and sub.tier == "up to 10 systems"
    assert ents == {"ai_systems": 10, "alert_packs": 3, "vault_gb": 50}
