"""A realistic world for the home screens, built once per module: the browser-test data (ABC Corp at stage 6 with every
client role, Meridian GmbH at stage 3 whose CAICO is also its Client Admin), created through the platform's own API."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    settings = Settings(database_url="sqlite://", mfa_required=False, email_mode="outbox", secret_key="test-secret-key-not-for-production-0123456789",
                        disable_scheduler=True, seed_on_start=False, file_store=f"local:{tmp_path_factory.mktemp('files')}")
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    from app.core.models import Base
    import app.models_registry  # noqa: F401

    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng, expire_on_commit=False)()
    from app.demo.seed_demo import e2e_late
    from app.reference import LOADERS
    from app.tenancy.models import Organization
    from app.tenancy.service import create_organization

    if db.scalar(select(Organization).where(Organization.type == "futran")) is None:
        create_organization(db, name="Futran Solutions", type="futran")
    for _name, loader in LOADERS:
        loader(db)
    db.commit()
    ids = e2e_late(db, settings)
    from app.main import create_app

    app = create_app(settings, engine=eng)
    yield {"db": db, "app": app, "ids": ids, "settings": settings}
    db.close()
    eng.dispose()


@pytest.fixture
def as_user(world):
    """as_user(email) -> a TestClient signed in as that person."""
    from app.tenancy.models import User
    from tests.factories import login_as

    clients = []

    def _as(email: str) -> TestClient:
        db = world["db"]
        c = TestClient(world["app"])
        clients.append(c)
        u = db.scalar(select(User).where(User.email == email))
        assert u is not None, email
        return login_as(c, db, u)

    yield _as
    for c in clients:
        c.close()
