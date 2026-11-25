import hashlib
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.config import Settings
from app.core.errors import AppError, Invalid
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
log = logging.getLogger(__name__)


class StoredFileMissing(AppError, FileNotFoundError):
    """The file's record exists but its bytes are gone from storage: 410, not a server error (BUG-01).
    Also an OSError, so callers that already treat an unreadable file as OSError keep working."""

    status_code = 410

    def __init__(self, detail: str = "The stored file is missing. Ask Futran to upload it again.", errors=None):
        super().__init__(detail, errors)


def content_type_for(filename: str) -> str:
    return CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


UPLOAD_CHUNK = 1024 * 1024


async def read_upload(file, max_bytes: int) -> bytes:
    """Read an uploaded file in chunks, stopping one byte past `max_bytes`, so the caller's size check refuses an
    over-limit file without the whole request being held in memory."""
    buf = bytearray()
    while len(buf) <= max_bytes:
        chunk = await file.read(min(UPLOAD_CHUNK, max_bytes + 1 - len(buf)))
        if not chunk:
            break
        buf += chunk
    return bytes(buf)


def upload_limit_bytes(settings: Settings) -> int:
    return settings.max_upload_mb * 1024 * 1024


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
        raise Invalid(f"This file is over the {limit} MB limit.", [{"field": "file", "message": "File too large."}])  # callers stop reading just past the limit
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
    try:
        return get_storage(settings).get(f.storage_key)
    except FileNotFoundError:
        log.warning("Stored file missing: file %s (%s), organization %s, key %s", f.id, f.filename, f.organization_id, f.storage_key)
        raise StoredFileMissing() from None
