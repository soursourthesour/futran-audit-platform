"""A slow address provider must not hold the database write lock.

On a laptop the database is a single SQLite file. If a request keeps its write transaction open while it waits for an
outside service, every other request that writes fails with "database is locked". Signing in touches the session row,
so even a read-only request starts a write transaction; that write must be committed before the slow call starts.
"""
import sqlite3
import threading

import httpx
import pytest

from app.core.db import make_engine
from app.geo import service as geo
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "lock.db"


@pytest.fixture
def engine(db_path):
    """A real file in WAL mode, as on the laptop, instead of the shared in-memory database."""
    from app.core.models import Base
    import app.models_registry  # noqa: F401

    eng = make_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def auditor(db, matrix):
    f = make_org(db, type="futran")
    u = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    db.commit()
    return u


def test_slow_address_lookup_leaves_the_database_writable(client, db, auditor, db_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def slow(request):
        entered.set()
        release.wait(10)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    geo.clear_cache()
    monkeypatch.setattr(geo, "TRANSPORT", httpx.MockTransport(slow))
    client.app.state.settings.address_autocomplete = "photon"
    login_as(client, db, auditor)
    db.close()

    result = {}
    t = threading.Thread(target=lambda: result.setdefault("r", client.get("/api/v1/geo/suggest", params={"q": "350 Fifth Avenue"})))
    t.start()
    try:
        assert entered.wait(10), "the lookup never reached the provider"
        other = sqlite3.connect(db_path, timeout=0.5)
        try:
            other.execute("BEGIN IMMEDIATE")  # fails with "database is locked" while the request holds the write lock
            other.rollback()
        finally:
            other.close()
    finally:
        release.set()
        t.join(10)
        geo.clear_cache()
    assert result["r"].status_code == 200, result["r"].text
