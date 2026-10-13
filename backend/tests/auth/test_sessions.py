from datetime import timedelta

import pytest

from app.core import clock
from tests.factories import make_org, make_user

PW = "Correct-Horse-2026"


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.set_now(None)


def _login(client, db):
    org = make_org(db, type="client")
    make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com", password=PW)
    db.commit()
    r = client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW})
    return r.json()["csrf_token"]


def test_idle_timeout_expires_session(client, db):
    start = clock.utcnow()
    clock.set_now(start)
    _login(client, db)
    assert client.get("/api/v1/auth/me").status_code == 200
    clock.set_now(start + timedelta(minutes=31))
    assert client.get("/api/v1/auth/me").status_code == 401


def test_activity_keeps_session_alive_until_absolute_timeout(client, db):
    start = clock.utcnow()
    clock.set_now(start)
    _login(client, db)
    t = start
    while t < start + timedelta(hours=11, minutes=59):
        t += timedelta(minutes=20)
        clock.set_now(t)
        if t < start + timedelta(hours=12):
            assert client.get("/api/v1/auth/me").status_code == 200
    clock.set_now(start + timedelta(hours=12, minutes=1))
    assert client.get("/api/v1/auth/me").status_code == 401


def test_csrf_required_on_post(client, db):
    csrf = _login(client, db)
    assert client.post("/api/v1/auth/logout").status_code == 403
    r = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
