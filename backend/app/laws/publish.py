"""Publish an import preview as a new matrix version (spec §10.1 import rules 1–5).

Identity: a regulation is the same law across versions when jurisdiction, feature and short name match.
- unchanged content  -> same row; `last_seen_version_id` moves to the new version
- changed content    -> new row; the old row gets `superseded_by_id` (never deleted)
- missing from file  -> old row gets `retired_in_version_id` (never deleted; client references keep working)
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


def _identity(jurisdiction_id: str, feature: str, short_name: str) -> tuple[str, str, str]:
    return (jurisdiction_id, feature, " ".join(short_name.lower().split()))


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


def publish(db: Session, preview: ImportPreview, actor: User | None, edits: dict[str, str], origin: str = "import", label: str | None = None, organization_id: str | None = None) -> MatrixVersion:
    actor_id = actor.id if actor else None
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

    existing = {_identity(r.jurisdiction_id, r.feature, r.short_name): r for r in current_regulations(db)}
    seen: set[str] = set()
    cache: dict[str, Jurisdiction] = {}
    created = updated = unchanged = 0
    for row in preview.rows:
        j = _ensure_jurisdiction(db, row, cache)
        if row.kind != "regulation":
            continue
        short = (edits.get(row.row_key) or row.short_name).strip()
        key = _identity(j.id, row.feature, short)
        h = row.content_hash()
        prev = existing.get(key)
        if prev is not None and prev.content_hash == h:
            prev.last_seen_version_id = version.id
            seen.add(prev.id)
            unchanged += 1
            continue
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
            content_hash=h,
            origin=origin,
            updated_by=actor_id,
        )
        db.add(reg)
        db.flush()
        if prev is not None:
            prev.superseded_by_id = reg.id
            seen.add(prev.id)
            updated += 1
        else:
            created += 1

    retired = 0
    if origin == "import":
        for r in existing.values():
            if r.id not in seen:
                r.retired_in_version_id = version.id
                retired += 1

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
        summary=f"Published law matrix ({created} new, {updated} changed, {unchanged} unchanged, {retired} retired)",
    )
    db.flush()
    version.summary = {"created": created, "updated": updated, "unchanged": unchanged, "retired": retired}  # transient, for the API response
    return version
