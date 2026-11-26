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
        seed_on_start=False,
        file_store="local:./data/test-files",
    )


PG_URL = __import__("os").environ.get("FAP_TEST_DATABASE_URL")  # opt in: run the suite on PostgreSQL (the AWS target)
_pg_engine = None


def _pg():
    """One PostgreSQL engine for the session: the schema is created once and every table is emptied before each test."""
    global _pg_engine
    from app.core.models import Base
    import app.models_registry  # noqa: F401

    if _pg_engine is None:
        _pg_engine = create_engine(PG_URL)
        with _pg_engine.begin() as c:  # start from an empty schema (drop_all cannot drop the unnamed circular foreign keys)
            c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        Base.metadata.create_all(_pg_engine)
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with _pg_engine.begin() as c:
        c.exec_driver_sql(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
    return _pg_engine


@pytest.fixture
def engine():
    if PG_URL:
        yield _pg()
        return
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


# ---- law matrix (published once per test; parsed once per session)
from pathlib import Path  # noqa: E402

from app.laws.importer import parse_workbook  # noqa: E402
from app.laws.publish import publish  # noqa: E402
from app.reference.jurisdictions import seed_iso  # noqa: E402

WORKBOOK = Path(__file__).resolve().parents[1] / "seeds" / "law_matrix.xlsx"


@pytest.fixture(scope="session")
def preview():
    return parse_workbook(WORKBOOK)


@pytest.fixture
def matrix(db, preview):
    seed_iso(db)
    publish(db, preview, None, {}, organization_id="futran")
    return db
