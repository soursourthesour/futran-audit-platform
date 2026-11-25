"""BUG-04: seed and template files are UTF-8, so every text read and write names its encoding.

Without it, Python uses the computer's locale encoding (cp1252 on Windows), and dashes and section signs come out
as 'â€”' and 'Â§'. Two checks: a static scan of backend/app, and the real reference loaders run under a
non-UTF-8 locale.
"""
import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
ESCAPE = "# noqa: encoding"  # for a call that is not a file open (for example a zip member); say why next to it


def _mode(call: ast.Call, position: int) -> str | None:
    for kw in call.keywords:
        if kw.arg == "mode":
            return kw.value.value if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str) else "?"
    if len(call.args) > position:
        a = call.args[position]
        return a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else "?"
    return None


def _has_encoding(call: ast.Call) -> bool:
    return any(kw.arg == "encoding" for kw in call.keywords) or any(kw.arg is None for kw in call.keywords)  # **kwargs: trust it


def violations(source: str, filename: str = "<string>") -> list[str]:
    """Text-mode file reads and writes with no explicit encoding."""
    lines = source.splitlines()
    out = []
    for node in ast.walk(ast.parse(source, filename)):
        if not isinstance(node, ast.Call) or _has_encoding(node):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
        if name in ("read_text", "write_text"):
            bad = True
        elif name == "open":
            # builtin open(file, mode): mode is the 2nd argument; Path.open(mode) and friends: the 1st
            builtin = isinstance(f, ast.Name) or (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in ("io", "codecs"))
            mode = _mode(node, 1 if builtin else 0)
            bad = mode is None or (mode != "?" and "b" not in mode)
        elif name in ("TextIOWrapper",):
            bad = True
        elif name in ("NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"):
            mode = _mode(node, 0)
            bad = mode is not None and mode != "?" and "b" not in mode
        else:
            continue
        if bad and ESCAPE not in lines[node.lineno - 1]:
            out.append(f"{filename}:{node.lineno}: {ast.unparse(node)[:100]}")
    return out


def test_guard_detects_missing_encoding():
    assert violations("p.read_text()")
    assert violations("p.write_text(s)")
    assert violations("open(f)")
    assert violations("open(f, 'w')")
    assert violations("p.open()")
    assert violations("io.TextIOWrapper(b)")
    assert not violations("p.read_text(encoding='utf-8')")
    assert not violations("p.write_text(s, encoding='utf-8')")
    assert not violations("open(f, 'rb')")
    assert not violations("p.open('wb')")
    assert not violations("open(f, encoding='utf-8')")
    assert not violations("zf.open(name)  # noqa: encoding (zip member, bytes)")
    assert not violations("tempfile.NamedTemporaryFile(suffix='.db')")


def test_every_text_read_and_write_in_app_names_its_encoding():
    found = []
    for path in sorted(APP.rglob("*.py")):
        if "static" in path.relative_to(APP).parts:
            continue
        found += violations(path.read_text(encoding="utf-8"), str(path.relative_to(BACKEND)))
    assert not found, "Add encoding=\"utf-8\" to these text reads/writes:\n" + "\n".join(found)


def test_reference_loaders_read_utf8_under_a_non_utf8_locale(tmp_path):
    """Run the real seed loaders with the locale encoding forced to ASCII (as cp1252 is on Windows, it is not UTF-8)."""
    script = textwrap.dedent("""
        import locale
        assert locale.getpreferredencoding(False).lower().replace("-", "") not in ("utf8",), locale.getpreferredencoding(False)
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import sessionmaker
        from app.core.models import Base
        import app.models_registry
        from app.reference import LOADERS
        from app.reference.models import DocumentTemplate, FrameworkControl
        from app.reports.service import _template_body
        eng = create_engine("sqlite://")
        Base.metadata.create_all(eng)
        db = sessionmaker(bind=eng)()
        from app.cli import _futran_org
        _futran_org(db)
        for _, fn in LOADERS:
            fn(db)
        codes = set(db.scalars(select(FrameworkControl.code)))
        assert "Admin. Code \\u00a7 20-870" in codes, sorted(c for c in codes if "20-870" in c)
        titles = set(db.scalars(select(FrameworkControl.title)))
        assert any("\\u2014" in t for t in titles)
        assert not any("\\u00e2\\u20ac" in t or "\\u00c2" in t for t in titles | codes)
        body = db.scalar(select(DocumentTemplate.body).where(DocumentTemplate.key == "report"))
        assert "\\u00e2\\u20ac" not in body
        db.query(DocumentTemplate).delete()
        fallback, _ = _template_body(db, "report")
        assert fallback == body
        print("ok")
    """)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "LANG", "PYTHONUTF8", "PYTHONIOENCODING"))}
    env.update(LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", PYTHONIOENCODING="utf-8", PYTHONPATH=str(BACKEND))
    r = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stderr[-3000:]
