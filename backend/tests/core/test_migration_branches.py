"""The 20 Nov hand-off build (shipped to the AWS team) added 9a1f3c5e7b20 and b7d2e4f6a8c1 after 717087b4a6c3; build/v1
went on from 717087b4a6c3 to its own head. A database at either head, or at 717087b4a6c3, must upgrade to one head, and
no column change on either branch may narrow a column the other branch widened."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]
VERSIONS = BACKEND / "migrations" / "versions"


def _script() -> ScriptDirectory:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return ScriptDirectory.from_config(cfg)


def _load(rev: str):
    path = next(VERSIONS.glob(f"{rev}_*.py"))
    spec = importlib.util.spec_from_file_location(f"mig_{rev}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_one_head_that_joins_the_hand_off_branch_and_the_main_line():
    s = _script()
    assert len(s.get_heads()) == 1
    head = s.get_revision(s.get_heads()[0])
    assert set(head.down_revision) == {"d6267bab780e", "b7d2e4f6a8c1"}
    assert s.get_revision("b7d2e4f6a8c1").down_revision == "9a1f3c5e7b20"
    assert s.get_revision("9a1f3c5e7b20").down_revision == "717087b4a6c3"


def test_widening_is_skipped_for_a_column_that_is_already_wide_enough():
    eng = sa.create_engine("sqlite://")
    with eng.begin() as c:
        c.exec_driver_sql("create table t (a varchar(12), b varchar(500), c text, d varchar)")
        mod = _load("b7d2e4f6a8c1")
        types = {col: mod.live_type(c, "t", col) for col in "abcd"}
    assert mod.wide_enough(types["a"], 20) is False
    assert mod.wide_enough(types["b"], 20) is True
    assert mod.wide_enough(types["c"], 20) is True  # TEXT: never turned back into a varchar
    assert mod.wide_enough(types["d"], 20) is True
    assert _load("9a1f3c5e7b20").wide_enough(types["c"], 500) is True


def test_the_hand_off_widening_never_runs_on_sqlite(monkeypatch):
    eng = sa.create_engine("sqlite://")
    with eng.begin() as c:
        for rev in ("9a1f3c5e7b20", "b7d2e4f6a8c1"):
            mod = _load(rev)
            monkeypatch.setattr(mod.op, "get_bind", lambda: c, raising=False)
            monkeypatch.setattr(mod.op, "alter_column", lambda *a, **k: (_ for _ in ()).throw(AssertionError("altered on SQLite")), raising=False)
            mod.upgrade()


def test_law_text_retyping_leaves_a_text_column_alone(monkeypatch):
    """66e4fe67c5ba after 9a1f3c5e7b20 or on a re-run: an effective_text that is already TEXT is not rebuilt."""
    eng = sa.create_engine("sqlite://")
    with eng.begin() as c:
        c.exec_driver_sql("create table law_versions (id integer primary key, effective_text text)")
        mod = _load("66e4fe67c5ba")
        monkeypatch.setattr(mod.op, "get_bind", lambda: c, raising=False)
        monkeypatch.setattr(mod.op, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("retyped again")), raising=False)
        mod.upgrade()
