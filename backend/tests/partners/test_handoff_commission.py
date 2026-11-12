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
