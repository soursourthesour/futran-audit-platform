"""Publish an import preview as a new matrix version (spec §10.1 import rules 1–5).

Identity: `Regulation.import_key` (see `import_keys`), carried through manual and Claude edits.
- unchanged content  -> same row; `last_seen_version_id` moves to the new version
- changed content    -> new row; the old row gets `superseded_by_id` (never deleted)
- curated and changed in the workbook -> curated row kept, reported as a conflict (Admin can take the workbook text)
- missing from file  -> imported row gets `retired_in_version_id`; curated and manually added rows are never retired
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.laws.importer import ImportPreview, PreviewRow
from app.laws.models import MatrixVersion, Regulation
from app.reference.models import Jurisdiction
from app.tenancy.models import User


def current_regulations(db: Session) -> list[Regulation]:
    return list(db.scalars(select(Regulation).where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None))))


def current_version_of(db: Session, reg_id: str) -> Regulation | None:
    """Follow the superseded_by chain to the newest version of a law."""
    reg = db.get(Regulation, reg_id)
    seen: set[str] = set()
    while reg is not None and reg.superseded_by_id and reg.id not in seen:
        seen.add(reg.id)
        reg = db.get(Regulation, reg.superseded_by_id)
    return reg


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def import_keys(preview: ImportPreview) -> dict[str, str]:
    """Stable workbook identity per regulation row: jurisdiction, feature, workbook short name and occurrence.

    The key uses the workbook's own short name, never an Admin rename, so curated rows still match on re-import.
    Duplicate names in one jurisdiction and feature are told apart by their order in the workbook."""
    counts: dict[str, int] = {}
    out: dict[str, str] = {}
    for row in preview.rows:
        if row.kind != "regulation":
            continue
        base = f"{row.jurisdiction_code}|{row.feature}|{_norm(row.short_name)}"
        n = counts.get(base, 0)
        counts[base] = n + 1
        out[row.row_key] = f"{base}|{n}"[:200]
    return out


CURATED = ("manual", "claude")


def plan_publish(db: Session, preview: ImportPreview, edits: dict[str, str], take_workbook: list[str] | None = None) -> dict:
    """What publishing this preview would do, without changing anything.

    Rows an Admin or Claude has changed since the last import are curated: when the workbook changes the same law,
    the curated version is kept and the row is reported as a conflict unless it is listed in `take_workbook`."""
    take = set(take_workbook or [])
    keys = import_keys(preview)
    existing = {r.import_key: r for r in current_regulations(db) if r.import_key}
    actions: dict[str, tuple[str, Regulation | None]] = {}
    conflicts: list[dict] = []
    seen: set[str] = set()
    counts = {"created": 0, "updated": 0, "unchanged": 0, "retired": 0}
    for row in preview.rows:
        if row.kind != "regulation":
            continue
        prev = existing.get(keys[row.row_key])
        edit = (edits.get(row.row_key) or "").strip()
        if prev is None:
            actions[row.row_key] = ("create", None)
            counts["created"] += 1
            continue
        seen.add(prev.id)
        renamed = bool(edit) and edit != prev.short_name
        if prev.content_hash == row.content_hash() and not renamed:
            actions[row.row_key] = ("unchanged", prev)
            counts["unchanged"] += 1
        elif prev.origin in CURATED and prev.content_hash != row.content_hash() and row.row_key not in take:
            actions[row.row_key] = ("conflict", prev)
            conflicts.append({"row_key": row.row_key, "kind": "changed", "current_id": prev.id, "current_short_name": prev.short_name, "current_origin": prev.origin, "workbook_short_name": row.short_name, "workbook_text": row.full_text})
        else:
            actions[row.row_key] = ("update", prev)
            counts["updated"] += 1
    retire: list[Regulation] = []
    for r in existing.values():
        if r.id in seen:
            continue
        if r.origin in CURATED:
            conflicts.append({"row_key": None, "kind": "removed", "current_id": r.id, "current_short_name": r.short_name, "current_origin": r.origin, "workbook_short_name": None, "workbook_text": None})
        else:
            retire.append(r)
    counts["retired"] = len(retire)
    return {**counts, "conflicts": conflicts, "_actions": actions, "_retire": retire, "_keys": keys}


def plan_out(plan: dict) -> dict:
    return {k: v for k, v in plan.items() if not k.startswith("_")}


def _ensure_jurisdiction(db: Session, row: PreviewRow, cache: dict[str, Jurisdiction]) -> Jurisdiction:
    j = cache.get(row.jurisdiction_code)
    if j is None:
        j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == row.jurisdiction_code))
        if j is None:
            parent = None
            if row.level in ("state", "city") and "-" in row.jurisdiction_code:
                parent_code = "US-NY" if row.jurisdiction_code == "US-NYC" else row.jurisdiction_code.rsplit("-", 1)[0]
                parent = db.scalar(select(Jurisdiction).where(Jurisdiction.code == parent_code))
            j = Jurisdiction(code=row.jurisdiction_code, name=row.jurisdiction_name, level=row.level, parent_id=parent.id if parent else None)
            db.add(j)
            db.flush()
        cache[row.jurisdiction_code] = j
    j.has_laws = True
    return j


def publish(
    db: Session,
    preview: ImportPreview,
    actor: User | None,
    edits: dict[str, str],
    origin: str = "import",
    label: str | None = None,
    organization_id: str | None = None,
    take_workbook: list[str] | None = None,
) -> MatrixVersion:
    actor_id = actor.id if actor else None
    plan = plan_publish(db, preview, edits, take_workbook)
    for old in db.scalars(select(MatrixVersion).where(MatrixVersion.status == "published")):
        old.status = "superseded"
    version = MatrixVersion(
        label=label or f"Law matrix import — status {preview.status_date.isoformat() if preview.status_date else 'undated'}",
        status_date=preview.status_date,
        source_filename=preview.source_filename,
        origin=origin,
        sources=preview.sources,
        warnings=preview.warnings,
        status="published",
        published_by=actor_id,
        published_at=utcnow(),
    )
    db.add(version)
    db.flush()

    cache: dict[str, Jurisdiction] = {}
    for row in preview.rows:
        j = _ensure_jurisdiction(db, row, cache)
        if row.kind != "regulation":
            continue
        action, prev = plan["_actions"][row.row_key]
        if action in ("unchanged", "conflict"):
            prev.last_seen_version_id = version.id
            continue
        short = (edits.get(row.row_key) or row.short_name).strip()
        reg = Regulation(
            jurisdiction_id=j.id,
            matrix_version_id=version.id,
            last_seen_version_id=version.id,
            short_name=short,
            citation=row.full_text[:300] if row.source_sheet != "State Matrix" else None,
            category_text=row.category_text,
            feature=row.feature,
            type=row.type,
            type_text=row.type_text,
            enforcer=row.enforcer,
            trigger_text=row.trigger_text,
            obligations_text=row.obligations_text,
            developments_text=row.developments_text,
            most_affected=row.most_affected,
            full_text=row.full_text,
            applies_to=row.applies_to,
            verify_flag=row.verify_flag,
            public_summary="local law 144" in (row.full_text or "").lower(),
            source_sheet=row.source_sheet,
            source_row_ref=row.row_key,
            import_key=plan["_keys"][row.row_key],
            content_hash=row.content_hash(),
            origin=origin,
            updated_by=actor_id,
        )
        db.add(reg)
        db.flush()
        if prev is not None:
            prev.superseded_by_id = reg.id

    if origin == "import":
        for r in plan["_retire"]:
            r.retired_in_version_id = version.id
    created, updated, unchanged, retired = (plan[k] for k in ("created", "updated", "unchanged", "retired"))
    conflicts = len(plan["conflicts"])

    for code, notes in preview.jurisdiction_notes.items():
        j = cache.get(code) or db.scalar(select(Jurisdiction).where(Jurisdiction.code == code))
        if j is not None:
            j.feature_notes = notes
            j.has_laws = True
    state_notes: dict[str, dict[str, list[str]]] = {}
    for row in preview.rows:
        if row.kind == "note":
            state_notes.setdefault(row.jurisdiction_code, {}).setdefault(row.feature, []).append(row.full_text)
    for code, notes in state_notes.items():
        j = cache.get(code)
        if j is not None:
            j.feature_notes = {k: "\n".join(v) for k, v in notes.items()}

    audit.record(
        db,
        actor_id=actor_id,
        action="law_matrix.publish",
        obj=version,
        organization_id=actor.organization_id if actor else organization_id,
        summary=f"Published law matrix ({created} new, {updated} changed, {unchanged} unchanged, {retired} retired, {conflicts} kept curated)",
    )
    db.flush()
    version.summary = {"created": created, "updated": updated, "unchanged": unchanged, "retired": retired, "conflicts": conflicts}  # transient, for the API response
    return version
