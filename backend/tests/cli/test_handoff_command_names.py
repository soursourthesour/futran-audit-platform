"""The 20 Nov hand-off README (with the AWS team) names `python -m app.cli repair-text` and `rematch-updates`. build/v1's
tools are scripts/repair_mojibake.py and `rematch-reg-updates`; the README's names run them, with the same safety: a dry
run unless --apply, and --apply on a database other than SQLite only after the operator says a backup exists."""
import io
import sys
import types

from app import cli


def test_rematch_updates_is_the_rematch_reg_updates_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_rematch_reg_updates", lambda args: seen.__setitem__("apply", args.apply) or 0)
    assert cli.main(["rematch-updates"]) == 0 and seen == {"apply": False}  # a dry run, as rematch-reg-updates
    seen.clear()
    assert cli.main(["rematch-updates", "--apply"]) == 0 and seen == {"apply": True}


def _settings(url: str):
    return types.SimpleNamespace(database_url=url)


def test_repair_text_runs_the_repair_script_on_the_configured_database(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "get_settings", lambda: _settings("sqlite:///./data/app.db"))
    monkeypatch.setattr(cli, "_repair_script_main", lambda argv: calls.append(argv) or 0)
    assert cli.main(["repair-text"]) == 0
    assert cli.main(["repair-text", "--apply"]) == 0
    assert calls == [["sqlite:///./data/app.db"], ["sqlite:///./data/app.db", "--apply"]]


def test_repair_text_apply_on_postgresql_needs_a_backup_first(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "get_settings", lambda: _settings("postgresql+psycopg://u@db/fap"))
    monkeypatch.setattr(cli, "_repair_script_main", lambda argv: calls.append(argv) or 0)
    assert cli.main(["repair-text", "--apply"]) == 2
    assert "Back it up yourself" in capsys.readouterr().err and calls == []
    assert cli.main(["repair-text", "--apply", "--i-have-a-backup"]) == 0
    assert calls == [["postgresql+psycopg://u@db/fap", "--apply"]]
    assert cli.main(["repair-text"]) == 0  # a dry run changes nothing, so it needs no backup


def test_output_survives_a_windows_console_encoding(monkeypatch):
    """A redirected Windows console is cp1252: printing '→' or '₹' must not stop a command (hand-off fix round 2, N-2)."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings("sqlite:///x.db"))
    monkeypatch.setattr(cli, "_repair_script_main", lambda argv: print("Admin. Code § 20-870 → ₹ 1,000") or 0)
    assert cli.main(["repair-text"]) == 0
    out.flush()
    assert "\\u20b9" in out.buffer.getvalue().decode("cp1252")



def test_repair_text_dry_run_on_a_real_database(tmp_path, capsys):
    """The script is loaded from backend/scripts and run, not only called through a stand-in."""
    from sqlalchemy import create_engine

    import app.models_registry  # noqa: F401
    from app.core.models import Base

    url = f"sqlite:///{tmp_path / 'app.db'}"
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    eng.dispose()
    assert cli._repair_script_main([url]) == 0


def test_the_image_keeps_what_repair_text_loads():
    """Review of the bloat trim: repair-text loads backend/scripts/repair_mojibake.py, so the Docker image must keep it."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    ignored = {line.strip().rstrip("/") for line in (root / ".dockerignore").read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}
    assert "backend/scripts" not in ignored
    assert (root / "backend" / "scripts" / "repair_mojibake.py").exists()


def test_repair_text_without_the_script_says_so(monkeypatch, capsys):
    from pathlib import Path

    from app import cli

    monkeypatch.setattr(cli, "_repair_script_path", lambda: Path("/nonexistent/repair_mojibake.py"))
    assert cli._repair_script_main(["sqlite:///x.db"]) == 2
    assert "repair script is not in this installation" in capsys.readouterr().err
