from app.invitations.service import invite_user
from app.mail.models import OutboxMessage
from app.mail.service import send
from tests.factories import login_as, make_org, make_user


def test_outbox_mode_stores_message_with_rendered_subject(db, settings):
    org = make_org(db, type="client")
    msg = send(
        db,
        settings,
        "test_message",
        to=["priya@abc.com"],
        context={"organization_name": "ABC Corp", "body": "Hello"},
        organization_id=org.id,
    )
    assert msg.status == "sent"
    assert msg.subject == "ABC Corp: test message"
    assert "Hello" in msg.body_html and "Hello" in msg.body_text
    assert db.query(OutboxMessage).count() == 1


def test_invitation_email_has_no_attachments_and_contains_accept_link(db, settings):
    futran = make_org(db, type="futran")
    admin = make_user(db, futran, roles=["admin"], name="Ada Admin", email="admin@futran.test")
    org = make_org(db, type="client")
    u = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com")
    invite_user(db, settings, admin, u)
    msg = db.query(OutboxMessage).one()
    assert msg.to == ["priya@abc.com"]
    assert msg.attachments in (None, [])
    assert f"{settings.base_url}/invite/" in msg.body_text
    assert "expires in 7 days" in msg.body_text
    assert "Documents are not attached to this email" in msg.body_text


def test_outbox_viewer_admin_only(client, db):
    futran = make_org(db, type="futran")
    admin = make_user(db, futran, roles=["admin"], name="Ada Admin", email="admin@futran.test")
    auditor = make_user(db, futran, roles=["auditor"], name="Al Auditor", email="al@futran.test")
    org = make_org(db, type="client")
    send(db, client.app.state.settings, "test_message", to=["x@abc.com"], context={"organization_name": "ABC Corp", "body": "Hi"}, organization_id=org.id)
    db.commit()
    login_as(client, db, auditor)
    assert client.get("/api/v1/admin/outbox").status_code == 403
    login_as(client, db, admin)
    r = client.get("/api/v1/admin/outbox")
    assert r.status_code == 200
    assert r.json()[0]["subject"] == "ABC Corp: test message"
