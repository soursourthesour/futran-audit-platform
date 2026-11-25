"""One demo world per test module for the permission tests: the full demo seed (ABC Corp completed, Meridian GmbH at
stage 3, and the wave 3 and Release 2 data), built once because it takes about a minute.

Each request goes through the real app, the real session cookie and CSRF check, and the real database."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings

WORKBOOK = Path(__file__).resolve().parents[2] / "seeds" / "law_matrix.xlsx"


def make_settings(file_dir: str) -> Settings:
    return Settings(database_url="sqlite://", mfa_required=False, email_mode="outbox", secret_key="test-secret-key-not-for-production-0123456789",
                    disable_scheduler=True, seed_on_start=False, file_store=f"local:{file_dir}")


def make_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    from app.core.models import Base
    import app.models_registry  # noqa: F401

    Base.metadata.create_all(eng)
    return eng


class World:
    def __init__(self, file_dir: str, demo: bool = True):
        from app.main import create_app

        self.settings = make_settings(file_dir)
        self.engine = make_engine()
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.app = create_app(self.settings, engine=self.engine)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.ids: dict = {}
        if demo:
            self._seed_demo()

    def _seed_demo(self):
        from app.demo.seed_demo import run
        from app.laws.importer import parse_workbook
        from app.laws.publish import publish
        from app.reference import LOADERS
        from app.reference.jurisdictions import seed_iso

        seed_iso(self.db)
        publish(self.db, parse_workbook(WORKBOOK), None, {}, organization_id="futran")
        for name, loader in LOADERS:
            if name != "Law matrix" and not name.startswith("Jurisdictions"):
                loader(self.db)
        self.db.commit()
        self.ids = run(self.db, self.settings, client=self.client)
        self.client.cookies.clear()

    def login(self, user) -> TestClient:
        from tests.factories import login_as

        self.client.cookies.clear()
        self.client.headers.pop("X-CSRF-Token", None)
        return login_as(self.client, self.db, user)

    def logout(self) -> TestClient:
        self.client.cookies.clear()
        self.client.headers.pop("X-CSRF-Token", None)
        return self.client

    def close(self):
        self.client.__exit__(None, None, None)
        self.db.close()
        self.engine.dispose()
