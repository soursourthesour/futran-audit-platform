"""The AWS target is PostgreSQL. With FAP_TEST_DATABASE_URL set, the migrations and reference seed run on an empty
PostgreSQL database (they once failed there: a boolean compared with 0, and seeded text longer than its column)."""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

PG_URL = os.environ.get("FAP_TEST_DATABASE_URL")
BACKEND = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not PG_URL, reason="set FAP_TEST_DATABASE_URL to a PostgreSQL database to run")
def test_migrations_and_reference_seed_run_on_an_empty_postgres_database():
    name = f"fap_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(make_url(PG_URL).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.exec_driver_sql(f'create database "{name}"')
    try:
        url = make_url(PG_URL).set(database=name).render_as_string(hide_password=False)
        env = {**os.environ, "DATABASE_URL": url, "SECRET_KEY": "test-secret-key-not-for-production-0123456789"}
        for cmd in ([sys.executable, "-m", "alembic", "upgrade", "head"], [sys.executable, "-m", "app.cli", "seed-reference"]):
            r = subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[-2000:]
    finally:
        with admin.connect() as c:
            c.exec_driver_sql(f'drop database if exists "{name}" with (force)')
        admin.dispose()


@pytest.mark.skipif(not PG_URL, reason="set FAP_TEST_DATABASE_URL to a PostgreSQL database to run")
def test_migrated_varchar_lengths_match_the_models():
    """PostgreSQL enforces varchar lengths (SQLite does not): after `alembic upgrade head`, every String column is at
    least as long as its model says, so a code the model allows is never refused (b7d2e4f6a8c1 widened the short ones)."""
    from sqlalchemy import String, text

    import app.models_registry  # noqa: F401
    from app.core.models import Base

    name = f"fap_len_{uuid.uuid4().hex[:8]}"
    admin = create_engine(make_url(PG_URL).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.exec_driver_sql(f'create database "{name}"')
    try:
        url = make_url(PG_URL).set(database=name)
        env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False), "SECRET_KEY": "test-secret-key-not-for-production-0123456789"}
        r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]
        eng = create_engine(url)
        with eng.connect() as c:
            db_len = {(t, col): n for t, col, n in c.execute(text(
                "select table_name, column_name, character_maximum_length from information_schema.columns "
                "where table_schema = 'public' and data_type = 'character varying'"))}
        eng.dispose()
        short = []
        for table in Base.metadata.sorted_tables:
            for col in table.columns:
                n = getattr(col.type, "length", None)
                if isinstance(col.type, String) and n and db_len.get((table.name, col.name)) is not None and db_len[(table.name, col.name)] < n:
                    short.append(f"{table.name}.{col.name}: database {db_len[(table.name, col.name)]} < model {n}")
        assert short == []
        for t, col, n in (("catalog_changes", "status", 20), ("findings", "origin", 20), ("mail_replies", "kind", 20), ("opportunities", "stage", 20),
                          ("refresh_runs", "source_set", 20), ("refresh_settings", "source_set", 20), ("update_digest_runs", "status", 20)):
            assert db_len[(t, col)] == n, (t, col)
    finally:
        with admin.connect() as c:
            c.exec_driver_sql(f'drop database if exists "{name}" with (force)')
        admin.dispose()
