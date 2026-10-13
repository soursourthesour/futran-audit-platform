from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.files.models import FileObject
from app.files.service import read
from app.policy.actions import Action
from app.policy.authorize import authorize, visible_org_ids

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}")
def download(file_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    f = db.get(FileObject, file_id)
    if f is None or f.deleted_at:
        raise NotFound()
    evidence = f.linked_type == "evidence"
    if f.engagement_id:
        authorize(db, actor, Action.VIEW_EVIDENCE if evidence else Action.VIEW_ENGAGEMENT, engagement_id=f.engagement_id)
    else:
        allowed = visible_org_ids(db, actor)
        if allowed is not None and f.organization_id not in allowed:
            raise NotFound()
    if evidence:
        audit.record(db, actor_id=actor.id, action="file.view", obj=f, summary=f"Viewed evidence {f.filename}")
    data = read(request.app.state.settings, f)
    ascii_name = f.filename.encode("ascii", "replace").decode().replace('"', "")
    return Response(
        content=data,
        media_type=f.content_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(f.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
