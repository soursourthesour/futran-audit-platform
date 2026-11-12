"""G-01: plan settings, daily usage, soft limits (90% notice and opportunity, 100% over plan), hard limits for api_access
and trust_center, renewals 90 days before an order line ends, and the formula-safe monthly billing export."""
import csv
import io
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.commercial import handoff, plans
from app.commercial.models import BillingExportRun, OrderLine, UsageRecord
from app.notifications.models import Notification
from app.register.models import RegisterSystem
from app.sales.models import Opportunity
from tests.commercial.conftest import STANDARD_LINES, line, proposal_for


def _won(cw, lines=None, **terms):
    p, a = proposal_for(cw, lines or STANDARD_LINES(), start_on="2026-11-02", **terms)
    h = handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.db.commit()
    return h


def _systems(cw, org_id, n, stage="live"):
    base = len(list(cw.db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org_id))))
    for i in range(n):
        cw.db.add(RegisterSystem(organization_id=org_id, reference=f"AIS-{base + i:03d}", name=f"System {base + i}", type="other", sourcing="vendor", stage=stage))
    cw.db.commit()


def test_existing_plans_read_as_before(cw):
    from app.monitoring import service as mon

    sub = mon.set_plan(cw.db, cw.fadmin, cw.org, "monitor")
    cw.db.commit()
    v = plans.plan_view(cw.db, cw.org)
    assert v["plan"]["plan"] == "monitor" and v["entitlements"] == [] and v["order_lines"] == []
    assert sub.tier is None and sub.data_region is None and sub.auto_renew is None


def test_usage_is_measured_daily_and_soft_limit_warns_at_90_percent(cw, fake_catalog):
    _won(cw)
    _systems(cw, cw.prospect.id, 46)
    _systems(cw, cw.prospect.id, 3, stage="retired")  # retired systems do not count
    n = plans.run_daily_usage(cw.db, None, datetime(2026, 11, 20, 10))
    cw.db.commit()
    assert n >= 1
    rec = cw.db.scalar(select(UsageRecord).where(UsageRecord.organization_id == cw.prospect.id, UsageRecord.key == "ai_systems"))
    assert rec.value == 46 and rec.measured_on == date(2026, 11, 20)
    opp = cw.db.scalar(select(Opportunity).where(Opportunity.trigger == "entitlement_limit"))
    assert opp is not None and opp.organization_id == cw.prospect.id and "92%" in opp.why_now
    assert cw.db.scalar(select(Notification).where(Notification.kind == "entitlement_limit", Notification.user_id == cw.sales.id)) is not None
    # a second day does not repeat the notice or the opportunity
    plans.run_daily_usage(cw.db, None, datetime(2026, 11, 21, 10))
    cw.db.commit()
    assert len(list(cw.db.scalars(select(Opportunity).where(Opportunity.trigger == "entitlement_limit")))) == 1
    assert len(list(cw.db.scalars(select(UsageRecord).where(UsageRecord.key == "ai_systems")))) == 2


def test_over_plan_shows_to_futran_and_the_client_keeps_working(cw, fake_catalog):
    _won(cw)
    _systems(cw, cw.prospect.id, 53)
    plans.run_daily_usage(cw.db, None, datetime(2026, 11, 20, 10))
    cw.db.commit()
    v = plans.plan_view(cw.db, cw.prospect)
    ai = next(e for e in v["entitlements"] if e["key"] == "ai_systems")
    assert ai["used"] == 53 and ai["limit"] == 50 and ai["over_plan"] and not ai["hard"]
    assert plans.feature_allowed(cw.db, cw.prospect.id, "ai_systems")


def test_hard_limits_only_for_api_access_and_trust_center(cw, fake_catalog):
    _won(cw)
    assert not plans.feature_allowed(cw.db, cw.prospect.id, "api_access")
    assert not plans.feature_allowed(cw.db, cw.prospect.id, "trust_center")
    # a client with no order keeps today's behaviour
    assert plans.feature_allowed(cw.db, cw.org.id, "api_access")


def test_renewal_opportunity_90_days_before_the_line_ends(cw, fake_catalog):
    _won(cw)
    end = cw.db.scalar(select(OrderLine).where(OrderLine.catalog_code == "M-01e")).end_on
    plans.run_daily_usage(cw.db, None, datetime.combine(end - timedelta(days=91), datetime.min.time()))
    assert cw.db.scalar(select(Opportunity).where(Opportunity.trigger == "renewal_due")) is None
    plans.run_daily_usage(cw.db, None, datetime.combine(end - timedelta(days=90), datetime.min.time()))
    plans.run_daily_usage(cw.db, None, datetime.combine(end - timedelta(days=89), datetime.min.time()))
    cw.db.commit()
    opps = list(cw.db.scalars(select(Opportunity).where(Opportunity.trigger == "renewal_due")))
    assert len(opps) == 1 and opps[0].organization_id == cw.prospect.id and opps[0].owner_id == cw.sales.id


def test_data_region_moves_only_with_a_migration_ticket(cw, fake_catalog):
    _won(cw, data_region="us")
    cw.as_(cw.fadmin)
    url = f"/api/v1/staff/clients/{cw.prospect.id}/plan"
    r = cw.client.patch(url, json={"data_region": "eu"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "migration_ticket"
    r = cw.client.patch(url, json={"data_region": "eu", "migration_ticket": "OPS-412", "support_level": "24x7", "auto_renew": True})
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["data_region"] == "eu" and r.json()["plan"]["support_level"] == "24x7"


def test_who_sees_and_edits_the_plan(cw, fake_catalog):
    _won(cw)
    url = f"/api/v1/staff/clients/{cw.prospect.id}/plan"
    for u in (cw.fadmin, cw.chief):
        cw.as_(u)
        assert cw.client.get(url).status_code == 200
    cw.as_(cw.chief)
    assert cw.client.patch(url, json={"support_level": "24x7"}).status_code == 403
    for u in (cw.auditor, cw.caico):
        cw.as_(u)
        assert cw.client.get(url).status_code in (403, 404)


def test_billing_export_is_formula_safe_and_lists_lines_due_and_overage(cw, fake_catalog):
    _won(cw)
    cw.prospect.name = "=HYPERLINK(evil)"
    _systems(cw, cw.prospect.id, 53)
    plans.run_daily_usage(cw.db, None, datetime(2026, 11, 20, 10))
    cw.db.commit()
    cw.as_(cw.fadmin)
    r = cw.client.post("/api/v1/staff/billing-export", json={"period": "2026-11", "client_id": cw.prospect.id})
    assert r.status_code == 200, r.text
    run = cw.db.get(BillingExportRun, r.json()["id"])
    rows = list(csv.DictReader(io.StringIO(run.content)))
    assert run.rows == len(rows) and rows
    assert all(not row["client_name"].startswith("=") for row in rows)
    kinds = {row["line_type"] for row in rows}
    assert {"order_line", "overage"} <= kinds
    m01 = next(row for row in rows if row["code"] == "M-01e")
    assert float(m01["amount"]) == 36000
    over = next(row for row in rows if row["line_type"] == "overage")
    assert over["code"] == "M-01e" and float(over["qty"]) == 3
    dl = cw.client.get(f"/api/v1/staff/billing-export/{run.id}.csv")
    assert dl.status_code == 200 and dl.headers["content-type"].startswith("text/csv")
    # all clients
    r = cw.client.post("/api/v1/staff/billing-export", json={"period": "2026-11"})
    assert r.status_code == 200 and r.json()["client_id"] is None
    cw.as_(cw.chief)
    assert cw.client.post("/api/v1/staff/billing-export", json={"period": "2026-11"}).status_code == 403


def test_monthly_export_runs_on_the_first(cw, fake_catalog):
    _won(cw)
    plans.run_daily_usage(cw.db, None, datetime(2026, 12, 1, 10))
    plans.run_daily_usage(cw.db, None, datetime(2026, 12, 1, 11))
    cw.db.commit()
    runs = list(cw.db.scalars(select(BillingExportRun)))
    assert len(runs) == 1 and runs[0].period == "2026-11" and runs[0].client_id is None
