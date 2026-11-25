"""Repair text garbled by BUG-04 (UTF-8 seed and template files read as cp1252 on Windows).

Garbled text looks like 'â€”' for '—', 'Â§' for '§' and 'Ã©' for 'é'. Only those sequences are reversed: each run
of characters that is the cp1252 (or latin-1) reading of one UTF-8 character is turned back into that character.
Text that is already correct, such as 'résumé', is left alone, and a value is changed only when the result has fewer
garbled sequences than before.

Run the fixed platform code only after this repair. Otherwise `seed-reference` cannot match the 8 garbled NYC Local
Law 144 control codes ('Admin. Code Â§ 20-870') and adds them a second time.

Usage (from backend/):
    python scripts/repair_mojibake.py <database path or URL>                 # dry run: counts and samples, no change
    python scripts/repair_mojibake.py <database path or URL> --apply         # write, in one transaction
    python scripts/repair_mojibake.py <database path or URL> --apply --include-signed

Reports that are released, final or signed (a declaration or a signature recorded) are skipped unless
--include-signed is given, because their text is what was signed. So are package documents the client has signed.
The outbox and the audit log are never changed. --apply adds one audit log entry describing the repair and, for a
SQLite file, first writes a backup copy next to it (--no-backup to skip).
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import MetaData, Table, create_engine, inspect, select  # noqa: E402
from sqlalchemy.engine import Connection, Engine  # noqa: E402

warnings.filterwarnings("ignore", message="Skipped unsupported reflection")  # expression indexes; not needed here

# ---- detecting and reversing garbled sequences


def _byte(ch: str) -> int | None:
    """The single byte cp1252 (or, for its five gaps, latin-1) would have decoded to this character."""
    o = ord(ch)
    if o < 0x100:
        return o
    try:
        b = ch.encode("cp1252")
    except UnicodeEncodeError:
        return None
    return b[0] if len(b) == 1 else None


_CONT = "".join(sorted({c for c in map(chr, range(0x80, 0xC0))} | {bytes([b]).decode("cp1252") for b in range(0x80, 0xA0) if b not in (0x81, 0x8D, 0x8F, 0x90, 0x9D)}))
_C = "[" + re.escape(_CONT) + "]"
# one UTF-8 character read as cp1252: a lead character followed by the right number of continuation characters
SUSPECT = re.compile(f"[Â-ß]{_C}|[à-ï]{_C}{{2}}|[ð-ô]{_C}{{3}}")


def suspect_count(s: str) -> int:
    return len(SUSPECT.findall(s)) if s else 0


def _fix_one(m: re.Match) -> str:
    raw = bytes(_byte(c) for c in m.group(0))
    try:
        out = raw.decode("utf-8")
    except UnicodeDecodeError:
        return m.group(0)
    return out if _plausible(out) else m.group(0)


# Characters the platform's text actually uses. A decoded character outside these is a false match on correct text,
# for example "NESTLÉ’s" (É then ’) would otherwise become "NESTLɒs" (review 11-25 #1).
PLAUSIBLE = ((0x00A0, 0x017F), (0x2010, 0x2044), (0x20AC, 0x20AC), (0x2122, 0x2122), (0x2190, 0x21FF))


def _plausible(ch: str) -> bool:
    return len(ch) == 1 and any(lo <= ord(ch) <= hi for lo, hi in PLAUSIBLE)


def repair_text(s: str) -> str:
    """Reverse garbled sequences, up to three passes for text garbled more than once. Each pass accepts only plausible
    characters, so a later pass cannot re-read text an earlier pass repaired correctly (review 11-25 #2)."""
    if not s or not SUSPECT.search(s):
        return s
    cur = s
    for _ in range(3):
        nxt = SUSPECT.sub(_fix_one, cur)
        if nxt == cur:
            break
        cur = nxt
    return cur if suspect_count(cur) < suspect_count(s) else s


def repair_json(value):
    """Repair every string inside a JSON value; keys and structure are kept."""
    if isinstance(value, str):
        return repair_text(value)
    if isinstance(value, list):
        return [repair_json(v) for v in value]
    if isinstance(value, dict):
        return {k: repair_json(v) for k, v in value.items()}
    return value


def _json_suspects(value) -> int:
    if isinstance(value, str):
        return suspect_count(value)
    if isinstance(value, list):
        return sum(_json_suspects(v) for v in value)
    if isinstance(value, dict):
        return sum(_json_suspects(v) for v in value.values())
    return 0


# ---- what is repaired

# (table, column, kind). The outbox (emails as sent) and the audit log (append-only) are deliberately absent.
TARGETS: list[tuple[str, str, str]] = [
    ("framework_controls", "code", "text"),
    ("framework_controls", "title", "text"),
    ("questions", "section_title", "text"),
    ("questions", "section_note", "text"),
    ("questions", "label", "text"),
    ("questions", "help_text", "text"),
    ("questions", "options", "json"),
    ("checklist_items", "text", "text"),
    ("client_requirements", "free_text", "text"),
    ("document_templates", "body", "text"),
    ("package_documents", "body_md", "text"),
    ("reports", "body_md", "text"),
]
NEVER = {"outbox_messages", "audit_log"}
SIGNED_REPORT_STATUSES = ("released", "signed", "final")


@dataclass
class ColumnPlan:
    table: str
    column: str
    changes: list[tuple[str, object, object]] = field(default_factory=list)  # (row id, before, after)
    sequences: int = 0
    skipped_signed: int = 0
    conflicts: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.table}.{self.column}"


def _signed_ids(conn: Connection, meta: MetaData, table: str) -> set[str]:
    """Rows whose text is what someone signed: kept unless --include-signed."""
    names = set(inspect(conn).get_table_names())
    if table == "reports":
        r = Table("reports", meta, autoload_with=conn)
        cond = r.c.status.in_(SIGNED_REPORT_STATUSES)
        if "signed_at" in r.c:
            cond = cond | r.c.signed_at.is_not(None)
        ids = set(conn.scalars(select(r.c.id).where(cond)))
        if "declarations" in names:
            d = Table("declarations", meta, autoload_with=conn)
            ids |= set(conn.scalars(select(d.c.report_id)))
        return ids
    if table == "package_documents":
        p = Table("package_documents", meta, autoload_with=conn)
        if "requires_action" in p.c and "completed_at" in p.c:
            return set(conn.scalars(select(p.c.id).where(p.c.requires_action == "sign", p.c.completed_at.is_not(None))))
    return set()


def plan(conn: Connection, include_signed: bool = False) -> list[ColumnPlan]:
    meta = MetaData()
    names = set(inspect(conn).get_table_names())
    out = []
    for table, column, kind in TARGETS:
        assert table not in NEVER
        if table not in names:
            continue
        t = Table(table, meta, autoload_with=conn)
        if column not in t.c:
            continue
        cp = ColumnPlan(table, column)
        signed = set() if include_signed else _signed_ids(conn, meta, table)
        for row_id, value in conn.execute(select(t.c.id, t.c[column])):
            if value is None:
                continue
            if kind == "json":
                n = _json_suspects(value)
                new = repair_json(value) if n else value
                left = _json_suspects(new)
            else:
                n = suspect_count(value)
                new = repair_text(value) if n else value
                left = suspect_count(new)
            if new == value:
                continue
            if row_id in signed:
                cp.skipped_signed += 1
                continue
            cp.changes.append((row_id, value, new))
            cp.sequences += n - left
        if table == "framework_controls" and column == "code" and cp.changes:
            cp.changes = _without_code_conflicts(conn, t, cp)
        out.append(cp)
    return out


def _without_code_conflicts(conn: Connection, t: Table, cp: ColumnPlan) -> list:
    """A control whose repaired code already exists in the same framework (the fixed code was seeded first) is reported,
    not changed: the unique (framework_id, code) would refuse it, and merging the two rows is the owner's decision."""
    fw_of = {r[0]: r[1] for r in conn.execute(select(t.c.id, t.c.framework_id))}
    existing = {(fw, code) for fw, code in conn.execute(select(t.c.framework_id, t.c.code))}
    keep = []
    for row_id, before, after in cp.changes:
        if (fw_of[row_id], after) in existing:
            cp.conflicts.append(f"{before!r} -> {after!r}: a control with the repaired code already exists")
        else:
            keep.append((row_id, before, after))
    return keep


def apply(conn: Connection, plans: list[ColumnPlan], include_signed: bool) -> dict[str, int]:
    meta = MetaData()
    counts = {}
    for cp in plans:
        if not cp.changes:
            continue
        t = Table(cp.table, meta, autoload_with=conn)
        for row_id, _, new in cp.changes:
            conn.execute(t.update().where(t.c.id == row_id).values({cp.column: new}))
        counts[cp.key] = len(cp.changes)
    if counts:
        _audit(conn, counts, plans, include_signed)
    return counts


def _audit(conn: Connection, counts: dict[str, int], plans: list[ColumnPlan], include_signed: bool) -> None:
    import uuid

    org = Table("organizations", MetaData(), autoload_with=conn)
    org_id = conn.scalar(select(org.c.id).where(org.c.type == "futran", org.c.is_internal.is_(False)).limit(1)) \
        or conn.scalar(select(org.c.id).where(org.c.type == "futran").limit(1))
    if org_id is None:
        raise SystemExit("No Futran organization found for the audit log entry; nothing was written.")
    total = sum(counts.values())
    log = Table("audit_log", MetaData(), autoload_with=conn)
    conn.execute(log.insert().values(
        id=str(uuid.uuid4()), organization_id=org_id, actor_id=None, actor_name="Data repair script", action="data.mojibake_repaired",
        object_type="Database", object_id=None, engagement_id=None,
        summary=f"Repaired garbled characters (BUG-04) in {total} stored values across {len(counts)} columns",
        before=None,
        after={"columns": counts, "skipped_signed": {cp.key: cp.skipped_signed for cp in plans if cp.skipped_signed},
               "include_signed": include_signed, "conflicts": {cp.key: cp.conflicts for cp in plans if cp.conflicts}},
        at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))


def uncovered(conn: Connection) -> dict[str, int]:
    """Other text columns that still hold garbled sequences, shown for information only."""
    covered = {(t, c) for t, c, _ in TARGETS}
    found = {}
    meta = MetaData()
    for table in inspect(conn).get_table_names():
        if table in NEVER or table == "alembic_version":
            continue
        t = Table(table, meta, autoload_with=conn)
        cols = [c for c in t.c if (table, c.name) not in covered and _has_type(c) and c.type.python_type in (str, dict, list)]
        if not cols:
            continue
        for row in conn.execute(select(*cols)):
            for c, v in zip(cols, row):
                if v is not None and (_json_suspects(v) if not isinstance(v, str) else suspect_count(v)):
                    found[f"{table}.{c.name}"] = found.get(f"{table}.{c.name}", 0) + 1
    return found


def _has_type(c) -> bool:
    try:
        c.type.python_type
        return True
    except NotImplementedError:
        return False


# ---- command line


def engine_for(target: str) -> Engine:
    url = target if "://" in target else "sqlite:///" + Path(target).resolve().as_posix()
    if url.startswith("sqlite:///") and not Path(url.removeprefix("sqlite:///")).exists():
        raise SystemExit(f"No database at {url.removeprefix('sqlite:///')}.")
    return create_engine(url)


def _backup(engine: Engine) -> Path | None:
    if engine.url.get_backend_name() != "sqlite" or not engine.url.database:
        return None
    src = Path(engine.url.database)
    dest = src.with_name(f"{src.name}.before-mojibake-repair-{datetime.now():%Y%m%d-%H%M%S}")
    with sqlite3.connect(src) as a, sqlite3.connect(dest) as b:
        a.backup(b)
    return dest


def _sample(before: object, after: object, width: int = 70) -> tuple[str, str]:
    if not isinstance(before, str):
        import json

        before, after = json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)
    m = SUSPECT.search(before)
    start = max(0, (m.start() if m else 0) - 25)
    b = before[start:start + width]
    a = after[start:start + width]  # repairs shorten the text, so the window is close, not exact
    return b.replace("\n", " "), a.replace("\n", " ")


def report(plans: list[ColumnPlan], applied: bool, samples: int = 3) -> int:
    total = 0
    print("Applied:" if applied else "Dry run (nothing written):")
    print(f"  {'table.column':38} {'values':>7} {'sequences':>10} {'skipped (signed)':>17}")
    for cp in plans:
        if not (cp.changes or cp.skipped_signed or cp.conflicts):
            continue
        total += len(cp.changes)
        print(f"  {cp.key:38} {len(cp.changes):>7} {cp.sequences:>10} {cp.skipped_signed:>17}")
        for c in cp.conflicts:
            print(f"      not changed: {c}")
    print(f"  {'total':38} {total:>7}")
    if not applied:
        for cp in plans:
            for _, before, after in cp.changes[:samples]:
                b, a = _sample(before, after)
                print(f"\n  {cp.key}\n    before: {b}\n    after:  {a}")
    return total


def write_changes(plans: list["ColumnPlan"], dest: Path) -> int:
    """Every before/after pair, in full, so the owner can read all of them before applying (review 11-25 #1)."""
    import json

    n = 0
    with dest.open("w", encoding="utf-8") as f:
        for cp in plans:
            for key, before, after in cp.changes:
                b = before if isinstance(before, str) else json.dumps(before, ensure_ascii=False)
                a = after if isinstance(after, str) else json.dumps(after, ensure_ascii=False)
                f.write(f"== {cp.key} [{key}]\n--- before\n{b}\n--- after\n{a}\n\n")
                n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Repair text garbled by BUG-04. Dry run unless --apply.")
    ap.add_argument("database", help="SQLite file path or SQLAlchemy database URL")
    ap.add_argument("--apply", action="store_true", help="write the repairs, in one transaction")
    ap.add_argument("--include-signed", action="store_true", help="also repair released, final and signed reports and signed package documents")
    ap.add_argument("--no-backup", action="store_true", help="with --apply on a SQLite file, do not write a backup copy first")
    ap.add_argument("--samples", type=int, default=3, help="before/after samples per column printed on screen in a dry run")
    ap.add_argument("--changes-file", help="dry run: write every before/after pair to this file (default: next to a SQLite database)")
    args = ap.parse_args(argv)
    print("Stop the Futran Audit Platform before --apply: a backup taken while it is writing loses those writes on restore.")

    engine = engine_for(args.database)
    if not args.apply:
        with engine.connect() as conn:
            plans = plan(conn, args.include_signed)
            report(plans, applied=False, samples=args.samples)
            other = uncovered(conn)
        dest = Path(args.changes_file) if args.changes_file else (
            Path(engine.url.database).with_name("mojibake-repair-changes.txt") if engine.url.get_backend_name() == "sqlite" and engine.url.database else None)
        if dest is not None:
            write_changes(plans, dest)
            print(f"\nEvery change is listed in {dest}. Read it before running with --apply.")
        if other:
            print("\nOther columns with garbled text, not changed by this script:")
            for k, n in sorted(other.items()):
                print(f"  {k}: {n}")
        return 0

    if not args.no_backup and (dest := _backup(engine)):
        print(f"Backup written to {dest}")
    elif not args.no_backup:
        print("No backup was written: this is not a SQLite file. Take a database backup (for example pg_dump) before applying.")
    with engine.begin() as conn:  # one transaction: all repairs and the audit entry, or nothing
        plans = plan(conn, args.include_signed)
        apply(conn, plans, args.include_signed)
    report(plans, applied=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
