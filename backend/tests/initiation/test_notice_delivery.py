"""The employee data notice is queued in the request and delivered after it (load test BUG-V01): one send with a
recipient per person, a second send refused while one is in progress or already done, and a restart resumes delivery
without emailing anyone twice."""
from collections import Counter

from sqlalchemy import select

from app.core.clock import utcnow
from app.initiation import notice
from app.mail import tokens
from app.mail.models import MailConnection, MailRecipient, MailSend, MailThread, OutboxMessage
from app.mail.providers.fake import FAKE
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def _add(client, cid, first, email, role="client_admin"):
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": first, "last_name": "Staff", "email": email, "job_title": "", "department": "", "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _notices(db):
    db.expire_all()
    return list(db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "employee_data_notice")))


def test_the_notice_goes_out_as_one_send_after_the_request(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    for i in range(4):
        _add(client, cid, f"Person{i}", f"p{i}@abc.test")
    db.get(User, maria.id).password_hash = "set"  # Maria has a login; the others are invited
    db.commit()
    r = client.post("/api/v1/me/notice/send")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sending" and r.json()["message"] == "Sending to 5 people" and r.json()["recipients"] == 5
    mails = _notices(db)
    assert sorted(m.to[0] for m in mails) == ["maria@abc.test"] + [f"p{i}@abc.test" for i in range(4)]
    sends = list(db.scalars(select(MailSend).where(MailSend.template_key == "employee_data_notice")))
    assert len(sends) == 1  # one row in the email log, not one per person
    s = sends[0]
    assert (s.kind, s.status, s.recipient_count, s.related_type) == ("system", "sent", 5, "NoticeRelease")
    assert Counter(db.scalars(select(MailRecipient.status).where(MailRecipient.send_id == s.id))) == {"sent": 5}
    # Maria has a login, the invited people do not: each email is written for its reader, as before
    by = {m.to[0]: m for m in mails}
    assert "next sign in" in by["maria@abc.test"].body_text and "next sign in" not in by["p0@abc.test"].body_text
    n = client.get("/api/v1/me/notice").json()
    assert n["sent"]["delivery"] == {"status": "sent", "sent": 5, "failed": 0, "waiting": 0, "total": 5}


def test_a_second_send_of_the_same_version_is_refused_unless_a_resend_is_asked_for(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _add(client, cid, "Tom", "tom@abc.test")
    assert client.post("/api/v1/me/notice/send").status_code == 200
    r = client.post("/api/v1/me/notice/send")
    assert r.status_code == 409 and "already been sent" in r.json()["detail"]
    assert len(_notices(db)) == 2  # nobody emailed twice
    # the legacy "done" call does not send it again either
    assert client.post("/api/v1/me/initiation/items/notice/done").json()["version"] == 1
    assert len(_notices(db)) == 2
    r = client.post("/api/v1/me/notice/send", json={"resend": True})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert len(_notices(db)) == 4


def test_a_send_is_refused_while_the_previous_version_is_still_being_delivered(client, db, people, live, settings):
    cid, e, maria = live
    login_as(client, db, maria)
    _add(client, cid, "Tom", "tom@abc.test")
    db.expire_all()
    rel = notice.send(db, client.app.state.settings, db.get(User, maria.id), {"caico"}, e)  # queued, not yet delivered
    db.commit()
    assert _notices(db) == []
    client.put("/api/v1/me/notice", json={"body_md": "# Notice\n\nVersion two."})
    r = client.post("/api/v1/me/notice/send")
    assert r.status_code == 409 and "still being sent (0 of 2 so far)" in r.json()["detail"]
    assert notice.delivery(db, rel) == {"status": "sending", "sent": 0, "failed": 0, "waiting": 2, "total": 2}


def test_a_restart_resumes_delivery_and_nobody_gets_it_twice(client, db, people, live):
    from app.mail.sending import dispatch_due
    from app.mail.service import dispatch_bulk

    cid, e, maria = live
    login_as(client, db, maria)
    for i in range(5):
        _add(client, cid, f"Person{i}", f"p{i}@abc.test")
    db.expire_all()
    settings = client.app.state.settings
    rel = notice.send(db, settings, db.get(User, maria.id), {"caico"}, e)
    db.commit()
    s = notice.delivery_send(db, rel)
    assert dispatch_bulk(db, settings, s, limit=2, after_each=db.commit) == 2  # the process stops after two emails
    db.commit()
    assert len(_notices(db)) == 2 and s.status == "sending"
    assert dispatch_due(db, settings, utcnow()) == 4  # the mail tick sends the rest
    db.commit()
    mails = _notices(db)
    assert len(mails) == 6 and len({m.to[0] for m in mails}) == 6
    db.refresh(s)
    assert s.status == "sent" and s.sent_at is not None
    assert dispatch_due(db, settings, utcnow()) == 0


def test_with_a_connected_mailbox_every_email_of_the_release_carries_one_thread_reference(client, db, people, live):
    FAKE.reset()
    cid, e, maria = live
    login_as(client, db, maria)
    for i in range(3):
        _add(client, cid, f"Person{i}", f"p{i}@abc.test")
    c = MailConnection(organization_id=cid, owner="client", provider="microsoft365", mailbox_address="ai-governance@abc.test", status="connected", sender_mode="own")
    tokens.store(client.app.state.settings, c, {"fake": True, "kind": "app", "domains": ["abc.test"]})
    db.add(c)
    db.commit()
    assert client.post("/api/v1/me/notice/send").status_code == 200
    s = db.scalar(select(MailSend).where(MailSend.template_key == "employee_data_notice"))
    refs = list(db.scalars(select(MailThread.subject_ref).where(MailThread.send_id == s.id)))
    assert len(refs) == 1
    subjects = [m.message.subject for m in FAKE.sent]
    assert len(subjects) == 4 and all(sub.endswith(f"[{refs[0]}]") for sub in subjects)
    assert {m.message.from_address for m in FAKE.sent} == {"ai-governance@abc.test"}
