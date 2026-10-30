"""Append-only tables beyond the audit and admin logs: ORM guards plus database triggers, the same way
app.audit_log.models protects the audit log. A demo or e2e reset replaces the database file; nothing deletes rows."""
from sqlalchemy import DDL, event
from sqlalchemy.orm import Session

_GUARDED: dict[str, str] = {}  # table name -> message


def sqlite_triggers(table: str, label: str) -> list[str]:
    return [
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{label} is append-only'); END",
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{label} is append-only'); END",
    ]


def postgres_triggers(table: str, label: str) -> list[str]:
    return [
        f"CREATE OR REPLACE FUNCTION {table}_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION '{label} is append-only'; END; $$ LANGUAGE plpgsql",
        f"DROP TRIGGER IF EXISTS {table}_no_change ON {table}",
        f"CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_append_only()",
    ]


def append_only(model, label: str) -> None:
    """Refuse updates and deletes of `model` rows in the ORM (single rows and bulk statements) and in the database."""
    message = f"The {label} is append-only."
    table = model.__tablename__
    _GUARDED[table] = message

    def _refuse(*_):
        raise PermissionError(message)

    event.listen(model, "before_update", _refuse)
    event.listen(model, "before_delete", _refuse)
    for sql in sqlite_triggers(table, label):
        event.listen(model.__table__, "after_create", DDL(sql).execute_if(dialect="sqlite"))
    for sql in postgres_triggers(table, label):
        event.listen(model.__table__, "after_create", DDL(sql).execute_if(dialect="postgresql"))


@event.listens_for(Session, "do_orm_execute")
def _no_bulk_changes(state):
    if state.is_update or state.is_delete:
        table = getattr(getattr(state.statement, "table", None), "name", None)
        if table in _GUARDED:
            raise PermissionError(_GUARDED[table])
