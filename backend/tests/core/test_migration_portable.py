"""Migrations run on SQLite (the laptop) and on an empty PostgreSQL database (the hosted install). Raw SQL in a
migration must not set or compare a boolean column with 0 or 1: SQLite accepts it, PostgreSQL refuses
`boolean = integer` and the container would not start (BUG-K07)."""
import importlib.util
import re
from pathlib import Path

import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _boolean_columns() -> set[str]:
    from app.core.models import Base
    import app.models_registry  # noqa: F401

    return {c.name for t in Base.metadata.tables.values() for c in t.columns if isinstance(c.type, sa.Boolean)}


def test_no_migration_compares_a_boolean_column_with_an_integer():
    names = _boolean_columns()
    pattern = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names))) + r")\s*(=|<>|!=)\s*[01]\b")
    found = []
    for f in sorted(VERSIONS.glob("*.py")):
        for no, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and "server_default" not in line:
                found.append(f"{f.name}:{no}")
    assert found == []


def _load(name: str):
    path = next(VERSIONS.glob(f"{name}_*.py"))
    spec = importlib.util.spec_from_file_location(f"mig_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refresh_schedule_correction_gives_the_same_result_on_sqlite(monkeypatch):
    """d5a9c7e3f182 still switches off schedules nobody turned on, and keeps the ones a person saved."""
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text("create table refresh_settings (id integer primary key, schedule_enabled boolean not null, updated_by varchar(36))"))
        conn.execute(sa.text("insert into refresh_settings values (1, 1, null), (2, 1, 'u1'), (3, 0, null), (4, 0, 'u2')"))
        mod = _load("d5a9c7e3f182")
        monkeypatch.setattr(mod.op, "get_bind", lambda: conn, raising=False)
        mod.upgrade()
        rows = conn.execute(sa.text("select id, schedule_enabled from refresh_settings order by id")).fetchall()
    assert [tuple(r) for r in rows] == [(1, 0), (2, 1), (3, 0), (4, 0)]
