"""Each paced dispatch run loads only the recipients it can send, not the whole queue (load test bottleneck 7: every
tick read all 9,800 queued recipients to send 30), in the same order as before; BCC runs load whole batches."""
from datetime import timedelta

from sqlalchemy import event

from app.core.clock import utcnow
from app.mail.models import MailRecipient
from app.mail.providers.fake import FAKE
from app.mail.sending import dispatch_due, send_to_groups
from tests.mail.test_delivery import _connect_fake, _list, _people, caico, org  # noqa: F401


class Loaded:
    def __init__(self):
        self.n = 0

    def _on(self, *_):
        self.n += 1

    def __enter__(self):
        event.listen(MailRecipient, "load", self._on)
        return self

    def __exit__(self, *_):
        event.remove(MailRecipient, "load", self._on)


def test_a_paced_run_loads_only_the_recipients_it_sends(db, settings, org, caico):
    FAKE.reset()
    settings.mail_pace_per_minute = 5
    _connect_fake(db, settings, org)
    g = _list(db, caico, org, "Many", _people(db, org, 40))
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request")
    db.flush()
    db.expunge_all()
    with Loaded() as seen:
        assert dispatch_due(db, settings, utcnow() + timedelta(minutes=1)) == 5
    assert seen.n <= 5 + 1, seen.n
    sent = [m.message.to[0] for m in FAKE.sent]
    assert sent == [f"p{i}@abc.com" for i in range(10)]  # in name order, the first five, then the next five
    for i in range(2, 10):
        dispatch_due(db, settings, utcnow() + timedelta(minutes=i))
    assert db.query(MailRecipient).filter_by(send_id=s.id, status="sent").count() == 40 and len(FAKE.sent) == 40


def test_a_bcc_run_sends_whole_batches(db, settings, org, caico):
    FAKE.reset()
    settings.mail_pace_per_minute = 1
    _connect_fake(db, settings, org)
    g = _list(db, caico, org, "Many", _people(db, org, 9))
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request", mode="bcc", batch_size=4)
    assert [len(m.message.bcc) for m in FAKE.sent] == [4]
    dispatch_due(db, settings, utcnow() + timedelta(minutes=1))
    dispatch_due(db, settings, utcnow() + timedelta(minutes=2))
    assert [len(m.message.bcc) for m in FAKE.sent] == [4, 4, 1]
    assert db.query(MailRecipient).filter_by(send_id=s.id, status="sent").count() == 9


def test_revocation_and_dispatch_use_indexes(db):
    plan = " ".join(str(r) for r in db.connection().exec_driver_sql(
        "EXPLAIN QUERY PLAN SELECT id FROM mail_recipients WHERE lower(email) = 'a@b.test'").fetchall())
    assert "ix_mail_recipients_email_ci" in plan
    plan = " ".join(str(r) for r in db.connection().exec_driver_sql(
        "EXPLAIN QUERY PLAN SELECT id FROM mail_recipients WHERE send_id = 'x' AND status = 'queued'").fetchall())
    assert "ix_mail_recipients_send_status" in plan
