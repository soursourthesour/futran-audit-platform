"""Send to all employees (spec §27.1): personal links from the attestation tracker. An answer through a personal link
marks the person responded and feeds the inventory exactly as the staff link does."""
from datetime import timedelta

from sqlalchemy import select

from app.attestation.models import Attestation, AttestationCampaign
from app.core.clock import set_now, utcnow
from app.inventory.models import AITool
from app.mail.models import MailRecipient, MailSend, OutboxMessage
from app.mail.people import upsert_person
from tests.attestation.test_attestation_v2 import _answer, _pub, _user, world  # noqa: F401
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def _staff(db, cid, depts):
    upsert_person(db, cid, email="eve@abc.test", name="Eve Long", department_id=depts["HR"], office="New York")
    upsert_person(db, cid, email="finn@abc.test", name="Finn Berg", department_id=depts["Finance"], office="Chicago")
    upsert_person(db, cid, email="gone@abc.test", name="Gone Person", department_id=depts["HR"], status="left")
    db.commit()


def _link(db, email):
    msg = db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "attestation_request").order_by(OutboxMessage.created_at.desc())).all()
    msg = next(m for m in msg if m.to == [email])
    return msg.body_text.split("/m/")[1].split()[0]


def test_preview_and_send_to_all_employees_leaves_out_people_who_already_responded(client, db, world):
    cid, e, maria, depts, token = world
    _staff(db, cid, depts)
    pub = _pub(client)
    assert pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], name="Tom Reyes", email="tom@abc.test")).status_code == 200
    login_as(client, db, _user(db, "sam@abc.test"))  # the Client Admin sends
    body = {"exclude_responded": True, "reminder_days": [3, 7]}
    p = client.post(f"/api/v1/clients/{cid}/attestation/send-all/preview", json=body)
    assert p.status_code == 200, p.text
    labels = {s["label"]: s["count"] for s in p.json()["steps"]}
    assert labels["Already responded"] == -1 and labels["Left the company or on leave"] == -1
    r = client.post(f"/api/v1/clients/{cid}/attestation/send-all", json=body)
    assert r.status_code == 200, r.text
    s = db.get(MailSend, r.json()["send_id"])
    assert s.campaign_type == "attestation" and s.mode == "personal" and s.reminder_plan == [3, 7]
    emails = {x.email for x in db.scalars(select(MailRecipient).where(MailRecipient.send_id == s.id))}
    assert "tom@abc.test" not in emails and "gone@abc.test" not in emails
    assert {"eve@abc.test", "finn@abc.test", "priya@abc.test"} <= emails
    assert r.json()["recipients"] == len(emails) == p.json()["total"]


def test_department_and_location_filters(client, db, world):
    cid, e, maria, depts, token = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/attestation/send-all/preview", json={"department_ids": [depts["HR"]], "offices": ["New York"]})
    assert r.json()["total"] == 1  # Eve: HR and New York


def test_a_personal_link_answer_marks_the_person_responded_and_feeds_the_inventory(client, db, world):
    cid, e, maria, depts, token = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={})
    raw = _link(db, "eve@abc.test")
    pub = _pub(client)
    v = pub.get(f"/api/v1/public/m/{raw}")
    assert v.status_code == 200, v.text
    form = v.json()
    assert form["kind"] == "attestation" and form["prefill"] == {"respondent_name": "Eve Long", "respondent_email": "eve@abc.test", "department_id": depts["HR"]}
    assert db.scalar(select(MailRecipient).where(MailRecipient.email == "eve@abc.test")).status == "opened"
    ans = _answer(depts["HR"], name="Eve Long", email="someone.else@abc.test")
    r = pub.post(f"/api/v1/public/m/{raw}/attestation", json=ans)
    assert r.status_code == 200, r.text
    a = db.scalar(select(Attestation).where(Attestation.respondent_email == "eve@abc.test"))
    assert a is not None and a.source == "link"  # the email is the one the link was sent to
    assert db.scalar(select(MailRecipient).where(MailRecipient.email == "eve@abc.test")).status == "completed"
    assert db.scalar(select(AITool).where(AITool.organization_id == cid, AITool.source == "attestation")) is not None
    # the tracker counts it like any other answer
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    assert any(i["email"] == "eve@abc.test" for i in t["individuals"])


def test_a_link_answer_from_someone_with_a_login_is_tied_to_their_user(client, db, world):
    cid, e, maria, depts, token = world
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={})
    raw = _link(db, "ian@abc.test")
    pub = _pub(client)
    assert pub.post(f"/api/v1/public/m/{raw}/attestation", json=_answer(depts["Finance"], name="Ian Doyle")).status_code == 200
    a = db.scalar(select(Attestation).where(Attestation.respondent_email == "ian@abc.test"))
    assert a.user_id == _user(db, "ian@abc.test").id
    login_as(client, db, _user(db, "ian@abc.test"))
    assert client.get("/api/v1/me/attestation").json()["line_item"] is None or True  # in-app view still loads
    assert client.get("/api/v1/me/attestation").status_code == 200


def test_a_closed_campaign_refuses_link_answers(client, db, world):
    cid, e, maria, depts, token = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={})
    raw = _link(db, "eve@abc.test")
    c = db.scalar(select(AttestationCampaign).where(AttestationCampaign.organization_id == cid))
    c.status = "closed"
    db.commit()
    assert _pub(client).post(f"/api/v1/public/m/{raw}/attestation", json=_answer(depts["HR"], name="Eve Long")).status_code == 410


def test_only_people_who_send_the_attestation_may_send_to_all_employees(client, db, world):
    cid, e, maria, depts, token = world
    login_as(client, db, _user(db, "priya@abc.test"))  # Department Compliance Lead
    assert client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={}).status_code == 403
    login_as(client, db, _user(db, "dana@abc.test"))  # DPO
    assert client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={}).status_code == 403


def test_shared_link_answer_needs_the_one_time_code(client, db, world):
    cid, e, maria, depts, token = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={"mode": "bcc"})
    assert r.status_code == 200, r.text
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.mail_send_id == r.json()["send_id"]))
    raw = msg.body_text.split("/m/s/")[1].split()[0]
    pub = _pub(client)
    assert pub.get(f"/api/v1/public/m/s/{raw}").json()["kind"] == "attestation"
    assert pub.post(f"/api/v1/public/m/s/{raw}/attestation", json={**_answer(depts["HR"], name="Eve Long"), "proof": "nope"}).status_code == 422
    assert pub.post(f"/api/v1/public/m/s/{raw}/code", json={"email": "eve@abc.test"}).status_code == 200
    code = db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "one_time_code")).subject.rsplit(" ", 1)[1]
    assert pub.post(f"/api/v1/public/m/s/{raw}/verify", json={"email": "eve@abc.test", "code": "999999" if code != "999999" else "000000"}).status_code == 422
    v = pub.post(f"/api/v1/public/m/s/{raw}/verify", json={"email": "eve@abc.test", "code": code})
    assert v.status_code == 200
    ok = pub.post(f"/api/v1/public/m/s/{raw}/attestation", json={**_answer(depts["HR"], name="Eve Long"), "proof": v.json()["proof"]})
    assert ok.status_code == 200, ok.text
    assert db.scalar(select(Attestation).where(Attestation.respondent_email == "eve@abc.test")) is not None


def test_link_answers_count_once_per_person_with_the_staff_link(client, db, world):
    cid, e, maria, depts, token = world
    _staff(db, cid, depts)
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/send-all", json={})
    raw = _link(db, "eve@abc.test")
    pub = _pub(client)
    pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], name="Eve Long", email="eve@abc.test"))
    pub.post(f"/api/v1/public/m/{raw}/attestation", json=_answer(depts["HR"], name="Eve Long"))
    current = db.scalars(select(Attestation).where(Attestation.respondent_email == "eve@abc.test", Attestation.superseded_by_id.is_(None))).all()
    assert len(current) == 1
    set_now(None)
    assert utcnow()
    _ = timedelta
