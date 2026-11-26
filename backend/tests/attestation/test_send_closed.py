"""BUG-12: the attestation request goes out only while its campaign is open, whichever screen sends it (the
attestation tracker or Email › Send), and reminders stop when the campaign closes."""
from datetime import timedelta

from sqlalchemy import select

from app.attestation.models import AttestationCampaign
from app.core.clock import utcnow
from app.mail.models import MailSend
from tests.attestation.test_attestation_v2 import _user, world  # noqa: F401
from tests.attestation.test_send_all import _staff
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401

CLOSED = "The campaign has closed, so the attestation can't be sent. Launch a new campaign first."


def _campaign(db, cid):
    return db.scalar(select(AttestationCampaign).where(AttestationCampaign.organization_id == cid))


def _email_send(client, **kw):
    opts = client.get("/api/v1/mail/send/options").json()
    group = next(g for g in opts["groups"] if g["system_key"] == "all_employees")
    return client.post("/api/v1/mail/send", json={"template_key": "attestation_request", "group_ids": [group["id"]]} | kw)


def test_email_send_refuses_the_attestation_for_a_closed_campaign(client, db, world):
    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    c = _campaign(db, cid)
    c.status = "closed"
    db.commit()
    before = db.scalar(select(MailSend.id).limit(1))
    r = _email_send(client)
    assert r.status_code == 409 and r.json()["detail"] == CLOSED
    assert db.scalar(select(MailSend.id).limit(1)) == before  # nothing was queued
    assert client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={}).json()["detail"] == CLOSED  # the same message as the tracker


def test_email_send_refuses_the_attestation_once_the_closing_date_has_passed(client, db, world):
    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    c = _campaign(db, cid)
    c.closes_at = utcnow() - timedelta(minutes=1)  # still 'open' in status, but past its date
    db.commit()
    assert _email_send(client).status_code == 409


def test_email_send_works_while_the_campaign_is_open(client, db, world):
    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    r = _email_send(client)
    assert r.status_code == 200, r.text
    s = db.scalar(select(MailSend).where(MailSend.template_key == "attestation_request"))
    assert s.campaign_type == "attestation" and s.campaign_id == _campaign(db, cid).id


def test_a_send_scheduled_after_the_campaign_closes_is_refused(client, db, world):
    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    c = _campaign(db, cid)
    late = (c.closes_at + timedelta(days=1)).isoformat()
    r = _email_send(client, scheduled_at=late)
    assert r.status_code == 409 and "closes" in r.json()["detail"]


def test_without_any_campaign_the_attestation_template_is_refused(client, db, world):
    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    _campaign(db, cid).deleted_at = utcnow()
    db.commit()
    r = _email_send(client)
    assert r.status_code == 409 and "campaign" in r.json()["detail"]


def test_reminders_stop_when_the_campaign_closes(client, db, world, settings):
    from app.mail.reminders import run_reminders

    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={"reminder_days": [3]})
    assert r.status_code == 200, r.text
    send_id = r.json()["send_id"]
    _campaign(db, cid).status = "closed"
    db.commit()
    assert run_reminders(db, client.app.state.settings, utcnow() + timedelta(days=4)) == 0
    assert db.scalar(select(MailSend).where(MailSend.parent_send_id == send_id)) is None
    r = client.post(f"/api/v1/mail/log/sends/{send_id}/remind")
    assert r.status_code == 409 and r.json()["detail"] == CLOSED
    from app.mail.models import MailRecipient

    db.scalar(select(MailRecipient).where(MailRecipient.send_id == send_id)).status = "bounced"
    db.commit()
    r = client.post(f"/api/v1/mail/log/sends/{send_id}/resend-bounced")
    assert r.status_code == 409 and r.json()["detail"] == CLOSED


def test_a_scheduled_send_is_cancelled_when_the_campaign_closes_early(client, db, world):
    """Review 11-25 #4: the check also runs when the scheduler sends, not only when the send is created."""
    from app.mail.models import MailRecipient
    from app.mail.sending import dispatch_due

    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    when = utcnow() + timedelta(hours=1)
    r = _email_send(client, scheduled_at=when.isoformat())
    assert r.status_code == 200, r.text
    _campaign(db, cid).status = "closed"
    db.commit()
    assert dispatch_due(db, client.app.state.settings, when + timedelta(minutes=1)) == 0
    s = db.scalar(select(MailSend).where(MailSend.template_key == "attestation_request").order_by(MailSend.created_at.desc()))
    assert s.status == "cancelled"
    statuses = set(db.scalars(select(MailRecipient.status).where(MailRecipient.send_id == s.id)))
    assert statuses == {"cancelled"}


def test_after_discovery_the_closed_message_does_not_point_to_a_new_campaign(client, db, world):
    """BUG-C01: once discovery has finished a new campaign can't start, so "Launch a new campaign first" was a dead end."""
    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    c = _campaign(db, cid)
    c.status = "closed"
    e.stage = 4
    db.commit()
    r = _email_send(client)
    assert r.status_code == 409
    msg = r.json()["detail"]
    assert "Launch" not in msg and "Chief Auditor" in msg
    assert client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={}).json()["detail"] == msg
    launch = client.post(f"/api/v1/clients/{cid}/attestation/campaigns", json={"department_ids": c.department_ids, "closes_at": (utcnow() + timedelta(days=7)).isoformat()})
    assert launch.status_code == 409 and "Chief Auditor" in launch.json()["detail"]  # the advice matches what launching says


# ---- From the 20 Nov hand-off build (BUG-12 fix round 1): the preview refuses too, and every skip is in the admin log
def test_the_preview_refuses_the_attestation_for_a_closed_campaign(client, db, world):
    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    _campaign(db, cid).status = "closed"
    db.commit()
    opts = client.get("/api/v1/mail/send/options").json()
    group = next(g for g in opts["groups"] if g["system_key"] == "all_employees")
    r = client.post("/api/v1/mail/send/preview", json={"template_key": "attestation_request", "group_ids": [group["id"]]})
    assert r.status_code == 409 and r.json()["detail"] == CLOSED


def _skips(db, send_id, action):
    from app.mail.models import AdminLogEntry

    return list(db.scalars(select(AdminLogEntry).where(AdminLogEntry.send_id == send_id, AdminLogEntry.action == action)))


def test_a_scheduled_send_skipped_at_dispatch_is_logged_once(client, db, world):
    from app.mail.sending import dispatch_due

    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    when = utcnow() + timedelta(hours=1)
    sid = _email_send(client, scheduled_at=when.isoformat()).json()["id"]
    _campaign(db, cid).status = "closed"
    db.commit()
    dispatch_due(db, client.app.state.settings, when + timedelta(minutes=1))
    dispatch_due(db, client.app.state.settings, when + timedelta(minutes=2))
    db.commit()
    logs = _skips(db, sid, "send_skipped")
    assert len(logs) == 1 and "campaign has closed" in logs[0].summary


def test_a_send_partly_delivered_before_the_campaign_closed_stays_sent(client, db, world):
    """Paced sends go out in batches: what already went is not reported as cancelled."""
    from app.mail.models import MailRecipient
    from app.mail.sending import dispatch

    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    s = db.get(MailSend, client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={}).json()["send_id"])
    rows = list(db.scalars(select(MailRecipient).where(MailRecipient.send_id == s.id)))
    assert len(rows) >= 2
    for r in rows[1:]:
        r.status, r.next_attempt_at = "queued", None
    rows[0].status = "sent"
    s.status = "sending"
    _campaign(db, cid).status = "closed"
    db.commit()
    dispatch(db, client.app.state.settings, s)
    db.commit()
    assert s.status == "sent"
    assert {r.status for r in rows[1:]} == {"cancelled"} and rows[0].status == "sent"


def test_automatic_reminders_skipped_after_the_campaign_closed_are_logged_once_per_planned_day(client, db, world):
    from app.mail.reminders import run_reminders

    cid, e, maria, depts, _ = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    s = db.get(MailSend, client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={"reminder_days": [3, 7]}).json()["send_id"])
    _campaign(db, cid).status = "closed"
    db.commit()
    settings = client.app.state.settings
    assert run_reminders(db, settings, s.sent_at + timedelta(days=4)) == 0
    assert run_reminders(db, settings, s.sent_at + timedelta(days=4, hours=1)) == 0
    db.commit()
    logs = _skips(db, s.id, "reminder_skipped")
    assert len(logs) == 1 and "campaign has closed" in logs[0].summary
    assert run_reminders(db, settings, s.sent_at + timedelta(days=8)) == 0
    db.commit()
    assert len(_skips(db, s.id, "reminder_skipped")) == 2
