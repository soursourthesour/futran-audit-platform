import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.config import Settings
from app.core.errors import Invalid
from app.files.models import FileObject
from app.files.scan import scan
from app.files.storage import get_storage, safe_name
from app.tenancy.models import User

# Served Content-Type comes from this table, never from the uploader. No HTML, XML or SVG: nothing a browser would run.
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".rtf": "application/rtf",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".zip": "application/zip",
    ".json": "application/json",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
}
ALLOWED_EXTENSIONS = set(CONTENT_TYPES)


def content_type_for(filename: str) -> str:
    return CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


def upload(
    db: Session,
    settings: Settings,
    actor: User | None,
    *,
    data: bytes,
    filename: str,
    content_type: str | None,
    organization_id: str,
    engagement_id: str | None = None,
    linked_type: str | None = None,
    linked_id: str | None = None,
) -> FileObject:
    """Store one file. Rejects files over the size limit, types outside the allow-list and files that fail the scan."""
    limit = settings.max_upload_mb
    if len(data) > limit * 1024 * 1024:
        raise Invalid(f"Files can be up to {limit} MB. This one is {len(data) / 1024 / 1024:.1f} MB.", [{"field": "file", "message": "File too large."}])
    name = safe_name(filename)
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise Invalid("This file type can't be uploaded. Use PDF, Word, Excel, CSV, PowerPoint, text, images or ZIP.", [{"field": "file", "message": "File type not allowed."}])
    status = scan(data, settings)
    if status == "infected":
        audit.record(db, actor_id=actor.id if actor else None, action="file.rejected_virus", object_type="File", object_id=None, organization_id=organization_id, summary=f"Rejected {name}: failed the virus scan")
        raise Invalid("This file failed the virus scan and was not stored.", [{"field": "file", "message": "Virus detected."}])
    key = get_storage(settings).put(organization_id, data, name)
    f = FileObject(
        organization_id=organization_id, engagement_id=engagement_id, storage_key=key, filename=name,
        content_type=content_type_for(name), size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        scan_status=status, uploaded_by=actor.id if actor else None, linked_type=linked_type, linked_id=linked_id,
        created_by=actor.id if actor else None,
    )
    db.add(f)
    db.flush()
    audit.record(db, actor_id=actor.id if actor else None, action="file.upload", obj=f, summary=f"Uploaded {name} ({len(data)} bytes)")
    return f


def read(settings: Settings, f: FileObject) -> bytes:
    return get_storage(settings).get(f.storage_key)
