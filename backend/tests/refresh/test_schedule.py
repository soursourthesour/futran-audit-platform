"""§25.3 step 1: the refresh runs on a schedule, every 14 days by default, through the daily jobs."""
from datetime import timedelta

from app.core.clock import utcnow
from app.refresh import schedule
from app.refresh.claude import FakeRefreshClient
from app.refresh.models import RefreshRun
from app.refresh.pipeline import get_run_setting


def test_schedule_runs_when_due_and_not_again_before_the_interval(db, lit, reg, settings, monkeypatch):
    calls = []
    monkeypatch.setattr(schedule, "CLIENT_FACTORY", lambda s: FakeRefreshClient({}, calls=calls))
    now = utcnow()
    out = schedule.run_scheduled(db, settings, now, background=False)
    assert out == 2  # law and litigation
    runs = db.query(RefreshRun).all()
    assert {r.kind for r in runs} == {"law", "litigation"} and all(r.trigger == "scheduled" and r.started_by is None for r in runs)
    assert schedule.run_scheduled(db, settings, now + timedelta(days=13), background=False) == 0
    assert schedule.run_scheduled(db, settings, now + timedelta(days=14, hours=1), background=False) == 2


def test_schedule_can_be_switched_off(db, lit, reg, settings, monkeypatch):
    monkeypatch.setattr(schedule, "CLIENT_FACTORY", lambda s: FakeRefreshClient({}))
    get_run_setting(db, "law").schedule_enabled = False
    get_run_setting(db, "litigation").schedule_enabled = False
    assert schedule.run_scheduled(db, settings, utcnow(), background=False) == 0


def test_no_client_no_scheduled_run(db, lit, reg, settings):
    assert schedule.run_scheduled(db, settings, utcnow(), background=False) == 0
    assert db.query(RefreshRun).count() == 0


def test_daily_jobs_include_the_refresh_jobs():
    from app.notifications.jobs import JOBS

    assert {"refresh_schedule", "refresh_reminders", "client_alert_dates", "opportunity_dates"} <= set(JOBS)
