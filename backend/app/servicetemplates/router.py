"""G-06 service templates and engagement types (Release 2 B6). Every endpoint calls `authorize`."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.servicetemplates.types import ENGAGEMENT_TYPES, NEW_ENGAGEMENT_TYPES

router = APIRouter(tags=["service-templates"])


@router.get("/engagement-types")
def engagement_types(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_ENGAGEMENT, list_view=True)
    return {"types": [{"value": k, "label": v, "new": k in NEW_ENGAGEMENT_TYPES} for k, v in ENGAGEMENT_TYPES.items()]}


# ---------------------------------------------------------------- G-06 service template library
from pydantic import BaseModel  # noqa: E402

from app.core.errors import NotFound  # noqa: E402
from app.servicetemplates import service as svc  # noqa: E402


class NoteIn(BaseModel):
    note: str | None = None


def _futran(actor: Actor) -> None:
    if not actor.is_futran:
        raise NotFound()


def _can(db: Session, actor: Actor, action: Action) -> bool:
    from app.core.errors import Forbidden

    try:
        authorize(db, actor, action, list_view=True)
        return True
    except (Forbidden, NotFound):
        return False


@router.get("/service-templates")
def library(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran(actor)
    authorize(db, actor, Action.VIEW_SERVICE_TEMPLATES, list_view=True)
    return {"types": svc.library(db), "can_manage": _can(db, actor, Action.MANAGE_SERVICE_TEMPLATES), "can_approve": _can(db, actor, Action.APPROVE_SERVICE_TEMPLATES)}


@router.get("/service-template-versions/{version_id}")
def get_version(version_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran(actor)
    authorize(db, actor, Action.VIEW_SERVICE_TEMPLATES, list_view=True)
    return svc.version_out(db, svc._load(db, version_id), full=True)


@router.put("/service-template-versions/{version_id}")
def put_version(version_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran(actor)
    authorize(db, actor, Action.MANAGE_SERVICE_TEMPLATES, list_view=True)
    return svc.version_out(db, svc.update_version(db, actor.user, version_id, data), full=True)


@router.post("/service-templates/{template_id}/versions")
def post_version(template_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran(actor)
    authorize(db, actor, Action.MANAGE_SERVICE_TEMPLATES, list_view=True)
    return svc.version_out(db, svc.new_version(db, actor.user, template_id), full=True)


@router.post("/service-template-versions/{version_id}/submit")
def submit(version_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran(actor)
    authorize(db, actor, Action.MANAGE_SERVICE_TEMPLATES, list_view=True)
    return svc.version_out(db, svc.submit(db, actor.user, version_id), full=True)


@router.post("/service-template-versions/{version_id}/approve")
def approve(version_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran(actor)
    authorize(db, actor, Action.APPROVE_SERVICE_TEMPLATES, list_view=True)
    return svc.version_out(db, svc.approve(db, actor.user, version_id, body.note), full=True)


@router.post("/service-template-versions/{version_id}/return")
def return_version(version_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran(actor)
    authorize(db, actor, Action.APPROVE_SERVICE_TEMPLATES, list_view=True)
    return svc.version_out(db, svc.return_version(db, actor.user, version_id, body.note), full=True)


# ---------------------------------------------------------------- board readout pack (A-13): export from a signed report
@router.get("/engagements/{engagement_id}/board-readout.pdf")
def board_readout(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from fastapi.responses import Response

    from app.audit_log import service as audit
    from app.servicetemplates.readout import readout_pdf

    e = authorize(db, actor, Action.VIEW_FINAL_REPORT, engagement_id=engagement_id)
    pdf = readout_pdf(db, e)
    audit.record(db, actor_id=actor.id, action="report.board_readout", obj=e, summary=f"Exported the board readout pack (PDF) for {e.audit_ref}")
    db.commit()
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{e.audit_ref or "engagement"} board readout.pdf"'})
