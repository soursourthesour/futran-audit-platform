import pytest

from app.audit_log.service import query
from app.auth.passwords import validate_password
from app.core.errors import Conflict
from app.tenancy.service import create_user
from tests.factories import make_org, make_user

PW = "Correct-Horse-2026"


def _setup(db):
    org = make_org(db, type="client")
    u = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com", password=PW)
    db.commit()
    return org, u


def test_login_success_sets_cookie_and_returns_csrf(client, db):
    _setup(db)
    r = client.post("/api/v1/auth/login", json={"email": "Priya@ABC.com", "password": PW})
    assert r.status_code == 200
    body = r.json()
    assert body["mfa_required"] is False
    assert body["csrf_token"]
    assert "fap_session" in r.cookies


def test_login_wrong_password_401_and_audited(client, db):
    org, u = _setup(db)
    r = client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": "nope-nope-nope"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Email or password is incorrect."
    db.expire_all()
    assert [e.action for e in query(db, organization_id=org.id, object_id=u.id)] == ["auth.login_failed"]


def test_login_unknown_email_same_message(client, db):
    _setup(db)
    r = client.post("/api/v1/auth/login", json={"email": "ghost@abc.com", "password": PW})
    assert r.status_code == 401
    assert r.json()["detail"] == "Email or password is incorrect."


def test_login_disabled_user_401(client, db):
    _, u = _setup(db)
    u.status = "disabled"
    db.commit()
    r = client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW})
    assert r.status_code == 401


def test_login_lockout_after_10_failures(client, db):
    _setup(db)
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": "wrong-password-x"})
    r = client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW})
    assert r.status_code == 429
    assert "15 minutes" in r.json()["detail"]


def test_password_policy_rejects_short():
    assert validate_password("short", "a@b.com") == ["Use at least 12 characters."]
    assert validate_password("a@b.com", "a@b.com")[-1] == "Do not use your email address as your password."
    assert validate_password("Long-Enough-Pass-1", "a@b.com") == []


def test_email_unique_across_platform(db):
    a = make_org(db, type="client", name="ABC Corp")
    b = make_org(db, type="client", name="BCD Inc")
    create_user(db, a, name="One", email="same@x.com")
    with pytest.raises(Conflict):
        create_user(db, b, name="Two", email="same@x.com")


def test_me_returns_user_roles_and_test_mode(client, db):
    _setup(db)
    client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW})
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "priya@abc.com"
    assert body["organization"]["type"] == "client"
    assert {"role": "caico", "scope_type": "org", "scope_id": None} in body["roles"]
    assert body["test_mode"] is True
    assert body["csrf_token"]


def test_me_without_session_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401
