"""BUG-H02: unsuccessful sign-ins are also limited per address across every account (password spraying), and a
forwarded address is believed only when TRUST_PROXY_HEADERS is set."""
from pathlib import Path
from types import SimpleNamespace

from app.auth.service import IP_LOCKOUT_FAILURES
from app.core.ratelimit import client_ip
from tests.factories import make_org, make_user

PW = "Correct-Horse-2026"
REPO = Path(__file__).resolve().parents[3]


def _setup(db):
    org = make_org(db, type="client")
    u = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com", password=PW)
    db.commit()
    return u


def _spray(client, n, headers=None):
    return [client.post("/api/v1/auth/login", json={"email": f"person{i}@abc.com", "password": "Spring2026!"}, headers=headers or {}).status_code for i in range(n)]


def test_one_address_spraying_many_accounts_is_locked_out(client, db):
    _setup(db)
    assert _spray(client, IP_LOCKOUT_FAILURES) == [401] * IP_LOCKOUT_FAILURES
    r = client.post("/api/v1/auth/login", json={"email": "someone.else@abc.com", "password": "Spring2026!"})
    assert r.status_code == 429
    assert "15 minutes" in r.json()["detail"]
    # Locked for that address even with the right password: guessing on stops being useful.
    r = client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW})
    assert r.status_code == 429


def test_the_address_limit_is_per_address(client, db, settings):
    _setup(db)
    client.app.state.settings = settings.model_copy(update={"trust_proxy_headers": True})
    _spray(client, IP_LOCKOUT_FAILURES, headers={"X-Forwarded-For": "203.0.113.5"})
    assert client.post("/api/v1/auth/login", json={"email": "x@abc.com", "password": "nope"}, headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 429
    r = client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW}, headers={"X-Forwarded-For": "198.51.100.7"})
    assert r.status_code == 200, r.text


def test_the_per_account_lock_still_holds(client, db):
    _setup(db)
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": "wrong-password-x"})
    assert client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW}).status_code == 429
    assert client.post("/api/v1/auth/login", json={"email": "other@abc.com", "password": "nope"}).status_code == 401


def test_forwarded_header_is_ignored_unless_trusted(settings):
    settings.trust_proxy_headers = False
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)), headers={"x-forwarded-for": "6.6.6.6"}, client=SimpleNamespace(host="10.0.0.1"))
    assert client_ip(req) == "10.0.0.1"


def test_launchers_stop_uvicorn_rewriting_the_client_address():
    """uvicorn trusts X-Forwarded-For from 127.0.0.1 by default and rewrites the client address before the app sees it,
    which made TRUST_PROXY_HEADERS meaningless on the laptop. The app decides which header to believe."""
    for name in ("run.bat", "Dockerfile", "e2e/start-server.sh"):
        lines = [ln for ln in (REPO / name).read_text().splitlines() if "uvicorn --factory" in ln or "uvicorn  --factory" in ln]
        assert lines, name
        assert all("--no-proxy-headers" in ln for ln in lines), name


def test_a_few_people_mistyping_do_not_lock_out_their_office(client, db):
    """Review 11-25 #1: the address limit counts distinct accounts, so repeated typos by a handful of people behind one
    office address never reach it; only spraying many accounts does."""
    _setup(db)
    for _ in range(4):
        for i in range(5):  # 5 people, 4 typos each: 20 failures, 5 accounts
            assert client.post("/api/v1/auth/login", json={"email": f"person{i}@abc.com", "password": "typo"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW})
    assert r.status_code == 200, r.text


def test_an_administrator_can_clear_an_address_lock(client, db):
    """Review 11-25 #1: a command clears one address's recent failures."""
    from app.auth.service import clear_login_lock

    _setup(db)
    _spray(client, IP_LOCKOUT_FAILURES)
    assert client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW}).status_code == 429
    assert clear_login_lock(db, "testclient") == IP_LOCKOUT_FAILURES
    db.commit()
    assert client.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW}).status_code == 200
