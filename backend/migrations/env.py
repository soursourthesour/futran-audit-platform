import importlib

from alembic import context
from sqlalchemy import event

from app.core.config import get_settings
from app.core.db import make_engine
from app.core.models import Base

importlib.import_module("app.models_registry")
target_metadata = Base.metadata


def _atomic_sqlite(engine) -> None:
    """SQLAlchemy's pysqlite recipe (docs: dialects/sqlite, "Serializable isolation / Savepoints / Transactional DDL").

    The sqlite3 driver only opens a transaction before INSERT/UPDATE/DELETE, so CREATE TABLE, ALTER and the batch
    table copies used to run outside it and stayed behind when a later step failed: the laptop database was left
    half-upgraded. With the driver's own handling off and an explicit BEGIN, each migration (DDL and data moves) is
    one transaction that rolls back fully on failure, and alembic_version still names the last migration that
    succeeded. Migrations only: the
    app's engine (app.core.db) keeps the driver's default behaviour."""

    @event.listens_for(engine, "connect")
    def _no_driver_transactions(dbapi_conn, _):
        dbapi_conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")


def run_migrations_online() -> None:
    url = context.config.attributes.get("database_url") or get_settings().database_url
    engine = make_engine(url)
    if url.startswith("sqlite"):
        _atomic_sqlite(engine)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=url.startswith("sqlite"),
            compare_type=True,
            # with _atomic_sqlite, DDL is transactional on SQLite too: each migration commits on its own or not at all
            transactional_ddl=True if url.startswith("sqlite") else None,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
