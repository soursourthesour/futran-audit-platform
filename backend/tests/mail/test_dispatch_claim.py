"""Two scheduler runs that overlap on the laptop's file database (WAL) deliver each queued message once: every
recipient is claimed with a conditional update before the provider is called."""
import threading
from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.clock import utcnow
from app.mail.models import MailRecipient
from app.mail.providers.fake import FAKE
from app.mail.reminders import run_reminders
from app.mail.sending import dispatch_due, send_to_groups
from tests.mail.test_delivery import _connect_fake, _list, _people
from tests.factories import make_org, make_user


@pytest.fixture
def engine(tmp_path):
    from app.core.db import make_engine
    from app.core.models import Base
    import app.models_registry  # noqa: F401

    eng = make_engine(f"sqlite:///{tmp_path}/race.db")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _fake():
    FAKE.reset()
    yield
    FAKE.reset()


def _overlap(engine, job):
    S = sessionmaker(bind=engine, expire_on_commit=False)
    first_done, release = threading.Event(), threading.Event()
    errors = []

    def first():
        s = S()
        try:
            job(s)
            s.flush()
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
        job(s2)
        s2.commit()
    except Exception as exc:  # noqa: BLE001  (a locked database is a retry next minute, not a second send)
        s2.rollback()
    finally:
        s2.close()
    t.join()
    assert not errors, errors


def test_overlapping_dispatch_runs_deliver_each_message_once(db, settings, engine):
    make_org(db, type="futran")
    org = make_org(db, type="client")
    caico = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com")
    _connect_fake(db, settings, org)
    g = _list(db, caico, org, "Many", _people(db, org, 40))
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request")
    db.commit()
    assert len(FAKE.sent) == 30  # paced: 30 a minute
    _overlap(engine, lambda sess: dispatch_due(sess, settings, utcnow() + timedelta(minutes=1)))
    emails = [tuple(m.message.to) for m in FAKE.sent]
    assert len(FAKE.sent) == 40, f"{len(FAKE.sent)} messages for 40 people"
    assert len(set(emails)) == 40
    check = sessionmaker(bind=engine)()
    assert check.query(MailRecipient).filter_by(send_id=s.id, status="sent").count() == 40


def test_overlapping_reminder_runs_remind_each_person_once(db, settings, engine):
    make_org(db, type="futran")
    org = make_org(db, type="client")
    caico = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com")
    g = _list(db, caico, org, "Three", _people(db, org, 3))
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request", reminder_days=[3])
    db.commit()
    _overlap(engine, lambda sess: run_reminders(sess, settings, utcnow() + timedelta(days=3, minutes=1)))
    check = sessionmaker(bind=engine)()
    from app.mail.models import MailSend

    reminders = check.query(MailSend).filter_by(parent_send_id=s.id).all()
    assert sum(r.recipient_count for r in reminders) == 3, [(r.id, r.recipient_count) for r in reminders]
