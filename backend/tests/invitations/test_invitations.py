import re
from datetime import timedelta

import pytest

from app.core import clock
from app.core.errors import Conflict
from app.invitations.models import Invitation
from app.invitations.service import accept_invitation, invite_user
from app.mail.models import OutboxMessage
from tests.factories import make_org, make_user


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.set_now(None)


def _setup(db):
    futran = make_org(db, type="futran")
    admin = make_user(db, futran, roles=["admin"], name="Ada Admin", email="admin@futran.test")
    org = make_org(db, type="client")
    u = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com", status="invited")
    u.status = "invited"
    db.flush()
    return admin, u


def _token_from_last_email(db, to):
    msg = db.query(OutboxMessage).filter(OutboxMessage.to.contains(to)).order_by(OutboxMessage.created_at.desc()).first()
    m = re.search(r"/invite/([A-Za-z0-9_\-]+)", msg.body_text)
    return m.group(1)


def test_invite_expires_after_7_days(db, settings):
    admin, u = _setup(db)
    start = clock.utcnow()
    clock.set_now(start)
    inv = invite_user(db, settings, admin, u)
    assert inv.expires_at == start + timedelta(days=7)
    token = _token_from_last_email(db, u.email)
    clock.set_now(start + timedelta(days=7, minutes=1))
    with pytest.raises(Conflict, match="expired"):
        accept_invitation(db, settings, token, "A-Long-Password-2026")


def test_resend_invalidates_previous_token(db, settings):
    admin, u = _setup(db)
    invite_user(db, settings, admin, u)
    first = _token_from_last_email(db, u.email)
    clock.set_now(clock.utcnow() + timedelta(seconds=5))
    invite_user(db, settings, admin, u)
    second = _token_from_last_email(db, u.email)
    assert first != second
    with pytest.raises(Conflict):
        accept_invitation(db, settings, first, "A-Long-Password-2026")
    assert accept_invitation(db, settings, second, "A-Long-Password-2026").status == "active"
    assert db.query(Invitation).filter_by(user_id=u.id, status="revoked").count() == 1


def test_accept_sets_password_and_activates(db, settings):
    admin, u = _setup(db)
    invite_user(db, settings, admin, u)
    token = _token_from_last_email(db, u.email)
    user = accept_invitation(db, settings, token, "A-Long-Password-2026")
    assert user.status == "active"
    assert user.password_hash and user.password_hash != "A-Long-Password-2026"


def test_accept_used_token_rejected(db, settings):
    admin, u = _setup(db)
    invite_user(db, settings, admin, u)
    token = _token_from_last_email(db, u.email)
    accept_invitation(db, settings, token, "A-Long-Password-2026")
    with pytest.raises(Conflict):
        accept_invitation(db, settings, token, "A-Long-Password-2026")


def test_accept_weak_password_rejected(db, settings):
    from app.core.errors import Invalid

    admin, u = _setup(db)
    invite_user(db, settings, admin, u)
    token = _token_from_last_email(db, u.email)
    with pytest.raises(Invalid):
        accept_invitation(db, settings, token, "short")


def test_accept_api_flow(client, db):
    admin, u = _setup(db)
    invite_user(db, client.app.state.settings, admin, u)
    db.commit()
    token = _token_from_last_email(db, u.email)
    info = client.get(f"/api/v1/invitations/accept/{token}").json()
    assert info == {"email": "priya@abc.com", "name": "Priya Shah", "organization_name": "ABC Corp", "expired": False, "used": False}
    r = client.post(f"/api/v1/invitations/accept/{token}", json={"password": "A-Long-Password-2026"})
    assert r.status_code == 200
    assert r.json()["csrf_token"]
    assert client.get("/api/v1/auth/me").status_code == 200
