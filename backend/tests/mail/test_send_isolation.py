"""Security review I2: a control character in a subject cannot reach a mail header, and one bad send cannot stop the
mail scheduler for every other organisation."""
from datetime import timedelta

import pytest

from app.core.clock import set_now, utcnow
from app.mail import delivery, sending
from app.mail.groups import add_member, create_group
from app.mail.models import MailSend
from app.mail.people import upsert_person
from app.mail.providers import OutgoingMessage, ProviderError
from app.mail.providers.fake import FAKE
from app.mail.providers.google import GoogleAdapter
from app.mail.sending import send_to_groups
from app.mail.tokens import Grant
from tests.factories import login_as, make_org, make_user


@pytest.fixture(autouse=True)
def _reset():
    FAKE.reset()
    yield
    set_now(None)


def _two_clients(db):
    make_org(db, type="futran")
    a, b = make_org(db, name="Client A"), make_org(db, name="Client B")
    ca, cb = make_user(db, a, roles=["caico"], email="ca@a.com"), make_user(db, b, roles=["caico"], email="cb@b.com")
    ga, gb = create_group(db, ca, a.id, name="GA", source="manual"), create_group(db, cb, b.id, name="GB", source="manual")
    add_member(db, ca, ga, person_id=upsert_person(db, a.id, email="x@a.com", name="X").id)
    add_member(db, cb, gb, person_id=upsert_person(db, b.id, email="y@b.com", name="Y").id)
    return (a, ca, ga), (b, cb, gb)


def test_render_folds_line_breaks_in_a_subject_into_spaces(db, settings):
    (a, ca, ga), _ = _two_clients(db)
    s = send_to_groups(db, settings, ca, organization_id=a.id, group_ids=[ga.id], template_key="regulatory_change_alert", scheduled_at=utcnow() + timedelta(hours=1),
                       subject="Update\r\nBcc: victim@example.com\tnow")
    subject, _, _ = sending.render(db, s, None, None, None, "FAP-1000")
    assert subject == "Update Bcc: victim@example.com now [FAP-1000]"


def test_a_crlf_subject_goes_out_on_one_line_through_smtp(db, settings, monkeypatch):
    settings.email_mode = "smtp"
    sent = []

    class DummySMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, m, to_addrs=None): sent.append(m)

    monkeypatch.setattr("smtplib.SMTP", DummySMTP)
    (a, ca, ga), _ = _two_clients(db)
    s = send_to_groups(db, settings, ca, organization_id=a.id, group_ids=[ga.id], template_key="regulatory_change_alert", subject="Update\r\nBcc: victim@example.com")
    assert s.status == "sent" and len(sent) == 1
    assert "\n" not in sent[0]["Subject"] and sent[0]["Bcc"] is None


def test_the_send_endpoint_refuses_control_characters_in_the_subject(client, db, settings):
    (a, ca, ga), _ = _two_clients(db)
    db.commit()
    login_as(client, db, ca)
    for path in ("/api/v1/mail/send", "/api/v1/mail/send/preview", "/api/v1/mail/send/test"):
        r = client.post(path, json={"group_ids": [ga.id], "template_key": "regulatory_change_alert", "subject": "Update\r\nBcc: victim@example.com"})
        assert r.status_code == 422, (path, r.text)
        assert r.json()["errors"][0]["field"] == "subject"
    assert db.query(MailSend).count() == 0


def test_smtp_header_errors_are_recorded_as_a_failed_delivery_not_raised(settings):
    sender = delivery.Sender(channel="smtp", from_name="Bad\nName", from_address="ai@a.com")
    res = delivery._smtp(settings, sender, delivery.Envelope(to=["x@a.com"], subject="Hello", html="<p>h</p>", text="h"))
    assert res.ok is False and res.error


def test_google_header_errors_become_a_provider_error(settings):
    g = GoogleAdapter(settings)
    with pytest.raises(ProviderError):
        g.send(Grant({"access_token": "t", "expires_at": 9e18}), OutgoingMessage("ai@a.com", "Bad\r\nName", None, ["x@a.com"], [], "Hello", "<p>h</p>", "h"))


def test_one_failing_send_does_not_stop_the_other_organisations_sends(db, settings, monkeypatch):
    (a, ca, ga), (b, cb, gb) = _two_clients(db)
    when = utcnow() + timedelta(hours=1)
    sa = send_to_groups(db, settings, ca, organization_id=a.id, group_ids=[ga.id], template_key="regulatory_change_alert", scheduled_at=when)
    sb = send_to_groups(db, settings, cb, organization_id=b.id, group_ids=[gb.id], template_key="regulatory_change_alert", scheduled_at=when + timedelta(minutes=1))
    db.commit()
    real = sending._sender_for

    def broken(db_, settings_, s):
        if s.organization_id == a.id:
            raise RuntimeError("unexpected failure in one send")
        return real(db_, settings_, s)

    monkeypatch.setattr(sending, "_sender_for", broken)
    set_now(when + timedelta(minutes=5))
    from app.mail.jobs import run_mail_tick

    out = run_mail_tick(db, settings, utcnow())
    db.commit()
    db.expire_all()
    assert db.get(MailSend, sb.id).status == "sent"
    assert db.get(MailSend, sa.id).status == "scheduled"  # left for the next tick, nothing half-done
    assert out["dispatched"] == 1


def test_one_failing_part_of_the_mail_tick_does_not_stop_the_others(db, settings, monkeypatch):
    (a, ca, ga), _ = _two_clients(db)
    when = utcnow() + timedelta(hours=1)
    sa = send_to_groups(db, settings, ca, organization_id=a.id, group_ids=[ga.id], template_key="regulatory_change_alert", scheduled_at=when)
    db.commit()
    from app.mail import jobs, reminders

    def boom(*a, **k):
        raise RuntimeError("reminders broke")

    monkeypatch.setattr(reminders, "run_reminders", boom)
    set_now(when + timedelta(minutes=5))
    out = jobs.run_mail_tick(db, settings, utcnow())
    db.commit()
    db.expire_all()
    assert db.get(MailSend, sa.id).status == "sent"
    assert out["dispatched"] == 1 and str(out["reminders"]).startswith("failed")
