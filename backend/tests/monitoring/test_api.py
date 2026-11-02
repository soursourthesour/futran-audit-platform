"""Screen 31 endpoints: the client's dashboard, Futran's view on the client page, the Futran Admin's plan setting, acting
on a result, the SOC 2 expiry date on the document register, and the daily job."""
from datetime import date, timedelta

import pytest

from app.monitoring import registry
from app.monitoring.models import MonitorResult
from app.monitoring.registry import CheckOutcome, register_check


@pytest.fixture
def checks(monkeypatch):
    monkeypatch.setattr(registry, "CHECKS", {})
    monkeypatch.setattr(registry, "load_checks", lambda: registry.CHECKS)
    box = {"out": [CheckOutcome("s1", "AIS-001 Résumé screening", "failed", "LL144 audit 14 months old", "/register/s1", action="start_reassessment", register_system_id="s1")]}
    register_check("demo_check", "LL144 bias audit older than 12 months", "high", "monthly", "system", lambda db, org: list(box["out"]))
    return box


def _plan(w, plan="monitor", **extra):
    w.as_(w.fadmin)
    return w.client.put(f"/api/v1/clients/{w.org.id}/subscription", json={"plan": plan, **extra})


def test_only_the_futran_admin_sets_the_plan(w):
    w.as_(w.chief)
    assert w.client.put(f"/api/v1/clients/{w.org.id}/subscription", json={"plan": "monitor"}).status_code == 403
    w.as_(w.admin)
    assert w.client.put(f"/api/v1/clients/{w.org.id}/subscription", json={"plan": "monitor"}).status_code in (403, 404)
    r = _plan(w, next_review_on=(date.today() + timedelta(days=120)).isoformat())
    assert r.status_code == 200 and r.json()["plan"] == "monitor"


def test_audit_only_client_sees_what_monitoring_offers(w):
    w.as_(w.caico)
    r = w.client.get("/api/v1/monitoring")
    assert r.status_code == 200 and r.json()["plan"] == "audit_only" and r.json()["kpis"] is None and r.json()["offers"]
    assert w.client.post("/api/v1/monitoring/run").status_code == 409


def test_caico_runs_checks_and_sees_the_dashboard(w, checks):
    _plan(w)
    w.as_(w.caico)
    assert w.client.post("/api/v1/monitoring/run").status_code == 200
    d = w.client.get("/api/v1/monitoring").json()
    assert d["kpis"]["failed"] == 1 and d["needs_action"][0]["action_label"] == "Start reassessment" and d["can_act"]


def test_people_without_the_right_cannot_open_monitoring(w):
    for u in (w.contrib, w.hr_lead):
        w.as_(u)
        assert w.client.get("/api/v1/monitoring").status_code == 403


def test_futran_auditor_sees_the_clients_monitoring_and_not_another(w, checks):
    _plan(w)
    w.as_(w.caico)
    w.client.post("/api/v1/monitoring/run")
    w.as_(w.auditor)
    r = w.client.get(f"/api/v1/clients/{w.org.id}/monitoring")
    assert r.status_code == 200 and r.json()["kpis"]["failed"] == 1 and not r.json()["can_set_plan"] and not r.json()["can_act"]
    w.as_(w.other_auditor)
    assert w.client.get(f"/api/v1/clients/{w.org.id}/monitoring").status_code == 404


def test_start_reassessment_needs_the_impact_triggers(w, checks, monkeypatch):
    import sys
    import types

    calls = []
    mod = types.ModuleType("app.impact.triggers")
    mod.raise_trigger = lambda db, register_system_id, type, source, **kw: calls.append((register_system_id, type, source)) or object()
    monkeypatch.setitem(sys.modules, "app.impact.triggers", mod)
    _plan(w)
    w.as_(w.caico)
    w.client.post("/api/v1/monitoring/run")
    rid = w.db.query(MonitorResult).filter_by(status="failed").one().id
    r = w.client.post(f"/api/v1/monitoring/results/{rid}/act")
    assert r.status_code == 200 and calls == [("s1", "failed_monitor_check", "monitor")]
    assert w.client.post(f"/api/v1/monitoring/results/{rid}/act").status_code == 409
    w.as_(w.other_admin)
    assert w.client.post(f"/api/v1/monitoring/results/{rid}/act").status_code in (404, 409)


def test_soc2_expiry_is_recorded_on_a_received_request(w):
    from datetime import datetime

    from app.docrequests.models import DocumentRequest
    from app.reference.models import DocumentCatalogItem

    item = DocumentCatalogItem(category=6, category_title="Vendor", code="DR-603", title="Vendor SOC 2 Type II or ISO 27001 certificates")
    w.db.add(item)
    w.db.flush()
    r = DocumentRequest(organization_id=w.org.id, engagement_id=w.engagement.id, catalog_item_id=item.id, requested_at=datetime(2026, 1, 1), status="pending")
    w.db.add(r)
    w.db.commit()
    w.as_(w.caico)
    assert w.client.put(f"/api/v1/document-requests/{r.id}/expiry", json={"expires_on": "2027-03-31"}).status_code == 409  # not received yet
    r.status = "received"
    w.db.commit()
    out = w.client.put(f"/api/v1/document-requests/{r.id}/expiry", json={"expires_on": "2027-03-31"})
    assert out.status_code == 200 and out.json()["expires_on"] == "2027-03-31"
    w.as_(w.other_admin)
    assert w.client.put(f"/api/v1/document-requests/{r.id}/expiry", json={"expires_on": "2027-04-30"}).status_code == 404


def test_the_daily_run_includes_the_monthly_monitoring_job(w, settings, checks):
    from app.notifications.jobs import JOBS, run_daily

    assert "monitoring_monthly" in JOBS
    _plan(w)
    out = run_daily(w.db, settings, date.today())
    assert out["monitoring_monthly"] == 1


def test_a_follow_up_without_a_handler_is_offered_as_a_link(w, checks):
    checks["out"] = [CheckOutcome("s9", "AIS-009", "failed", "Audit report missing", "/register/s9", action="request_report")]
    _plan(w)
    w.as_(w.caico)
    w.client.post("/api/v1/monitoring/run")
    row = w.client.get("/api/v1/monitoring").json()["needs_action"][0]
    assert row["action_kind"] == "link" and row["action_link"] == "/register/s9"
    rid = w.db.query(MonitorResult).filter_by(status="failed").one().id
    assert w.client.post(f"/api/v1/monitoring/results/{rid}/act").status_code == 409


def test_training_reminders_go_through_the_training_service(w, checks, monkeypatch):
    import sys
    import types

    sent = []
    mod = types.ModuleType("app.training.service")
    mod.send_reminders = lambda db, settings, actor, org_id, module_code=None: sent.append(org_id) or 7
    monkeypatch.setitem(sys.modules, "app.training.service", mod)
    registry.CHECKS.clear()
    register_check("training_below_target", "AI literacy training below target", "medium", "monthly", "department",
                   lambda db, org: [CheckOutcome("d1", "Sales and Marketing", "attention", "54% complete", "/training", action="send_reminder")])
    _plan(w)
    w.as_(w.caico)
    w.client.post("/api/v1/monitoring/run")
    row = w.client.get("/api/v1/monitoring").json()["needs_action"][0]
    assert row["action_kind"] == "server"
    r = w.client.post(f"/api/v1/monitoring/results/{row['id']}/act")
    assert r.status_code == 200 and sent == [w.org.id] and "7" in r.json()["message"]


def test_the_plan_note_is_for_futran_staff_only(w):
    assert _plan(w, note="Discounted 30%; push Monitor Plus at renewal").json()["subscription"]["note"] == "Discounted 30%; push Monitor Plus at renewal"
    w.as_(w.chief)
    assert w.client.get(f"/api/v1/clients/{w.org.id}/monitoring").json()["subscription"]["note"] == "Discounted 30%; push Monitor Plus at renewal"
    for user in (w.caico, w.admin):
        w.as_(user)
        r = w.client.get("/api/v1/monitoring")
        assert r.status_code == 200 and r.json()["plan"] == "monitor"
        assert "Discounted" not in r.text and r.json()["subscription"]["note"] is None
