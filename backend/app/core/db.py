from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url.startswith("sqlite:///./") or database_url.startswith("sqlite:///"):
            import os

            path = database_url.replace("sqlite:///", "", 1)
            if path and path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    engine = create_engine(database_url, future=True, **kwargs)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            dbapi_conn.execute("PRAGMA journal_mode=WAL")

    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def get_db(request: Request) -> Iterator[Session]:
    SessionLocal: sessionmaker = request.app.state.sessionmaker
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def hold_transaction(db: Session) -> None:
    """Make sure the request's own transaction is open before `begin_nested()`.

    The sqlite3 driver only opens a transaction before INSERT/UPDATE/DELETE. A SAVEPOINT issued while none is open
    becomes the outermost transaction, and releasing it commits: the work inside could no longer be undone when a
    later step of the same request failed. This starts the transaction first (BEGIN IMMEDIATE: the request is about
    to write, and taking the write lock now avoids a stale read snapshot under WAL). No-op on other databases or when
    a transaction is already open. The app engine otherwise keeps the driver's default behaviour."""
    conn = db.connection()
    if conn.dialect.name != "sqlite":
        return
    raw = conn.connection.dbapi_connection
    if raw is not None and not raw.in_transaction:
        raw.execute("BEGIN IMMEDIATE")
