"""Expansion, personal links, BCC with one-time codes, pacing, retries and reminders (spec §26.4, §26.5)."""
from datetime import timedelta

import pytest

from app.core.clock import set_now, utcnow
from app.core.errors import AppError, Invalid
from app.mail import links, tokens
from app.mail.groups import add_member, create_group
from app.mail.models import MailConnection, MailRecipient, MailSend, OutboxMessage
from app.mail.people import upsert_person
from app.mail.providers.fake import FAKE
from app.mail.reminders import run_reminders
from app.mail.sending import dispatch, dispatch_due, preview_expansion, send_to_groups
from tests.factories import make_org, make_user


@pytest.fixture(autouse=True)
def _clock():
    FAKE.reset()
    yield
    set_now(None)


@pytest.fixture
def org(db):
    make_org(db, type="futran")
    return make_org(db, type="client")


@pytest.fixture
def caico(db, org):
    return make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com")


def _list(db, caico, org, name, people):
    g = create_group(db, caico, org.id, name=name, source="manual")
    for p in people:
        add_member(db, caico, g, person_id=p.id)
    return g


def _people(db, org, n, prefix="p", **kw):
    return [upsert_person(db, org.id, email=f"{prefix}{i}@abc.com", name=f"{prefix.title()} {i:04d}", **kw) for i in range(n)]


def test_preview_shows_the_count_after_each_step(db, org, caico):
    staff = _people(db, org, 10)
    contractors = _people(db, org, 3, prefix="c")
    leaver = upsert_person(db, org.id, email="gone@abc.com", name="Gone Person", status="left")
    a = _list(db, caico, org, "Staff", staff + [leaver])
    b = _list(db, caico, org, "Contractors", contractors + staff[:2])
    team = _list(db, caico, org, "AIComplianceTeam", staff[2:3])
    ex = preview_expansion(db, org.id, [a.id, b.id], exclude_group_ids=[team.id])
    assert [(s["label"], s["count"]) for s in ex.steps] == [
        ("Staff", 11), ("Contractors", 5), ("In more than one group (counted once)", -2), ("Left out: AIComplianceTeam", -1),
        ("Left the company or on leave", -1), ("Will receive", 12)]
    assert len(ex.people) == 12


def test_personal_links_are_random_hashed_expiring_and_one_per_person(db, settings, org, caico):
    ana = _people(db, org, 1)[0]
    g = _list(db, caico, org, "One", [ana])
    s1 = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request", campaign=("attestation", "camp-1"))
    msg = db.query(OutboxMessage).filter_by(mail_send_id=s1.id).one()
    raw = msg.body_text.split("/m/")[1].split()[0]
    assert len(raw) >= 43  # 32 random bytes = 256 bits
    r1 = db.query(MailRecipient).filter_by(send_id=s1.id).one()
    assert r1.link_token_hash != raw and raw not in (r1.link_token_hash or "")
    assert r1.link_expires_at - utcnow() >= timedelta(days=13, hours=23)
    rec, _ = links.open_personal(db, raw)
    assert rec.id == r1.id and rec.status == "opened"
    # a resend to the same person for the same campaign replaces the link
    s2 = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request", campaign=("attestation", "camp-1"))
    with pytest.raises(AppError) as e:
        links.open_personal(db, raw)
    assert e.value.status_code == 410
    raw2 = db.query(OutboxMessage).filter_by(mail_send_id=s2.id).one().body_text.split("/m/")[1].split()[0]
    assert links.open_personal(db, raw2)[0].send_id == s2.id


def test_expired_personal_link_is_refused(db, settings, org, caico):
    g = _list(db, caico, org, "One", _people(db, org, 1))
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request")
    raw = db.query(OutboxMessage).filter_by(mail_send_id=s.id).one().body_text.split("/m/")[1].split()[0]
    set_now(utcnow() + timedelta(days=15))
    with pytest.raises(AppError) as e:
        links.open_personal(db, raw)
    assert e.value.status_code == 410


def test_bcc_goes_in_batches_of_450_with_one_shared_link(db, settings, org, caico):
    g = _list(db, caico, org, "Everyone", _people(db, org, 1000))
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="ll144_notice", mode="bcc")
    msgs = db.query(OutboxMessage).filter_by(mail_send_id=s.id).all()
    assert sorted(len(m.bcc) for m in msgs) == [100, 450, 450]
    assert all("/m/s/" in m.body_text for m in msgs)
    assert s.shared_token_hash and len(s.shared_token_hash) == 64
    assert db.query(MailRecipient).filter_by(send_id=s.id, status="sent").count() == 1000


def _bcc(db, settings, org, caico):
    people = _people(db, org, 3)
    g = _list(db, caico, org, "Few", people)
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="ll144_notice", mode="bcc")
    raw = db.query(OutboxMessage).filter_by(mail_send_id=s.id).one().body_text.split("/m/s/")[1].split()[0]
    return s, raw


def test_shared_link_needs_a_one_time_code_sent_to_a_recipient_email(db, settings, org, caico):
    s, raw = _bcc(db, settings, org, caico)
    with pytest.raises(Invalid):
        links.request_code(db, settings, raw, "stranger@abc.com")
    code = links.request_code(db, settings, raw, "P1@abc.com")
    assert len(code) == 6 and code.isdigit()
    mail = db.query(OutboxMessage).filter(OutboxMessage.template_key == "one_time_code").one()
    assert mail.to == ["p1@abc.com"] and code in mail.body_text
    with pytest.raises(Invalid):
        links.verify_code(db, raw, "p1@abc.com", "000000" if code != "000000" else "111111")
    proof = links.verify_code(db, raw, "p1@abc.com", code)
    rec = links.recipient_for_proof(db, raw, proof)
    assert rec.email == "p1@abc.com"


def test_one_time_code_expires_after_10_minutes_and_locks_after_5_wrong_tries(db, settings, org, caico):
    s, raw = _bcc(db, settings, org, caico)
    code = links.request_code(db, settings, raw, "p0@abc.com")
    set_now(utcnow() + timedelta(minutes=11))
    with pytest.raises(Invalid):
        links.verify_code(db, raw, "p0@abc.com", code)
    set_now(None)
    code = links.request_code(db, settings, raw, "p2@abc.com")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(Invalid):
            links.verify_code(db, raw, "p2@abc.com", wrong)
    with pytest.raises(Invalid):
        links.verify_code(db, raw, "p2@abc.com", code)  # locked


def test_code_requests_are_rate_limited_per_email(db, settings, org, caico):
    s, raw = _bcc(db, settings, org, caico)
    for _ in range(3):
        links.request_code(db, settings, raw, "p1@abc.com")
    with pytest.raises(AppError) as e:
        links.request_code(db, settings, raw, "p1@abc.com")
    assert e.value.status_code == 429


def _connect_fake(db, settings, org):
    c = MailConnection(organization_id=org.id, owner="client", provider="microsoft365", mailbox_address="ai-governance@abc.com", send_as_name="ABC AI Governance",
                       status="connected", sender_mode="own")
    tokens.store(settings, c, {"fake": True, "kind": "app", "domains": ["abc.com"]})
    db.add(c)
    db.flush()
    return c


def test_sending_through_a_mailbox_is_paced_and_the_scheduler_finishes_it(db, settings, org, caico):
    _connect_fake(db, settings, org)
    g = _list(db, caico, org, "Many", _people(db, org, 70))
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request")
    assert s.channel == "microsoft365"
    assert db.query(MailRecipient).filter_by(send_id=s.id, status="sent").count() == 30
    assert s.status == "sending"
    dispatch_due(db, settings, utcnow() + timedelta(minutes=1))
    dispatch_due(db, settings, utcnow() + timedelta(minutes=2))
    assert db.query(MailRecipient).filter_by(send_id=s.id, status="sent").count() == 70
    assert s.status == "sent" and len(FAKE.sent) == 70
    assert all("[FAP-" in m.message.subject for m in FAKE.sent)


def test_failed_sends_retry_then_show_as_bounced(db, settings, org, caico):
    _connect_fake(db, settings, org)
    g = _list(db, caico, org, "One", _people(db, org, 1))
    FAKE.fail_next = 5
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request")
    r = db.query(MailRecipient).filter_by(send_id=s.id).one()
    assert r.status == "queued" and r.attempts == 1
    t = utcnow()
    dispatch(db, settings, s, t + timedelta(minutes=1))
    assert r.attempts == 2
    dispatch(db, settings, s, t + timedelta(minutes=7))
    assert r.status == "bounced" and r.error
    assert s.status == "sent"


def test_reminders_go_only_to_people_who_have_not_responded(db, settings, org, caico):
    people = _people(db, org, 3)
    g = _list(db, caico, org, "Three", people)
    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="attestation_request", reminder_days=[3, 7])
    done = db.query(MailRecipient).filter_by(send_id=s.id, email="p0@abc.com").one()
    links.mark_completed(db, done)
    assert run_reminders(db, settings, utcnow() + timedelta(days=2)) == 0
    assert run_reminders(db, settings, utcnow() + timedelta(days=3, minutes=1)) == 2
    assert run_reminders(db, settings, utcnow() + timedelta(days=4)) == 0  # not twice for day 3
    reminders = db.query(MailSend).filter_by(parent_send_id=s.id).all()
    assert len(reminders) == 1 and reminders[0].kind == "reminder"
    assert {r.email for r in db.query(MailRecipient).filter_by(send_id=reminders[0].id)} == {"p1@abc.com", "p2@abc.com"}
    assert run_reminders(db, settings, utcnow() + timedelta(days=7, minutes=1)) == 2
    assert db.query(MailRecipient).filter_by(send_id=s.id, email="p1@abc.com").one().reminders_sent == 2
