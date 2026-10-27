"""Employee AI audit and data notice: the CAICO edits and sends it; every client user acknowledges the current version."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.initiation.models import PackageDocument
from app.mail.models import OutboxMessage
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def _add(client, cid, first, last, email, role="client_admin", department=""):
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": first, "last_name": last, "email": email, "job_title": "", "department": department, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _active(db, user_id):
    u = db.get(User, user_id)
    u.status = "active"
    db.commit()
    return u


def test_only_the_caico_edits_the_notice(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    sam = _active(db, _add(client, cid, "Sam", "Admin", "sam@abc.test"))
    n = client.get("/api/v1/me/notice").json()
    assert n["can_edit"] is True and "52-c" in n["document"]["html"] and n["document"]["body_md"]
    assert n["sent"] is None
    r = client.put("/api/v1/me/notice", json={"body_md": "# Employee AI audit and data notice\n\nRevised wording for staff."})
    assert r.status_code == 200, r.text
    doc = db.scalar(select(PackageDocument).where(PackageDocument.engagement_id == e.id, PackageDocument.item == 5))
    db.refresh(doc)
    assert "Revised wording" in doc.body_md and doc.edited and doc.pdf_file_id and doc.docx_file_id
    assert db.scalar(select(AuditLog).where(AuditLog.action == "notice.edit", AuditLog.object_id == doc.id)) is not None
    assert client.put("/api/v1/me/notice", json={"body_md": "   "}).status_code == 422
    # a Client Admin who is not the CAICO can read it but not change or send it
    login_as(client, db, sam)
    n = client.get("/api/v1/me/notice").json()
    assert n["can_edit"] is False and n["document"]["body_md"] is None and "Revised wording" in n["document"]["html"]
    assert client.put("/api/v1/me/notice", json={"body_md": "Changed"}).status_code == 403
    assert client.post("/api/v1/me/notice/send").status_code == 403


def test_send_emails_every_user_completes_item_6_and_asks_each_user_to_acknowledge(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Finance"})
    sam = _active(db, _add(client, cid, "Sam", "Admin", "sam@abc.test"))
    tom_id = _add(client, cid, "Tom", "Reyes", "tom@abc.test", role="contributor", department="Finance")  # invited, never signed in
    assert client.get("/api/v1/auth/me").json()["notice_required"] is False  # nothing sent yet
    r = client.post("/api/v1/me/notice/send")
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1 and r.json()["recipients"] == 3
    mails = db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "employee_data_notice")).all()
    assert sorted(m.to[0] for m in mails) == ["maria@abc.test", "sam@abc.test", "tom@abc.test"]
    assert "Employee AI audit and data notice" in mails[0].subject
    items = {i["key"]: i for i in client.get("/api/v1/me/initiation").json()["items"]}
    assert items["notice"]["done"] is True
    assert items["notice"]["title"] == "Review employee AI audit and data notice and kick off audit"
    assert items["notice"]["acknowledgements"] == {"acknowledged": 1, "pending": 2, "version": 1}
    # the sender has read it; everyone else must acknowledge on their next sign-in
    assert client.get("/api/v1/auth/me").json()["notice_required"] is False
    login_as(client, db, sam)
    assert client.get("/api/v1/auth/me").json()["notice_required"] is True
    pending = client.get("/api/v1/me/notice/pending").json()
    assert pending["version"] == 1 and "52-c" in pending["html"]
    assert client.post("/api/v1/me/notice/acknowledge", json={"version": 1, "accepted": False}).status_code == 422
    assert client.post("/api/v1/me/notice/acknowledge", json={"version": 1, "accepted": True}).status_code == 200
    assert client.get("/api/v1/auth/me").json()["notice_required"] is False
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "notice.acknowledge", AuditLog.actor_id == sam.id))
    assert entry is not None and entry.after["version"] == 1 and entry.after["user_id"] == sam.id
    # People > Users shows who has acknowledged
    login_as(client, db, maria)
    users = {u["email"]: u for u in client.get(f"/api/v1/clients/{cid}/people").json()["users"]}
    assert users["sam@abc.test"]["notice"]["status"] == "acknowledged" and users["sam@abc.test"]["notice"]["at"]
    assert users["tom@abc.test"]["notice"]["status"] == "pending"
    assert tom_id


def test_a_new_version_must_be_acknowledged_again(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    sam = _active(db, _add(client, cid, "Sam", "Admin", "sam@abc.test"))
    client.post("/api/v1/me/notice/send")
    login_as(client, db, sam)
    client.post("/api/v1/me/notice/acknowledge", json={"version": 1, "accepted": True})
    login_as(client, db, maria)
    client.put("/api/v1/me/notice", json={"body_md": "# Notice\n\nVersion two."})
    n = client.get("/api/v1/me/notice").json()
    assert n["unsent_changes"] is True and n["sent"]["version"] == 1
    login_as(client, db, sam)
    assert client.get("/api/v1/auth/me").json()["notice_required"] is False  # edits alone do not reach staff
    login_as(client, db, maria)
    assert client.post("/api/v1/me/notice/send").json()["version"] == 2
    login_as(client, db, sam)
    assert client.get("/api/v1/auth/me").json()["notice_required"] is True
    p = client.get("/api/v1/me/notice/pending").json()
    assert p["version"] == 2 and "Version two" in p["html"]
    assert client.post("/api/v1/me/notice/acknowledge", json={"version": 1, "accepted": True}).status_code == 409  # stale version
    assert client.post("/api/v1/me/notice/acknowledge", json={"version": 2, "accepted": True}).status_code == 200
    assert db.query(AuditLog).filter(AuditLog.action == "notice.acknowledge", AuditLog.actor_id == sam.id).count() == 2


def test_legacy_done_endpoint_sends_the_notice(client, db, people, live):
    """Item 6 used to be ticked off; the same call now sends the notice so the attestation gate keeps working."""
    cid, e, maria = live
    login_as(client, db, maria)
    assert client.post("/api/v1/me/initiation/items/notice/done").status_code == 200
    assert client.get("/api/v1/me/notice").json()["sent"]["version"] == 1
    from app.attestation.service import notice_acknowledged

    db.expire_all()
    assert notice_acknowledged(db, e)


def test_other_organizations_cannot_see_the_notice(client, db, people, live):
    from tests.factories import make_org, make_user

    cid, e, maria = live
    login_as(client, db, maria)
    client.post("/api/v1/me/notice/send")
    other = make_org(db, name="XYZ")
    boss = make_user(db, other, roles=["caico"], name="X Officer", email="x@xyz.test")
    db.commit()
    login_as(client, db, boss)
    assert client.get("/api/v1/me/notice").status_code == 404
    assert client.get("/api/v1/auth/me").json()["notice_required"] is False
    login_as(client, db, people["aud"])
    assert client.get("/api/v1/me/notice").status_code == 404
