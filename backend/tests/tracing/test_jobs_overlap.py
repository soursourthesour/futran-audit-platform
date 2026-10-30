"""Two runs of the incident deadline job that overlap on the laptop's file database (WAL) send each reminder once:
each reminder claims its row with a conditional update before anyone is notified."""
import threading
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.notifications.models import Notification
from app.tracing.jobs import run_incident_deadlines
from tests.tracing.test_jobs import _setup


@pytest.fixture
def engine(tmp_path):
    """Replaces the in-memory engine: the app and both job sessions use one file database with the production pragmas."""
    from app.core.db import make_engine
    from app.core.models import Base
    import app.models_registry  # noqa: F401

    eng = make_engine(f"sqlite:///{tmp_path}/race.db")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _overlap(engine, settings, at):
    S = sessionmaker(bind=engine, expire_on_commit=False)
    first_done, release = threading.Event(), threading.Event()
    errors = []

    def first():  # e.g. a slow run: writes, keeps working, commits a second later
        s = S()
        try:
            run_incident_deadlines(s, settings, at)
            first_done.set()
            release.wait(5)
            s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
            first_done.set()
        finally:
            s.close()

    t = threading.Thread(target=first)
    t.start()
    first_done.wait(5)
    threading.Timer(1.0, release.set).start()
    s2 = S()
    try:
        run_incident_deadlines(s2, settings, at)
        s2.commit()
    finally:
        s2.close()
    t.join()
    assert not errors, errors
    return S()


def test_overlapping_runs_send_the_reminder_once(client, db, trc, settings, engine):
    _setup(client, db, trc)
    db.commit()
    check = _overlap(engine, settings, datetime(2028, 3, 1, 12, 30))
    n = len(list(check.scalars(select(Notification).where(Notification.kind == "incident_deadline_reminder"))))
    assert n == 3, f"{n} reminder notifications for 3 recipients"


def test_overlapping_runs_send_the_missed_notice_once(client, db, trc, settings, engine):
    _setup(client, db, trc)
    db.commit()
    check = _overlap(engine, settings, datetime(2028, 3, 1, 14, 1))
    n = len(list(check.scalars(select(Notification).where(Notification.kind == "incident_deadline_missed"))))
    assert n == 3, f"{n} missed notifications for 3 recipients"
