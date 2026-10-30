"""Existing emails (invitations, package, reminders, notices, attestation) go through MailSend; the outbox still shows
every one of them (spec §26 via the plan's ruling)."""
import pytest

from app.mail import tokens
from app.mail.models import AdminLogEntry, MailConnection, MailRecipient, MailSend, OutboxMessage
from app.mail.providers.fake import FAKE
from app.mail.service import send
from tests.factories import make_org, make_user


@pytest.fixture(autouse=True)
def _reset():
    FAKE.reset()


def _conn(db, settings, org, owner, mailbox, **kw):
    c = MailConnection(organization_id=org.id, owner=owner, provider="microsoft365", mailbox_address=mailbox, status="connected", **kw)
    tokens.store(settings, c, {"fake": True, "kind": "app", "domains": [mailbox.split("@")[1]]})
    db.add(c)
    db.flush()
    return c


def test_a_system_email_is_logged_as_a_send_with_its_recipient(db, settings):
    org = make_org(db, type="client")
    msg = send(db, settings, "test_message", to=["priya@abc.com"], context={"organization_name": "ABC Corp", "body": "Hi"}, organization_id=org.id)
    s = db.get(MailSend, msg.mail_send_id)
    assert s.kind == "system" and s.template_key == "test_message" and s.mode == "direct" and s.channel == "outbox"
    assert [(r.email, r.status) for r in db.query(MailRecipient).filter_by(send_id=s.id)] == [("priya@abc.com", "sent")]
    assert db.query(AdminLogEntry).filter_by(send_id=s.id, category="send").count() == 1
    assert msg.subject == "ABC Corp: test message"  # unchanged when nothing is connected


def test_futran_emails_go_from_the_futran_mailbox_when_it_is_connected(db, settings):
    futran = make_org(db, type="futran")
    org = make_org(db, type="client")
    _conn(db, settings, futran, "futran", "aiaudit@futransolutions.com")
    msg = send(db, settings, "test_message", to=["priya@abc.com"], context={"organization_name": "ABC Corp", "body": "Hi"}, organization_id=org.id)
    assert msg.channel == "microsoft365" and msg.status == "sent"
    assert len(FAKE.sent) == 1 and FAKE.sent[0].message.from_address == "aiaudit@futransolutions.com"
    assert "[FAP-" in FAKE.sent[0].message.subject
    assert db.query(OutboxMessage).count() == 1  # still visible in Admin > Outbox


def test_client_side_emails_go_from_the_clients_own_mailbox(db, settings):
    futran = make_org(db, type="futran")
    org = make_org(db, type="client")
    _conn(db, settings, futran, "futran", "aiaudit@futransolutions.com")
    _conn(db, settings, org, "client", "ai-governance@abc.com", sender_mode="own")
    send(db, settings, "employee_data_notice", to=["staff@abc.com"], organization_id=org.id, context=_notice_ctx())
    assert FAKE.sent[-1].message.from_address == "ai-governance@abc.com"


def test_client_emails_go_from_futran_on_the_clients_behalf_when_chosen(db, settings):
    futran = make_org(db, type="futran")
    org = make_org(db, type="client", name="ABC Corp")
    _conn(db, settings, futran, "futran", "aiaudit@futransolutions.com")
    _conn(db, settings, org, "client", "ai-governance@abc.com", sender_mode="futran_on_behalf")
    send(db, settings, "employee_data_notice", to=["staff@abc.com"], organization_id=org.id, context=_notice_ctx())
    m = FAKE.sent[-1].message
    assert m.from_address == "aiaudit@futransolutions.com" and "ABC Corp" in m.from_name


def test_invitation_still_reaches_the_outbox_through_mailsend(db, settings):
    from app.invitations.service import invite_user

    futran = make_org(db, type="futran")
    admin = make_user(db, futran, roles=["admin"], name="Ada Admin", email="admin@futran.test")
    org = make_org(db, type="client")
    u = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya2@abc.com")
    invite_user(db, settings, admin, u)
    msg = db.query(OutboxMessage).one()
    assert msg.mail_send_id and db.get(MailSend, msg.mail_send_id).template_key == "invitation"


def _notice_ctx():
    return {"client": "ABC Corp", "name": "Staff", "sender": "Priya Shah", "sender_role": "Chief AI Compliance Officer", "version": 1, "has_login": False,
            "link": "http://x/login", "notice_html": "<p>n</p>", "notice_text": "n"}
