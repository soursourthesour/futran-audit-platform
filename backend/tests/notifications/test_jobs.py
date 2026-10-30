from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.core import clock
from app.engagements.models import Engagement
from app.governance.models import Commitment
from app.invitations.models import Invitation
from app.invitations.service import invite_user
from app.mail.models import OutboxMessage
from app.notifications import jobs
from app.notifications.events import EVENTS
from app.notifications.models import Notification
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def test_events_table_covers_spec_14():
    assert len(EVENTS) == 9
    assert {e.key for e in EVENTS.values()} == {
        "engagement_submitted", "package_sent", "invitation_expiring", "sign_off_role_changed", "sign_off_awaiting",
        "evidence_request", "finding_returned", "remediation_done", "overdue_digest",
    }
    assert EVENTS["finding_returned"].channels == ("in_app",)
    assert EVENTS["sign_off_awaiting"].channels == ("in_app", "email")
    assert EVENTS["overdue_digest"].channels == ("digest",)


def _pending(db, live):
    cid, e, maria = live
    tom = User(organization_id=cid, name="Tom Reyes", email="tom@abc.test", status="invited")
    db.add(tom)
    db.flush()
    return tom


def test_invitation_48h_warning_once(client, db, live, settings, people):
    tom = _pending(db, live)
    invite_user(db, settings, people["aud"], tom)
    db.commit()
    inv = db.scalar(select(Invitation).where(Invitation.user_id == tom.id))
    soon = inv.expires_at - timedelta(hours=30)
    assert jobs.run_invitation_warnings(db, settings, soon) == 1
    assert jobs.run_invitation_warnings(db, settings, soon + timedelta(hours=2)) == 0
    mail = db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "invitation_expiring")).all()
    assert len(mail) == 1 and mail[0].to == ["tom@abc.test"]
    assert jobs.run_invitation_warnings(db, settings, inv.expires_at - timedelta(days=5)) == 0


def test_expired_invitation_marked_and_futran_notified(client, db, live, settings, people):
    tom = _pending(db, live)
    invite_user(db, settings, people["aud"], tom)
    db.commit()
    inv = db.scalar(select(Invitation).where(Invitation.user_id == tom.id))
    assert jobs.run_invitation_expiry(db, settings, inv.expires_at + timedelta(minutes=1)) >= 1  # other pending invitations from setup expire too
    db.expire_all()
    assert db.get(Invitation, inv.id).status == "expired"
    notes = db.scalars(select(Notification).where(Notification.kind == "invitation_expired")).all()
    tom_notes = [n for n in notes if "Tom Reyes" in n.title]
    assert people["chief"].id in {n.user_id for n in tom_notes}
    assert jobs.run_invitation_expiry(db, settings, inv.expires_at + timedelta(days=1)) == 0


def test_weekly_digest_groups_by_owner(client, db, live, settings, people):
    cid, e, maria = live
    for owner, desc, days in [("Priya Shah", "Constitute bias committee", 10), ("Priya Shah", "Create RACI", 3), ("Raj Iyer", "Appoint security owner", 1), ("Raj Iyer", "Not due yet", -5)]:
        db.add(Commitment(organization_id=cid, engagement_id=e.id, source="governance_role", source_id="x", description=desc, target_date=date(2026, 11, 16) - timedelta(days=days), owner=owner, status="open"))
    db.commit()
    monday = date(2026, 11, 16)
    assert jobs.run_weekly_digest(db, settings, monday + timedelta(days=1)) == 0  # Tuesday: nothing
    n = jobs.run_weekly_digest(db, settings, monday)
    assert n >= 2  # the CAICO and the assigned auditors
    mail = db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "overdue_digest", OutboxMessage.to == ["maria@abc.test"]))
    body = mail.body_text
    assert body.index("Priya Shah") < body.index("Constitute bias committee") < body.index("Raj Iyer") < body.index("Appoint security owner")
    assert "Not due yet" not in body
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "overdue_digest", OutboxMessage.to == [people["aud"].email])) is not None


def test_sign_off_awaiting_sends_email_and_bell_lists_it(client, db, live, settings, people):
    from app.notifications.service import notify

    cid, e, maria = live
    notify(db, [maria], "sign_off_awaiting", "Sign-off 3 is waiting for you", "Inventory review", "/inventory", engagement=e, settings=settings)
    db.commit()
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "notification", OutboxMessage.to == ["maria@abc.test"])) is not None
    login_as(client, db, maria)
    r = client.get("/api/v1/me/notifications").json()
    assert r["unread"] >= 1 and r["items"][0]["title"] == "Sign-off 3 is waiting for you"
    nid = r["items"][0]["id"]
    assert client.post(f"/api/v1/notifications/{nid}/read").status_code == 200
    assert client.get("/api/v1/me/notifications").json()["unread"] == r["unread"] - 1
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/notifications/{nid}/read").status_code == 404
    assert client.post("/api/v1/notifications/read-all").status_code == 200


def test_run_daily_runs_every_job(client, db, live, settings):
    out = jobs.run_daily(db, settings, datetime(2026, 11, 16, 6, 0))
    assert set(out) == {"invitation_warnings", "invitation_expiry", "due_soon", "escalations", "weekly_digest", "email"}
