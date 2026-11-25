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


def test_outbox_goes_through_authorize_with_view_outbox(client, db, monkeypatch):
    """Y01: the outbox used a hand-written role check; it now asks the permission matrix like every other route."""
    from app.mail import router as outbox_router
    from app.policy.actions import Action
    from app.policy.matrix import Scope, scopes_for

    assert scopes_for({"admin"}, Action.VIEW_OUTBOX) == {Scope.ALL}
    assert scopes_for({"chief_auditor"}, Action.VIEW_OUTBOX) == {Scope.ALL}
    for role in ("auditor", "qa_reviewer", "engagement_manager", "sales_team", "caico", "client_admin"):
        assert not scopes_for({role}, Action.VIEW_OUTBOX), role
    futran = make_org(db, type="futran")
    chief = make_user(db, futran, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    org = make_org(db, type="client")
    cadmin = make_user(db, org, roles=["client_admin"], name="Cleo Admin", email="cleo@abc.com")
    db.commit()
    seen = []
    real = outbox_router.authorize

    def spy(db_, actor, action, **kw):
        seen.append(action)
        return real(db_, actor, action, **kw)

    monkeypatch.setattr(outbox_router, "authorize", spy)
    login_as(client, db, chief)
    assert client.get("/api/v1/admin/outbox").status_code == 200
    assert seen == [Action.VIEW_OUTBOX]
    login_as(client, db, cadmin)
    assert client.get("/api/v1/admin/outbox").status_code in (403, 404)
