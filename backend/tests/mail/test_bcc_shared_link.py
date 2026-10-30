"""Security review I7: one shared link per BCC send, kept across retries, and BCC batches follow the pacing limit."""
from datetime import timedelta

import pytest

from app.core.clock import set_now, utcnow
from app.mail import links, tokens
from app.mail.groups import add_member, create_group
from app.mail.models import MailConnection, MailRecipient
from app.mail.people import upsert_person
from app.mail.providers.fake import FAKE
from app.mail.sending import dispatch_due, send_to_groups
from tests.factories import make_org, make_user


@pytest.fixture(autouse=True)
def _reset():
    FAKE.reset()
    yield
    set_now(None)


def _client(db, settings, n: int):
    make_org(db, type="futran")
    a = make_org(db, name="Client A")
    ca = make_user(db, a, roles=["caico"], email="ca@abc.com")
    conn = MailConnection(organization_id=a.id, owner="client", provider="microsoft365", mailbox_address="ai@abc.com", status="connected", sender_mode="own")
    tokens.store(settings, conn, {"fake": True, "kind": "app", "domains": ["abc.com"]})
    db.add(conn)
    g = create_group(db, ca, a.id, name="G", source="manual")
    for i in range(n):
        add_member(db, ca, g, person_id=upsert_person(db, a.id, email=f"p{i}@abc.com", name=f"P{i}").id)
    return a, ca, g


def _shared(message) -> str:
    return next(x for x in message.text.split() if "/m/s/" in x).rsplit("/m/s/", 1)[1]


def test_a_bcc_retry_keeps_the_shared_link_already_delivered(db, settings):
    a, ca, g = _client(db, settings, 2)
    FAKE.fail_next = 1  # batch 1 fails once, batch 2 goes out
    s = send_to_groups(db, settings, ca, organization_id=a.id, group_ids=[g.id], template_key="regulatory_change_alert", mode="bcc", batch_size=1)
    first = _shared(FAKE.sent[0].message)
    assert links.shared_send(db, first).id == s.id
    set_now(utcnow() + timedelta(minutes=2))
    dispatch_due(db, settings)  # the retry of batch 1
    assert len(FAKE.sent) == 2
    assert _shared(FAKE.sent[1].message) == first  # the retry carries the same link
    assert links.shared_send(db, first).id == s.id  # and batch 2's link still works
    assert db.query(MailRecipient).filter_by(send_id=s.id, status="sent").count() == 2


def test_bcc_batches_follow_the_pacing_limit(db, settings):
    settings.mail_pace_per_minute = 2
    a, ca, g = _client(db, settings, 5)
    s = send_to_groups(db, settings, ca, organization_id=a.id, group_ids=[g.id], template_key="regulatory_change_alert", mode="bcc", batch_size=1)
    assert len(FAKE.sent) == 2 and s.status == "sending"
    link = _shared(FAKE.sent[0].message)
    set_now(utcnow() + timedelta(minutes=1))
    dispatch_due(db, settings)
    set_now(utcnow() + timedelta(minutes=1))
    dispatch_due(db, settings)
    assert len(FAKE.sent) == 5 and s.status == "sent"
    assert {_shared(m.message) for m in FAKE.sent} == {link}  # later batches carry the same link
    assert links.shared_send(db, link).id == s.id
