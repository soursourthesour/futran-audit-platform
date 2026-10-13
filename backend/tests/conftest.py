import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        mfa_required=False,
        email_mode="outbox",
        secret_key="test-secret-key-not-for-production-0123456789",
        disable_scheduler=True,
        file_store="local:./data/test-files",
    )


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    from app.core.models import Base
    import app.models_registry  # noqa: F401  (imports every domain model)

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def app(settings, engine):
    from app.main import create_app

    return create_app(settings, engine=engine)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
