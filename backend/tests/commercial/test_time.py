"""G-03: weekly timesheets for all Futran staff, approval, hours banks (80% alert, overage priced from the price list),
retainers (activating the incident retainer opens an incident engagement and starts billable time), standard cost per
hour (Futran Admin) and the margin view (Chief Auditor and Sales Manager)."""
from datetime import date, timedelta

from sqlalchemy import select

from app.commercial import handoff, plans
from app.commercial.models import EngagementCommercial, HoursBank, Retainer, TimeEntry
from app.engagements.models import Engagement, EngagementTeam
from app.notifications.models import Notification
from tests.commercial.conftest import STANDARD_LINES, proposal_for
from tests.factories import make_user

MON = date(2026, 11, 9)


def _row(target, activity, hours, billable=True, note=None):
    return {"target": target, "activity": activity, "billable": billable, "note": note, "hours": {(MON + timedelta(days=i)).isoformat(): h for i, h in enumerate(hours) if h}}


def _week(cw, rows):
    return cw.client.put(f"/api/v1/staff/time/{MON.isoformat()}", json={"rows": rows})


def _won(cw):
    p, a = proposal_for(cw, STANDARD_LINES())
    handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.db.commit()
    return cw.db.scalar(select(HoursBank)), cw.db.scalar(select(Retainer))


def test_every_futran_person_keeps_a_weekly_timesheet(cw):
    for u in (cw.auditor, cw.sales, cw.fadmin):
        cw.as_(u)
        assert cw.client.get(f"/api/v1/staff/time/{MON.isoformat()}").status_code == 200
    cw.as_(cw.caico)
    assert cw.client.get(f"/api/v1/staff/time/{MON.isoformat()}").status_code in (403, 404)


def test_auditor_logs_time_against_their_engagement_and_internal_work(cw):
    cw.as_(cw.auditor)
    r = _week(cw, [_row(f"engagement:{cw.engagement.id}", "fieldwork", [3, 4, 4, 4]), _row("internal", "other", [2, 0, 0, 2.5], billable=False, note="Methodology")])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total"] == 19.5 and d["billable_total"] == 15 and d["status"] == "draft"
    assert {t["key"] for t in d["targets"]} >= {f"engagement:{cw.engagement.id}", "internal"}
    # not on the team: refused
    other = Engagement(organization_id=cw.org.id, client_id=cw.org.id, name="Other", status="in_progress")
    cw.db.add(other)
    cw.db.commit()
    r = _week(cw, [_row(f"engagement:{other.id}", "fieldwork", [1])])
    assert r.status_code == 422
    # internal time is never billable, and activities come from the list
    assert _week(cw, [_row("internal", "other", [1], billable=True)]).status_code == 422
    assert _week(cw, [_row(f"engagement:{cw.engagement.id}", "coffee", [1])]).status_code == 422
    assert _week(cw, [_row(f"engagement:{cw.engagement.id}", "fieldwork", [25])]).status_code == 422


def test_submit_and_the_manager_approves_not_the_author(cw):
    cw.as_(cw.auditor)
    _week(cw, [_row(f"engagement:{cw.engagement.id}", "fieldwork", [3])])
    assert cw.client.post(f"/api/v1/staff/time/{MON.isoformat()}/submit").json()["status"] == "submitted"
    assert _week(cw, [_row(f"engagement:{cw.engagement.id}", "fieldwork", [5])]).status_code == 409  # submitted weeks are locked
    assert cw.db.scalar(select(Notification).where(Notification.user_id == cw.em.id, Notification.kind == "timesheet_submitted")) is not None
    assert cw.client.post(f"/api/v1/staff/time/{MON.isoformat()}/decide", json={"user_id": cw.auditor.id, "approve": True}).status_code == 403
    cw.as_(cw.em)
    q = cw.client.get("/api/v1/staff/time-approvals").json()
    assert [w["user_name"] for w in q] == ["Alex Auditor"]
    r = cw.client.post(f"/api/v1/staff/time/{MON.isoformat()}/decide", json={"user_id": cw.auditor.id, "approve": True})
    assert r.status_code == 200, r.text
    assert all(t.status == "approved" and t.approved_by == cw.em.id for t in cw.db.scalars(select(TimeEntry)))


def test_hours_bank_balance_80_percent_alert_and_overage(cw, fake_catalog):
    bank, _ = _won(cw)
    cw.as_(cw.chief)  # the bank is Acme's: logged by someone who may log to it
    r = _week(cw, [_row(f"bank:{bank.id}", "advisory", [8, 8])])
    assert r.status_code == 200, r.text
    assert cw.db.scalar(select(Notification).where(Notification.kind == "hours_bank_80")) is not None
    banks = cw.client.get("/api/v1/staff/hours-banks").json()
    b = next(x for x in banks["banks"] if x["id"] == bank.id)
    assert b["used"] == 16 and b["remaining"] == 4 and b["pct"] == 80
    _week(cw, [_row(f"bank:{bank.id}", "advisory", [8, 8, 6])])
    rows = plans.billing_rows(cw.db, "2026-11", cw.prospect.id)
    over = next(r for r in rows if r[5] == "hours_overage")
    assert float(over[8]) == 2 and float(over[9]) == 300  # priced from the catalog (M-13 list)


def test_activating_the_incident_retainer_opens_an_incident_engagement_and_billable_time(cw, fake_catalog):
    _, ret = _won(cw)
    cw.as_(cw.auditor)
    assert cw.client.post(f"/api/v1/staff/retainers/{ret.id}/activate", json={"reason": "Chatbot leak"}).status_code in (403, 404)
    cw.as_(cw.chief)
    r = cw.client.post(f"/api/v1/staff/retainers/{ret.id}/activate", json={"reason": "Chatbot data leak reported by the client"})
    assert r.status_code == 200, r.text
    cw.db.expire_all()
    ret = cw.db.get(Retainer, ret.id)
    e = cw.db.get(Engagement, ret.incident_engagement_id)
    assert ret.status == "activated" and e.type == "incident_response" and e.client_id == cw.prospect.id
    # the audit engagement stays the one the client page and the wizard open
    from app.engagements.wizard_router import _load
    from app.auth.deps import Actor
    from app.tenancy.models import Organization

    chief = Actor(user=cw.chief, organization=cw.futran, roles=list(__import__("app.tenancy.service", fromlist=["roles_of"]).roles_of(cw.db, cw.chief.id)))
    assert _load(cw.db, chief, cw.prospect.id)[1].type == "initial_assessment" and e.status == "draft"
    r = _week(cw, [_row(f"retainer:{ret.id}", "incident_response", [3, 5.5])])
    assert r.status_code == 200, r.text
    rows = plans.billing_rows(cw.db, "2026-11", cw.prospect.id)
    hrs = next(r for r in rows if r[5] == "retainer_hours")
    assert float(hrs[8]) == 8.5 and float(hrs[9]) == 350


def test_standard_cost_is_set_by_the_futran_admin_and_margins_are_for_chief_and_sales_manager(cw):
    cw.db.add(EngagementCommercial(organization_id=cw.org.id, engagement_id=cw.engagement.id, fee_total=43500, milestones=[]))
    cw.db.commit()
    cw.as_(cw.chief)
    assert cw.client.post("/api/v1/staff/standard-costs", json={"role": "auditor", "cost_per_hour": 90, "effective_from": "2026-01-01"}).status_code == 403
    cw.as_(cw.fadmin)
    for role, cost in (("auditor", 90), ("engagement_manager", 120)):
        r = cw.client.post("/api/v1/staff/standard-costs", json={"role": role, "cost_per_hour": cost, "effective_from": "2026-01-01"})
        assert r.status_code == 200, r.text
    cw.as_(cw.auditor)
    _week(cw, [_row(f"engagement:{cw.engagement.id}", "fieldwork", [10, 10])])
    cw.as_(cw.em)
    _week(cw, [_row(f"engagement:{cw.engagement.id}", "report", [2])])
    cw.as_(cw.chief)
    m = cw.client.get("/api/v1/staff/margins")
    assert m.status_code == 200
    row = next(x for x in m.json()["engagements"] if x["engagement_id"] == cw.engagement.id)
    assert row["hours"] == 22 and row["cost"] == 20 * 90 + 2 * 120 and row["fee"] == 43500 and row["margin_pct"] == round(100 * (43500 - 2040) / 43500)
    mgr = make_user(cw.db, cw.futran, roles=["sales_manager"], name="Mia Manager", email="mia@futran.test")
    cw.db.commit()
    cw.as_(mgr)
    assert cw.client.get("/api/v1/staff/margins").status_code == 200
    for u in (cw.auditor, cw.sales, cw.em):
        cw.as_(u)
        assert cw.client.get("/api/v1/staff/margins").status_code == 403
