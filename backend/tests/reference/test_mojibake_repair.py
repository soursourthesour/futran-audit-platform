"""BUG-04 data repair: scripts/repair_mojibake.py, and the order of repair and seed-reference."""
import importlib.util
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("repair_mojibake", BACKEND / "scripts" / "repair_mojibake.py")
rm = importlib.util.module_from_spec(_spec)
sys.modules["repair_mojibake"] = rm
_spec.loader.exec_module(rm)


def garble(s: str) -> str:
    """What Windows did: UTF-8 bytes read as cp1252."""
    return "".join(bytes([b]).decode("cp1252", errors="ignore") or chr(b) for b in s.encode("utf-8"))


LL144 = [c["code"] for f in yaml.safe_load((BACKEND / "seeds" / "frameworks.yaml").read_text(encoding="utf-8"))["frameworks"] if f["code"] == "NYC_LL144" for c in f["controls"]]


@pytest.mark.parametrize("good", [
    "Overall maturity (1–5)", "Admin. Code § 20-870", "Govern — culture", "it’s “quoted”", "Ação · café", "a b", "€ 1,000", "→ next",
])
def test_repair_reverses_garbled_text(good):
    assert garble(good) != good
    assert rm.repair_text(garble(good)) == good


@pytest.mark.parametrize("text", ["résumé", "café au lait", "São Paulo", "naïve", "plain ascii", "", "Straße", "§ 5 — ok"])
def test_repair_leaves_correct_text_alone(text):
    assert rm.repair_text(text) == text


def test_repair_handles_mixed_and_double_garbled_text():
    assert rm.repair_text("résumé " + garble("— café")) == "résumé — café"
    assert rm.repair_text(garble(garble("1–5"))) == "1–5"
    assert rm.repair_json([{"value": "1", "label": garble("1 — negligible")}]) == [{"value": "1", "label": "1 — negligible"}]


# ---- against a database


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    """Frameworks, templates and the question bank, loaded once by the fixed code."""
    path = tmp_path_factory.mktemp("seeded") / "app.db"
    eng = create_engine(f"sqlite:///{path}")
    from app.core.models import Base
    import app.models_registry  # noqa: F401
    from app.cli import _futran_org
    from app.reference import LOADERS

    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    org_id = _futran_org(db).id
    for name, fn in LOADERS:
        if name in ("Frameworks", "Document templates", "Question bank"):
            fn(db)
    db.commit()
    db.close()
    eng.dispose()
    return path, org_id


@pytest.fixture
def dbfile(seeded, tmp_path):
    """A copy whose stored text was garbled as on the laptop."""
    src, org_id = seeded
    path = tmp_path / "app.db"
    shutil.copy(src, path)
    con = sqlite3.connect(path)
    con.create_function("garble", 1, lambda s: garble(s) if s is not None else None)
    con.execute("update framework_controls set code = garble(code), title = garble(title)")
    con.execute("update questions set label = garble(label), help_text = garble(help_text), section_note = garble(section_note)")
    con.execute("update document_templates set body = garble(body)")
    now = datetime(2026, 11, 1).isoformat(" ")
    for rid, status, signed in (("r-draft", "draft", None), ("r-released", "released", None), ("r-final", "final", now), ("r-declared", "draft", None)):
        con.execute("insert into reports (id, organization_id, engagement_id, version, type, status, body_md, content_hash, signed_at, created_at, updated_at) "
                    "values (?, ?, 'e1', 'v0.1', 'audit_report', ?, ?, 'h', ?, ?, ?)", (rid, org_id, status, garble("Overall maturity (1–5)"), signed, now, now))
    con.execute("insert into declarations (id, organization_id, engagement_id, report_id, kind, user_id, typed_name, text, signed_at, document_sha256, disputed_finding_refs, created_at, updated_at) "
                "values ('d1', ?, 'e1', 'r-declared', 'lead_auditor', 'u1', 'A', 't', ?, 'x', '[]', ?, ?)", (org_id, now, now, now))
    con.execute("insert into outbox_messages (id, organization_id, \"to\", subject, body_html, body_text, template_key, status, created_at, updated_at) "
                "values ('o1', ?, '[]', 's', ?, ?, 'k', 'sent', ?, ?)", (org_id, garble("a — b"), garble("a — b"), now, now))
    con.execute("insert into audit_log (id, organization_id, action, object_type, summary, at) values ('a1', ?, 'x', 'X', ?, ?)", (org_id, garble("a — b"), now))
    con.commit()
    con.close()
    return path


def _session(path):
    return sessionmaker(bind=create_engine(f"sqlite:///{path}"))()


def _ll144_codes(db):
    from app.reference.models import Framework, FrameworkControl

    return sorted(db.scalars(select(FrameworkControl.code).join(Framework, Framework.id == FrameworkControl.framework_id).where(Framework.code == "NYC_LL144")))


def _plans(path, include_signed=False):
    with create_engine(f"sqlite:///{path}").connect() as conn:
        return {p.key: p for p in rm.plan(conn, include_signed)}


def test_repair_before_seed_reference_keeps_one_row_per_control(dbfile):
    """The required order: repair first, then the fixed seed-reference finds every control and adds none."""
    from app.reference.frameworks import load_frameworks

    db = _session(dbfile)
    assert _ll144_codes(db) == sorted(garble(c) for c in LL144)
    db.close()
    rm.main([str(dbfile), "--apply", "--no-backup"])
    db = _session(dbfile)
    assert _ll144_codes(db) == sorted(LL144)
    assert load_frameworks(db) == "0 controls added"
    assert _ll144_codes(db) == sorted(LL144)


def test_seed_reference_before_repair_adds_no_duplicates(dbfile):
    """The wrong order: the fixed loader still recognises a garbled code as the same control, so the repair can follow."""
    from app.reference.frameworks import load_frameworks

    db = _session(dbfile)
    assert load_frameworks(db) == "0 controls added"
    db.commit()
    db.close()
    rm.main([str(dbfile), "--apply", "--no-backup"])
    assert _ll144_codes(_session(dbfile)) == sorted(LL144)


def test_code_already_present_in_both_forms_is_reported_not_changed(dbfile):
    con = sqlite3.connect(dbfile)
    fw, title = con.execute("select framework_id, title from framework_controls where code = ?", (garble(LL144[0]),)).fetchone()
    con.execute("insert into framework_controls (id, framework_id, code, title) values ('dup', ?, ?, ?)", (fw, LL144[0], title))
    con.commit()
    con.close()
    p = _plans(dbfile)["framework_controls.code"]
    assert len(p.conflicts) == 1 and len(p.changes) == 7
    rm.main([str(dbfile), "--apply", "--no-backup"])  # no unique-constraint failure
    assert _plans(dbfile)["framework_controls.code"].conflicts


def test_dry_run_apply_and_rerun(dbfile, capsys):
    before = dbfile.read_bytes()
    rm.main([str(dbfile)])
    assert dbfile.read_bytes() == before, "a dry run writes nothing"
    assert "Dry run" in capsys.readouterr().out

    plans = _plans(dbfile)
    assert len(plans["framework_controls.code"].changes) == 8
    assert plans["reports.body_md"].skipped_signed == 3 and len(plans["reports.body_md"].changes) == 1

    rm.main([str(dbfile), "--apply", "--no-backup"])
    assert sum(len(p.changes) for p in _plans(dbfile).values()) == 0, "a re-run finds nothing more"

    con = sqlite3.connect(dbfile)
    assert con.execute("select body_md from reports where id = 'r-draft'").fetchone()[0] == "Overall maturity (1–5)"
    for rid in ("r-released", "r-final", "r-declared"):
        assert con.execute("select body_md from reports where id = ?", (rid,)).fetchone()[0] == garble("Overall maturity (1–5)")
    assert con.execute("select body_html, body_text from outbox_messages").fetchone() == (garble("a — b"), garble("a — b"))
    assert con.execute("select summary from audit_log where id = 'a1'").fetchone()[0] == garble("a — b")
    entries = con.execute("select actor_name, summary from audit_log where action = 'data.mojibake_repaired'").fetchall()
    assert len(entries) == 1 and entries[0][0] == "Data repair script"
    from app.reference.templates import TEMPLATE_DIR

    body = con.execute("select body from document_templates where key = 'report'").fetchone()[0]
    assert body == (TEMPLATE_DIR / "report.md.j2").read_text(encoding="utf-8"), "the repaired template is the shipped file"

    rm.main([str(dbfile), "--apply", "--no-backup", "--include-signed"])
    assert con.execute("select count(*) from reports where body_md = 'Overall maturity (1–5)'").fetchone()[0] == 4
    assert con.execute("select count(*) from audit_log where action = 'data.mojibake_repaired'").fetchone()[0] == 2


def test_apply_on_a_sqlite_file_writes_a_backup_first(dbfile):
    rm.main([str(dbfile), "--apply"])
    backups = list(dbfile.parent.glob("app.db.before-mojibake-repair-*"))
    assert len(backups) == 1
    con = sqlite3.connect(backups[0])
    assert con.execute("select count(*) from framework_controls where code like '%Â§%'").fetchone()[0] == 8
