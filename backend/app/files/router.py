from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.files.models import FileObject
from app.files.service import content_type_for, read
from app.policy.actions import Action
from app.policy.authorize import authorize, visible_org_ids

router = APIRouter(prefix="/files", tags=["files"])


def _package_document_access(db: Session, actor: Actor, f: FileObject) -> None:
    """Clients get the documents of the package that was sent to them; drafts and replaced versions stay with Futran."""
    from app.initiation.models import InitiationPackage, PackageDocument

    authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=f.engagement_id)
    if actor.is_futran:
        return
    doc = db.get(PackageDocument, f.linked_id) if f.linked_id else None
    pkg = db.get(InitiationPackage, doc.package_id) if doc else None
    current = doc is not None and f.id in (doc.pdf_file_id, doc.docx_file_id, doc.csv_file_id)
    if pkg is None or pkg.status != "sent" or not current:
        raise NotFound()


def _evidence_access(db: Session, actor: Actor, f: FileObject) -> None:
    """Futran sees the engagement's evidence. A client sees only files uploaded on the client side, within the
    department or system scope of the thing the file is attached to."""
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_EVIDENCE, engagement_id=f.engagement_id)
        return
    from app.engagements.models import Engagement
    from app.questionnaire.service import uploaded_by_client
    from app.systems.models import AISystem

    e = db.get(Engagement, f.engagement_id) if f.engagement_id else None
    if e is None or not uploaded_by_client(db, f, e):
        raise NotFound()
    s = db.get(AISystem, f.linked_id) if f.linked_id and f.linked_id != e.id else None
    if s is not None and s.engagement_id == e.id:
        try:
            authorize(db, actor, Action.VIEW_EVIDENCE, engagement_id=e.id, department_id=s.department_id, system_id=s.id)
            return
        except Forbidden:
            authorize(db, actor, Action.UPLOAD_REQUESTED_DOCUMENT, engagement_id=e.id, department_id=s.department_id, system_id=s.id)
            return
    authorize(db, actor, Action.VIEW_EVIDENCE, engagement_id=e.id)


def _futran_only(db: Session, actor: Actor, f: FileObject) -> None:
    if not actor.is_futran:
        raise NotFound()
    if f.engagement_id:
        authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=f.engagement_id)
    else:
        allowed = visible_org_ids(db, actor)
        if allowed is not None and f.organization_id not in allowed:
            raise NotFound()


# Who may download a file depends on what it is attached to. A link type not listed here is Futran-only until
# the task that introduces it registers its own rule.
def _governance_access(db: Session, actor: Actor, f: FileObject) -> None:
    authorize(db, actor, Action.VIEW_GOVERNANCE, engagement_id=f.engagement_id)


FILE_ACCESS = {
    "governance_document": _governance_access,
    "package_document": _package_document_access,
    "evidence": _evidence_access,
}


@router.get("/{file_id}")
def download(file_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    f = db.get(FileObject, file_id)
    if f is None or f.deleted_at:
        raise NotFound()
    FILE_ACCESS.get(f.linked_type or "", _futran_only)(db, actor, f)
    if f.linked_type == "evidence":
        audit.record(db, actor_id=actor.id, action="file.view", obj=f, summary=f"Viewed evidence {f.filename}")
    data = read(request.app.state.settings, f)
    ascii_name = f.filename.encode("ascii", "replace").decode().replace('"', "")
    return Response(
        content=data,
        media_type=content_type_for(f.filename),
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(f.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )
