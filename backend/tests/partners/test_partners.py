"""G-11 partners and referrals (spec B11): partner records, commissions on wins from the accepted proposal's first-year
value, law firms never get a commission (bar rules), referrals in and out, and commission values hidden from Auditors."""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.partners import service as partners
from app.partners.models import Commission, Partner, Referral
from app.sales.models import Opportunity
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def pw(db, client):
    f = make_org(db, type="futran")
    w = SimpleNamespace(db=db, client=client, futran=f)
    w.sm = make_user(db, f, roles=["sales_manager"], name="Sally Manager", email="sally@futran.test")
    w.officer = make_user(db, f, roles=["sales_team"], name="Raj Mehta", email="raj@futran.test")
    w.fadmin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    w.auditor = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    w.org = make_org(db, name="Metro Retail Inc.", status="active")
    w.ats = Partner(organization_id=f.id, name="Greenhouse partner desk", type="ats_vendor", commission_rule={"rate_pct": 15, "basis": "first_year_value"}, status="active")
    w.law = Partner(organization_id=f.id, name="Employment law firm", type="law_firm", commission_rule=None, status="active")
    db.add_all([w.ats, w.law])
    w.opp = Opportunity(organization_id=w.org.id, trigger="manual", service="Initial assessment", owner_id=w.officer.id, stage="won", value=60000)
    w.opp2 = Opportunity(organization_id=w.org.id, trigger="manual", service="LL144 audit", owner_id=w.officer.id, stage="won", value=20000)
    db.add_all([w.opp, w.opp2])
    db.commit()
    w.order = SimpleNamespace(id="ord-1", ref="ORD-0172", organization_id=w.org.id, start_on=date(2026, 11, 2))
    w.as_ = lambda u: login_as(client, db, u)
    return w


def _refer(w, partner, opp):
    partners.record_referral(w.db, w.sm, partner, direction="in", organization_id=opp.organization_id, opportunity_id=opp.id, note="Intro call")


def test_commission_on_win_is_15_percent_of_first_year_value(pw):
    _refer(pw, pw.ats, pw.opp)
    c = partners.commission_for_win(pw.db, pw.opp, pw.order, 52800.0)
    assert isinstance(c, Commission)
    assert (c.partner_id, c.opportunity_id, c.order_id, c.base_value, c.rate, c.amount, c.status) == (pw.ats.id, pw.opp.id, "ord-1", 52800.0, 15.0, 7920.0, "due")
    assert c.due_on == date(2026, 12, 2) and c.organization_id == pw.org.id
    # idempotent: a second call (a retried hand-off) returns the same row
    assert partners.commission_for_win(pw.db, pw.opp, pw.order, 52800.0).id == c.id
    assert pw.db.scalar(select(AuditLog).where(AuditLog.action == "partner.commission_created")) is not None


def test_opportunity_partner_id_is_used_when_r2_adds_it(pw):
    pw.opp.partner_id = pw.ats.id  # the column R2 adds; a plain attribute here
    c = partners.commission_for_win(pw.db, pw.opp, pw.order, 10000.0)
    assert c is not None and c.amount == 1500.0


def test_law_firms_never_get_a_commission(pw):
    _refer(pw, pw.law, pw.opp)
    assert partners.commission_for_win(pw.db, pw.opp, pw.order, 52800.0) is None
    # even a rule written straight into the row does not pay a law firm
    pw.law.commission_rule = {"rate_pct": 10}
    pw.db.flush()
    assert partners.commission_for_win(pw.db, pw.opp, pw.order, 52800.0) is None
    assert pw.db.scalar(select(Commission)) is None


def test_no_partner_no_commission(pw):
    assert partners.commission_for_win(pw.db, pw.opp, pw.order, 52800.0) is None


def test_commission_rule_cannot_be_set_for_a_law_firm(pw):
    pw.as_(pw.sm)
    r = pw.client.post("/api/v1/staff/partners", json={"name": "Privacy and EU law firm", "type": "law_firm", "rate_pct": 10})
    assert r.status_code == 422
    r = pw.client.post("/api/v1/staff/partners", json={"name": "Privacy and EU law firm", "type": "law_firm"})
    assert r.status_code == 200
    row = next(p for p in r.json()["partners"] if p["name"] == "Privacy and EU law firm")
    assert row["commission_rule"] is None and "bar rules" in row["commission_label"]
    r = pw.client.patch(f"/api/v1/staff/partners/{pw.law.id}", json={"rate_pct": 5})
    assert r.status_code == 422


def test_partner_list_counts_and_commissions(pw):
    _refer(pw, pw.ats, pw.opp)
    partners.record_referral(pw.db, pw.sm, pw.law, direction="out", organization_id=pw.org.id, note="Legal opinion on LL144 applicability")
    partners.commission_for_win(pw.db, pw.opp, pw.order, 52800.0)
    pw.db.commit()
    pw.as_(pw.sm)
    v = pw.client.get("/api/v1/staff/partners").json()
    ats = next(p for p in v["partners"] if p["id"] == pw.ats.id)
    law = next(p for p in v["partners"] if p["id"] == pw.law.id)
    assert ats["referred_in"] == 1 and ats["referred_out"] == 0 and ats["commission_due"] == 7920.0 and ats["commission_label"] == "15% of first-year contract value"
    assert law["referred_out"] == 1 and law["commission_due"] is None
    assert v["commissions"][0]["amount"] == 7920.0 and v["commissions"][0]["order_ref"] == "ORD-0172"
    assert {r["direction"] for r in v["referrals"]} == {"in", "out"}


def test_sales_officer_sees_partners_without_money_and_auditors_see_nothing(pw):
    _refer(pw, pw.ats, pw.opp)
    partners.commission_for_win(pw.db, pw.opp, pw.order, 52800.0)
    pw.db.commit()
    pw.as_(pw.officer)
    v = pw.client.get("/api/v1/staff/partners").json()
    assert v["commissions"] is None
    for p in v["partners"]:
        assert p["commission_due"] is None and p["won_value"] is None and p["commission_rule"] is None
    assert pw.client.post("/api/v1/staff/partners", json={"name": "X", "type": "other"}).status_code == 403
    pw.as_(pw.auditor)
    assert pw.client.get("/api/v1/staff/partners").status_code == 403


def test_commissions_are_settled_and_feed_the_billing_export(pw):
    _refer(pw, pw.ats, pw.opp)
    c = partners.commission_for_win(pw.db, pw.opp, pw.order, 52800.0)
    pw.db.commit()
    due = partners.commissions_due(pw.db, date(2026, 12, 1), date(2026, 12, 31), None)
    assert due == [{"id": c.id, "organization_id": pw.org.id, "amount": 7920.0, "order_ref": "ORD-0172", "partner_name": "Greenhouse partner desk", "status": "due"}]
    assert partners.commissions_due(pw.db, date(2026, 11, 1), date(2026, 11, 30), None) == []
    assert partners.commissions_due(pw.db, date(2026, 12, 1), date(2026, 12, 31), "another-client") == []
    pw.as_(pw.officer)
    assert pw.client.post(f"/api/v1/staff/partners/commissions/{c.id}/paid").status_code == 403
    pw.as_(pw.sm)
    r = pw.client.post(f"/api/v1/staff/partners/commissions/{c.id}/paid")
    assert r.status_code == 200 and r.json()["commissions"][0]["status"] == "paid"
    r = pw.client.post(f"/api/v1/staff/partners/commissions/{c.id}/void", json={"reason": "x"})
    assert r.status_code == 409  # a paid commission is not voided


def test_billing_export_carries_the_commission_row(pw):
    from app.commercial import plans

    _refer(pw, pw.ats, pw.opp)
    partners.commission_for_win(pw.db, pw.opp, pw.order, 52800.0)
    pw.db.commit()
    rows = plans._commission_rows(pw.db, "2026-12", date(2026, 12, 1), date(2026, 12, 31), None)
    assert len(rows) == 1 and rows[0][6] == "X-07" and rows[0][9] == "7920.00"


def test_referrals_in_and_out_are_recorded(pw):
    pw.as_(pw.sm)
    r = pw.client.post(f"/api/v1/staff/partners/{pw.law.id}/referrals", json={"direction": "out", "organization_id": pw.org.id, "note": "Legal opinion"})
    assert r.status_code == 200
    r = pw.client.post(f"/api/v1/staff/partners/{pw.ats.id}/referrals", json={"direction": "in", "opportunity_id": pw.opp2.id, "note": "Joint customer"})
    assert r.status_code == 200
    refs = list(pw.db.scalars(select(Referral)))
    assert {(x.direction, x.partner_id) for x in refs} == {("out", pw.law.id), ("in", pw.ats.id)}
    assert next(x for x in refs if x.direction == "in").organization_id == pw.org.id  # taken from the opportunity
    assert pw.client.post(f"/api/v1/staff/partners/{pw.ats.id}/referrals", json={"direction": "sideways"}).status_code == 422
