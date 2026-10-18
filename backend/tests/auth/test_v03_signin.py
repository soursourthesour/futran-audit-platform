"""Spec v0.3 screens 1, 9a and 9b: separate staff and client sign-in, the invitation steps, recovery codes, terms."""
import pyotp
from sqlalchemy import select

from app.auth.passwords import validate_password
from app.invitations.models import Invitation
from app.invitations.service import invite_user
from app.notifications.models import Notification
from tests.factories import make_org, make_user
from tests.invitations.test_invitations import _token_from_last_email

PW = "Correct-Horse-2026"


def _people(db):
    futran = make_org(db, type="futran")
    admin = make_user(db, futran, roles=["admin"], name="Ada Admin", email="admin@futran.test", password=PW)
    org = make_org(db, type="client")
    caico = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com", password=PW)
    db.commit()
    return admin, caico


def _login(client, email, portal):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PW, "portal": portal})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r


def test_staff_and_client_portals_are_separate(client, db):
    admin, caico = _people(db)
    r = client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW, "portal": "staff"})
    assert r.status_code == 401 and "client sign-in" in r.json()["detail"]
    r = client.post("/api/v1/auth/login", json={"email": "admin@futran.test", "password": PW, "portal": "client"})
    assert r.status_code == 401 and "staff sign-in" in r.json()["detail"]
    assert "fa_session" not in r.cookies and client.get("/api/v1/auth/me").status_code == 401
    # a wrong password never reveals which portal the account belongs to
    r = client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": "Wrong-password-1", "portal": "staff"})
    assert r.status_code == 401 and "client" not in r.json()["detail"]
    assert client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW, "portal": "client"}).status_code == 200


def test_breached_and_trivial_passwords_rejected():
    for pw in ("password1234", "Password12345", "123456789012", "qwertyuiop123", "aaaaaaaaaaaa", "iloveyou2026!"):
        assert validate_password(pw, "x@y.com"), pw
    assert validate_password("Correct-Horse-2026", "x@y.com") == []


def test_not_you_cancels_invitation(client, db, settings):
    admin, _ = _people(db)
    org = make_org(db, type="client", name="Other Co")
    u = make_user(db, org, roles=["caico"], name="Sam Lee", email="sam@other.test")
    u.status, u.password_hash = "invited", None
    db.commit()
    invite_user(db, settings, admin, u)
    db.commit()
    token = _token_from_last_email(db, "sam@other.test")
    info = client.get(f"/api/v1/invitations/accept/{token}").json()
    assert info["name"] == "Sam Lee" and info["roles"] == ["Chief AI Compliance Officer"]
    assert client.post(f"/api/v1/invitations/decline/{token}").status_code == 200
    db.expire_all()
    assert db.scalar(select(Invitation).where(Invitation.user_id == u.id)).status == "revoked"
    assert client.post(f"/api/v1/invitations/accept/{token}", json={"password": PW}).status_code in (404, 409, 410)
    assert admin.id in {n.user_id for n in db.scalars(select(Notification).where(Notification.kind == "invitation_declined"))}


def test_recovery_codes_issued_once_and_single_use(client, db, settings):
    admin, caico = _people(db)
    settings.mfa_required = True
    client.app.state.settings = settings
    _login(client, "priya@abc.com", "client")
    secret = client.post("/api/v1/auth/mfa/enroll").json()["secret"]
    r = client.post("/api/v1/auth/mfa/verify", json={"code": pyotp.TOTP(secret).now()})
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    client.post("/api/v1/auth/logout")
    _login(client, "priya@abc.com", "client")
    assert client.post("/api/v1/auth/mfa/verify", json={"code": codes[0]}).json() == {"ok": True}
    client.post("/api/v1/auth/logout")
    _login(client, "priya@abc.com", "client")
    assert client.post("/api/v1/auth/mfa/verify", json={"code": codes[0]}).status_code == 401


def test_client_must_accept_terms(client, db):
    admin, caico = _people(db)
    _login(client, "priya@abc.com", "client")
    me = client.get("/api/v1/auth/me").json()
    assert me["terms_required"] is True
    assert client.get("/api/v1/me/initiation").status_code == 403
    assert client.post("/api/v1/auth/terms", json={"accepted": False}).status_code == 422
    assert client.post("/api/v1/auth/terms", json={"accepted": True}).status_code == 200
    assert client.get("/api/v1/auth/me").json()["terms_required"] is False
    client.post("/api/v1/auth/logout")
    _login(client, "admin@futran.test", "staff")
    assert client.get("/api/v1/auth/me").json()["terms_required"] is False
