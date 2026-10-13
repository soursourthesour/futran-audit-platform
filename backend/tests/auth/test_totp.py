import pyotp
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.factories import make_org, make_user

PW = "Correct-Horse-2026"


@pytest.fixture
def mfa_client(settings, engine):
    app = create_app(settings.model_copy(update={"mfa_required": True}), engine=engine)
    with TestClient(app) as c:
        yield c


def _login(c, db):
    org = make_org(db, type="client")
    make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com", password=PW)
    db.commit()
    r = c.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW})
    assert r.status_code == 200
    return r.json()


def test_mfa_required_blocks_me_until_verified(mfa_client, db):
    body = _login(mfa_client, db)
    assert body["mfa_required"] is True and body["mfa_enrolled"] is False
    r = mfa_client.get("/api/v1/auth/me")
    assert r.status_code == 403
    assert r.json()["detail"] == "mfa_required"


def test_totp_enroll_then_verify_marks_session(mfa_client, db):
    body = _login(mfa_client, db)
    h = {"X-CSRF-Token": body["csrf_token"]}
    enroll = mfa_client.post("/api/v1/auth/mfa/enroll", headers=h).json()
    assert enroll["otpauth_uri"].startswith("otpauth://totp/")
    bad = mfa_client.post("/api/v1/auth/mfa/verify", json={"code": "000000"}, headers=h)
    assert bad.status_code == 401
    code = pyotp.TOTP(enroll["secret"]).now()
    ok = mfa_client.post("/api/v1/auth/mfa/verify", json={"code": code}, headers=h)
    assert ok.status_code == 200
    assert mfa_client.get("/api/v1/auth/me").status_code == 200


def test_enrolled_user_cannot_re_enroll_and_must_verify(mfa_client, db):
    body = _login(mfa_client, db)
    h = {"X-CSRF-Token": body["csrf_token"]}
    secret = mfa_client.post("/api/v1/auth/mfa/enroll", headers=h).json()["secret"]
    mfa_client.post("/api/v1/auth/mfa/verify", json={"code": pyotp.TOTP(secret).now()}, headers=h)
    mfa_client.post("/api/v1/auth/logout", headers=h)
    body2 = mfa_client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW}).json()
    assert body2["mfa_enrolled"] is True
    h2 = {"X-CSRF-Token": body2["csrf_token"]}
    assert mfa_client.post("/api/v1/auth/mfa/enroll", headers=h2).status_code == 409
