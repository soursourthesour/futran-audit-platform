"""The SM-13 hand-off (R5) records the partner commission through `partners.service.commission_for_win`."""
from sqlalchemy import select

from app.commercial import handoff
from app.partners.models import Commission, Partner
from tests.commercial.conftest import STANDARD_LINES, cw, fake_catalog, proposal_for  # noqa: F401


def _won_with(cw, ptype, rate):
    p = Partner(organization_id=cw.futran.id, name=f"{ptype} partner", type=ptype, commission_rule={"rate_pct": rate} if rate else None, status="active")
    cw.db.add(p)
    cw.db.flush()
    cw.opp.partner_id = p.id  # R2's column; set as an attribute so this test does not depend on it landing
    prop, acc = proposal_for(cw, STANDARD_LINES())
    h = handoff.create_from_acceptance(cw.db, prop, acc, cw.sales)
    cw.db.commit()
    return h, next(i for i in h.items if i["kind"] == "commission")


def test_handoff_creates_the_ats_vendor_commission(cw, fake_catalog):
    h, item = _won_with(cw, "ats_vendor", 15)
    assert item["status"] == "Created"
    c = cw.db.scalar(select(Commission))
    assert c.order_id == h.order_id and c.rate == 15 and c.amount == round(c.base_value * 0.15, 2) and c.base_value > 0


def test_handoff_creates_nothing_for_a_law_firm(cw, fake_catalog):
    _, item = _won_with(cw, "law_firm", None)
    assert item["status"] == "Not needed" and cw.db.scalar(select(Commission)) is None


def test_a_real_handoff_finds_the_partner_from_an_inbound_referral(cw, fake_catalog):
    """Fix pass 2: no partner_id set by hand; the referral recorded on the opportunity is enough."""
    from app.partners import service as partners

    p = Partner(organization_id=cw.futran.id, name="ATS partner", type="ats_vendor", commission_rule={"rate_pct": 15}, status="active")
    cw.db.add(p)
    cw.db.flush()
    partners.record_referral(cw.db, cw.sales, p, direction="in", opportunity_id=cw.opp.id, note="Intro")
    cw.db.commit()
    assert getattr(cw.opp, "partner_id", None) is None
    prop, acc = proposal_for(cw, STANDARD_LINES())
    h = handoff.create_from_acceptance(cw.db, prop, acc, cw.sales)
    cw.db.commit()
    item = next(i for i in h.items if i["kind"] == "commission")
    assert item["status"] == "Created"
    c = cw.db.scalar(select(Commission))
    assert c is not None and c.partner_id == p.id and c.order_id == h.order_id


def test_no_partner_still_says_not_needed(cw, fake_catalog):
    prop, acc = proposal_for(cw, STANDARD_LINES())
    h = handoff.create_from_acceptance(cw.db, prop, acc, cw.sales)
    item = next(i for i in h.items if i["kind"] == "commission")
    assert item["status"] == "Not needed" and "No partner" in str(item)
