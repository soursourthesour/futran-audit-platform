"""A migration that fails partway leaves the laptop database exactly as it was: the tables it created and the rows it
moved are rolled back, and alembic_version still names the last revision that succeeded (migrations/env.py)."""
import shutil
import sqlite3
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]

REV_A = '''"""first"""
from alembic import op
import sqlalchemy as sa

revision = "aaaa00000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("t_keep", sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String(20)))
    op.execute("insert into t_keep (id, name) values (1, 'before')")


def downgrade():
    pass
'''

REV_B = '''"""second, fails after some work"""
from alembic import op
import sqlalchemy as sa

revision = "bbbb00000002"
down_revision = "aaaa00000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("t_new", sa.Column("id", sa.Integer, primary_key=True))
    with op.batch_alter_table("t_keep") as b:
        b.add_column(sa.Column("extra", sa.String(20), nullable=True))
    op.execute("update t_keep set name = 'after'")
    raise RuntimeError("the data move failed")


def downgrade():
    pass
'''


@pytest.fixture
def scripts(tmp_path):
    root = tmp_path / "migrations"
    (root / "versions").mkdir(parents=True)
    shutil.copy(BACKEND / "migrations" / "env.py", root / "env.py")
    shutil.copy(BACKEND / "migrations" / "script.py.mako", root / "script.py.mako")
    (root / "versions" / "aaaa00000001_first.py").write_text(REV_A)
    (root / "versions" / "bbbb00000002_second.py").write_text(REV_B)
    return root


def _upgrade(scripts: Path, url: str, rev: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(scripts))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, rev)


def test_failed_migration_leaves_the_database_unchanged(scripts, tmp_path):
    path = tmp_path / "laptop.db"
    url = f"sqlite:///{path}"
    _upgrade(scripts, url, "aaaa00000001")
    with pytest.raises(RuntimeError):
        _upgrade(scripts, url, "head")
    c = sqlite3.connect(path)
    tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    assert "t_new" not in tables and not any(t.startswith("_alembic_tmp") for t in tables)
    assert [r[1] for r in c.execute("pragma table_info(t_keep)")] == ["id", "name"]
    assert c.execute("select name from t_keep").fetchall() == [("before",)]
    assert c.execute("select version_num from alembic_version").fetchall() == [("aaaa00000001",)]


def test_each_migration_is_its_own_transaction(scripts, tmp_path):
    """From an empty database: the first migration lands, the failing second leaves nothing behind."""
    path = tmp_path / "fresh.db"
    with pytest.raises(RuntimeError):
        _upgrade(scripts, f"sqlite:///{path}", "head")
    c = sqlite3.connect(path)
    assert {r[0] for r in c.execute("select name from sqlite_master where type='table'")} == {"alembic_version", "t_keep"}
    assert c.execute("select version_num from alembic_version").fetchall() == [("aaaa00000001",)]
    assert c.execute("select name from t_keep").fetchall() == [("before",)]
