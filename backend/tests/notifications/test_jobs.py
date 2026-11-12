from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.core import clock
from app.engagements.models import Engagement
from app.governance.models import Commitment
from app.invitations.models import Invitation
from app.invitations.service import invite_user
from app.mail.models import OutboxMessage
from app.notifications import jobs
from app.notifications.events import EVENTS
from app.notifications.models import Notification
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def test_events_table_covers_spec_14():
    assert len(EVENTS) == 9
    assert {e.key for e in EVENTS.values()} == {
        "engagement_submitted", "package_sent", "invitation_expiring", "sign_off_role_changed", "sign_off_awaiting",
        "evidence_request", "finding_returned", "remediation_done", "overdue_digest",
    }
    assert EVENTS["finding_returned"].channels == ("in_app",)
    assert EVENTS["sign_off_awaiting"].channels == ("in_app", "email")
    assert EVENTS["overdue_digest"].channels == ("digest",)


def _pending(db, live):
    cid, e, maria = live
    tom = User(organization_id=cid, name="Tom Reyes", email="tom@abc.test", status="invited")
    db.add(tom)
    db.flush()
    return tom


def test_invitation_48h_warning_once(client, db, live, settings, people):
    tom = _pending(db, live)
    invite_user(db, settings, people["aud"], tom)
    db.commit()
    inv = db.scalar(select(Invitation).where(Invitation.user_id == tom.id))
    soon = inv.expires_at - timedelta(hours=30)
    assert jobs.run_invitation_warnings(db, settings, soon) == 1
    assert jobs.run_invitation_warnings(db, settings, soon + timedelta(hours=2)) == 0
    mail = db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "invitation_expiring")).all()
    assert len(mail) == 1 and mail[0].to == ["tom@abc.test"]
    assert jobs.run_invitation_warnings(db, settings, inv.expires_at - timedelta(days=5)) == 0


def test_expired_invitation_marked_and_futran_notified(client, db, live, settings, people):
    tom = _pending(db, live)
    invite_user(db, settings, people["aud"], tom)
    db.commit()
    inv = db.scalar(select(Invitation).where(Invitation.user_id == tom.id))
    assert jobs.run_invitation_expiry(db, settings, inv.expires_at + timedelta(minutes=1)) >= 1  # other pending invitations from setup expire too
    db.expire_all()
    assert db.get(Invitation, inv.id).status == "expired"
    notes = db.scalars(select(Notification).where(Notification.kind == "invitation_expired")).all()
    tom_notes = [n for n in notes if "Tom Reyes" in n.title]
    assert people["chief"].id in {n.user_id for n in tom_notes}
    assert jobs.run_invitation_expiry(db, settings, inv.expires_at + timedelta(days=1)) == 0


def test_weekly_digest_groups_by_owner(client, db, live, settings, people):
    cid, e, maria = live
    for owner, desc, days in [("Priya Shah", "Constitute bias committee", 10), ("Priya Shah", "Create RACI", 3), ("Raj Iyer", "Appoint security owner", 1), ("Raj Iyer", "Not due yet", -5)]:
        db.add(Commitment(organization_id=cid, engagement_id=e.id, source="governance_role", source_id="x", description=desc, target_date=date(2026, 11, 16) - timedelta(days=days), owner=owner, status="open"))
    db.commit()
    monday = date(2026, 11, 16)
    assert jobs.run_weekly_digest(db, settings, monday + timedelta(days=1)) == 0  # Tuesday: nothing
    n = jobs.run_weekly_digest(db, settings, monday)
    assert n >= 2  # the CAICO and the assigned auditors
    mail = db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "overdue_digest", OutboxMessage.to == ["maria@abc.test"]))
    body = mail.body_text
    assert body.index("Priya Shah") < body.index("Constitute bias committee") < body.index("Raj Iyer") < body.index("Appoint security owner")
    assert "Not due yet" not in body
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "overdue_digest", OutboxMessage.to == [people["aud"].email])) is not None


def test_sign_off_awaiting_sends_email_and_bell_lists_it(client, db, live, settings, people):
    from app.notifications.service import notify

    cid, e, maria = live
    notify(db, [maria], "sign_off_awaiting", "Sign-off 3 is waiting for you", "Inventory review", "/inventory", engagement=e, settings=settings)
    db.commit()
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "notification", OutboxMessage.to == ["maria@abc.test"])) is not None
    login_as(client, db, maria)
    r = client.get("/api/v1/me/notifications").json()
    assert r["unread"] >= 1 and r["items"][0]["title"] == "Sign-off 3 is waiting for you"
    nid = r["items"][0]["id"]
    assert client.post(f"/api/v1/notifications/{nid}/read").status_code == 200
    assert client.get("/api/v1/me/notifications").json()["unread"] == r["unread"] - 1
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/notifications/{nid}/read").status_code == 404
    assert client.post("/api/v1/notifications/read-all").status_code == 200


def test_run_daily_runs_every_job(client, db, live, settings):
    out = jobs.run_daily(db, settings, datetime(2026, 11, 16, 6, 0))
    assert set(out) == {"invitation_warnings", "invitation_expiry", "due_soon", "escalations", "weekly_digest", "repeal_dates",
                        "refresh_schedule", "refresh_reminders", "client_alert_dates", "opportunity_dates",  # v0.6 WS-D
                        "regulatory_digest", "reassessment_schedule",  # wave 3 WS-H
                        "bias_raw_data_retention",  # wave 3 WS-K
                        "monitoring_monthly",  # wave 3 WS-J
                        "opportunity_scan",  # 11-03 F8
                        "model_catalogue_monthly",  # 11-03 C12
                        "catalog_effective_dates",  # Release 2 R1
                        "commercial_usage",  # Release 2 R5
                        "proposal_followups",  # Release 2 R4
                        "scoping_reminders"}  # Release 2 R3
    # email (every minute) and incident deadlines (every 15 minutes) run on their own ticks, never also in the daily run
    assert all(isinstance(v, int) for v in out.values()), out


# ---- 11-10 review O7: the daily run happens once a day even when the server was not running at 10:00 UTC

def _counting(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "JOBS", {"count": lambda db, settings, now: calls.append(now) or 1})
    return calls


def test_a_missed_daily_run_catches_up_once_when_the_app_is_open(db, settings, monkeypatch):
    from app.notifications.models import DailyJobRun

    calls = _counting(monkeypatch)
    assert jobs.run_daily_once(db, settings, datetime(2026, 11, 16, 9, 59)) is None  # not before 10:00 UTC
    assert jobs.run_daily_once(db, settings, datetime(2026, 11, 16, 14, 30)) == {"count": 1}  # opened in the afternoon
    assert jobs.run_daily_once(db, settings, datetime(2026, 11, 16, 14, 45)) is None  # the next tick: already run today
    assert jobs.run_daily_once(db, settings, datetime(2026, 11, 16, 23, 59)) is None
    assert len(calls) == 1
    row = db.scalar(select(DailyJobRun))
    assert row.run_on.isoformat() == "2026-11-16" and row.status == "completed" and row.outcome == {"count": 1} and row.finished_at
    assert jobs.run_daily_once(db, settings, datetime(2026, 11, 18, 10, 0)) == {"count": 1}  # a day the laptop was off is not run twice
    assert len(calls) == 2


def test_a_failed_job_is_recorded_on_the_days_run(db, settings, monkeypatch):
    from app.notifications.models import DailyJobRun

    def boom(db, settings, now):
        raise RuntimeError("x")

    monkeypatch.setattr(jobs, "JOBS", {"boom": boom})
    assert jobs.run_daily_once(db, settings, datetime(2026, 11, 16, 11, 0)) == {"boom": "failed: RuntimeError"}
    assert db.scalar(select(DailyJobRun.status)) == "failed"
    assert jobs.run_daily_once(db, settings, datetime(2026, 11, 16, 12, 0)) is None


def test_two_processes_claim_the_day_and_one_runs(tmp_path, settings, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.models import Base
    import app.models_registry  # noqa: F401

    eng = create_engine(f"sqlite:///{tmp_path / 'two.db'}")
    Base.metadata.create_all(eng)
    a, b = sessionmaker(bind=eng)(), sessionmaker(bind=eng)()
    now = datetime(2026, 11, 16, 10, 0)
    try:
        assert jobs._claim_day(a, now) is not None
        assert jobs._claim_day(b, now) is None  # the unique day is taken: the other process runs nothing
        calls = _counting(monkeypatch)
        assert jobs.run_daily_once(b, settings, now) is None and calls == []
    finally:
        a.close()
        b.close()
        eng.dispose()


def test_the_scheduler_catches_up_on_start_and_every_15_minutes(engine, settings, monkeypatch):
    import time as _time
    from types import SimpleNamespace

    from sqlalchemy.orm import sessionmaker

    seen = []
    monkeypatch.setattr(jobs, "run_daily_once", lambda db, settings, now: seen.append(now))
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, sessionmaker=sessionmaker(bind=engine)))
    jobs.start_scheduler(app)
    try:
        sched = app.state.scheduler
        daily = sched.get_job("daily")
        assert daily.misfire_grace_time and daily.misfire_grace_time >= 3600 and daily.coalesce is True
        assert str(daily.trigger.fields[5]) == "10" and str(daily.trigger.fields[6]) == "0"  # hour, minute (UTC)
        catchup = sched.get_job("daily_catchup")
        assert catchup.trigger.interval.total_seconds() == 15 * 60 and catchup.coalesce is True and catchup.max_instances == 1
        for _ in range(50):  # on start
            if seen:
                break
            _time.sleep(0.1)
        assert seen
    finally:
        app.state.scheduler.shutdown(wait=False)
