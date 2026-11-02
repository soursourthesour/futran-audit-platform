"""Monitoring runs (spec §21 F3): only for clients on a Monitor plan, claimed once per run key, one result per object a
check looked at, and an alert to the CAICO and the assigned auditor once per new failure. Monitoring never changes a
signed report."""
from datetime import datetime, timedelta

import pytest

from app.core.errors import AppError
from app.monitoring import registry, service as mon
from app.monitoring.models import MonitorResult, MonitorRun, Subscription
from app.monitoring.registry import CheckOutcome, register_check
from app.notifications.models import Notification


@pytest.fixture
def checks(monkeypatch):
    """A scratch registry with one check whose outcomes a test sets."""
    monkeypatch.setattr(registry, "CHECKS", {})
    monkeypatch.setattr(registry, "load_checks", lambda: registry.CHECKS)
    box = {"out": []}
    register_check("demo_check", "Demo check", "high", "monthly", "system", lambda db, org: list(box["out"]))
    return box


def _monitor(w):
    mon.set_plan(w.db, w.fadmin, w.org, "monitor", next_review_on=w.today + timedelta(days=200))


def test_set_plan_records_a_subscription_and_the_organisation_plan(w):
    sub = mon.set_plan(w.db, w.fadmin, w.org, "monitor_plus", next_review_on=w.today + timedelta(days=90))
    assert w.org.subscription_plan == "monitor_plus" and sub.plan == "monitor_plus" and sub.start_on == w.today
    mon.set_plan(w.db, w.fadmin, w.org, "audit_only")
    assert w.org.subscription_plan == "audit_only"
    assert w.db.get(Subscription, sub.id).end_on == w.today
    with pytest.raises(AppError):
        mon.set_plan(w.db, w.fadmin, w.org, "gold")


def test_no_run_for_a_client_on_the_audit_only_plan(w, settings, checks):
    assert mon.run(w.db, settings, w.org, "manual", "manual:1") is None
    assert w.db.query(MonitorRun).count() == 0


def test_a_run_records_each_outcome_and_a_healthy_row_when_a_check_finds_nothing(w, settings, checks):
    _monitor(w)
    checks["out"] = [CheckOutcome("s1", "AIS-001 Résumé screening", "failed", "Last bias audit 14 months ago", "/register/s1", action="start_reassessment", register_system_id="s1"),
                     CheckOutcome("s2", "AIS-002 Chatbot", "attention", "Due in 20 days", None)]
    run = mon.run(w.db, settings, w.org, "manual", "manual:1")
    assert run.status == "completed" and run.counts == {"healthy": 0, "attention": 1, "failed": 1, "not_started": 0}
    checks["out"] = []
    run2 = mon.run(w.db, settings, w.org, "manual", "manual:2")
    assert run2.counts["healthy"] == 1


def test_a_check_that_raises_is_recorded_as_not_started(w, settings, checks, monkeypatch):
    _monitor(w)

    def boom(db, org):
        raise RuntimeError("no table")

    register_check("broken", "Broken check", "low", "monthly", "org", boom)
    run = mon.run(w.db, settings, w.org, "manual", "manual:1")
    r = w.db.query(MonitorResult).filter_by(run_id=run.id, status="not_started").one()
    assert "could not run" in r.detail


def test_the_same_run_key_is_claimed_once(w, settings, checks):
    _monitor(w)
    assert mon.run(w.db, settings, w.org, "monthly", "monthly:2026-11") is not None
    assert mon.run(w.db, settings, w.org, "monthly", "monthly:2026-11") is None
    assert w.db.query(MonitorRun).count() == 1


def test_a_new_failure_alerts_the_caico_and_the_assigned_auditor_once(w, settings, checks):
    _monitor(w)
    checks["out"] = [CheckOutcome("s1", "AIS-001 Résumé screening", "failed", "Overdue", "/register/s1")]
    mon.run(w.db, settings, w.org, "manual", "manual:1")
    mon.run(w.db, settings, w.org, "manual", "manual:2")  # still failing: no second alert
    to = {n.user_id for n in w.db.query(Notification).filter_by(kind="monitoring_check_failed")}
    assert to == {w.caico.id, w.auditor.id}
    assert w.db.query(Notification).filter_by(kind="monitoring_check_failed").count() == 2
    checks["out"] = [CheckOutcome("s1", "AIS-001 Résumé screening", "healthy", "Done", None)]
    mon.run(w.db, settings, w.org, "manual", "manual:3")
    checks["out"] = [CheckOutcome("s1", "AIS-001 Résumé screening", "failed", "Overdue again", None)]
    mon.run(w.db, settings, w.org, "manual", "manual:4")  # failed again after recovering: a new failure
    assert w.db.query(Notification).filter_by(kind="monitoring_check_failed").count() == 4


def test_monthly_job_runs_each_monitored_client_once_a_month(w, settings, checks):
    _monitor(w)
    now = datetime(2026, 11, 3, 10, 0)
    assert mon.run_monthly(w.db, settings, now) == 1
    assert mon.run_monthly(w.db, settings, now + timedelta(days=2)) == 0
    assert mon.run_monthly(w.db, settings, datetime(2026, 12, 1, 10, 0)) == 1
    assert w.db.query(MonitorRun).filter(MonitorRun.organization_id == w.other.id).count() == 0


def test_a_connector_sync_starts_a_run_for_a_monitored_client(w, settings, checks):
    from app.connectors import service as csvc

    csvc.upload(w.db, settings, w.admin, w.org, "expense_csv", "a.csv", b"Description,Department\nOPENAI *CHATGPT,HR\n")
    assert w.db.query(MonitorRun).count() == 0  # audit only
    _monitor(w)
    csvc.upload(w.db, settings, w.admin, w.org, "expense_csv", "b.csv", b"Description,Department\nOPENAI *CHATGPT,HR\n")
    assert w.db.query(MonitorRun).filter_by(trigger="sync").count() == 1


def test_a_run_changes_no_signed_report(w, settings, checks):
    from app.reports.models import Report

    _monitor(w)
    rep = Report(organization_id=w.org.id, engagement_id=w.engagement.id, version="v1.0", type="audit_report", status="final", body_md="Signed body", content_hash="h",
                 signed_by=w.chief.id, signed_at=datetime(2026, 1, 15))
    w.db.add(rep)
    w.db.commit()
    checks["out"] = [CheckOutcome("s1", "x", "failed", "y", None)]
    mon.run(w.db, settings, w.org, "manual", "manual:1")
    w.db.refresh(rep)
    assert (rep.body_md, rep.status, rep.updated_at <= datetime(2026, 12, 31)) == ("Signed body", "final", True)


def test_dashboard_counts_the_latest_run_and_lists_what_needs_action(w, settings, checks):
    _monitor(w)
    checks["out"] = [CheckOutcome("s1", "AIS-001", "failed", "Overdue", "/register/s1", action="start_reassessment", register_system_id="s1"),
                     CheckOutcome("s2", "AIS-002", "attention", "Soon", None), CheckOutcome("s3", "AIS-003", "healthy", "Fine", None)]
    mon.run(w.db, settings, w.org, "manual", "manual:1")
    d = mon.dashboard(w.db, w.org)
    assert d["plan"] == "monitor" and d["kpis"] == {"healthy": 1, "attention": 1, "failed": 1, "not_started": 0}
    assert [r["status"] for r in d["needs_action"]] == ["failed", "attention"]
    assert d["needs_action"][0]["check"] == "Demo check" and d["next_review_on"] == (w.today + timedelta(days=200)).isoformat()


def test_dashboard_for_audit_only_lists_what_monitoring_offers(w):
    d = mon.dashboard(w.db, w.org)
    assert d["plan"] == "audit_only" and d["kpis"] is None and len(d["offers"]) >= 4
