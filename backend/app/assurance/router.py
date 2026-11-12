"""G-09 Agent assurance (Release 2 B9). The client's CAICO reads it on the register record (/register/{id}/assurance,
tenant from the session); Futran reads and records at /clients/{client_id}/register/{id}/assurance. Every endpoint calls
`authorize`."""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.assurance import service as svc
from app.auth.deps import Actor, current_actor, get_settings_dep
from app.core.db import get_db
from app.core.errors import Forbidden, Invalid, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.register.models import RegisterSystem
from app.tenancy.models import Organization

router = APIRouter(tags=["agent-assurance"])


class ChecklistIn(BaseModel):
    items: list[dict]


def _may(db: Session, actor: Actor, action: Action, org_id: str | None = None, list_view: bool = False) -> bool:
    try:
        authorize(db, actor, action, org_id=org_id, list_view=list_view)
        return True
    except (Forbidden, NotFound):
        return False


def _page(db: Session, actor: Actor, s: RegisterSystem) -> dict:
    return svc.page(db, s, can_record=actor.is_futran and _may(db, actor, Action.RECORD_AGENT_ASSURANCE, s.organization_id),
                    can_sync=actor.is_futran and _may(db, actor, Action.SYNC_AGENTWARDEN, s.organization_id),
                    can_edit_checklist=_may(db, actor, Action.MANAGE_ASSURANCE_CHECKLIST, list_view=True))


# ---------------------------------------------------------------- client: the register record's Assurance tab
@router.get("/register/{system_id}/assurance")
def client_page(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.router import load

    s = load(db, actor, system_id)
    authorize(db, actor, Action.VIEW_AGENT_ASSURANCE, org_id=s.organization_id)
    return _page(db, actor, s)


# ---------------------------------------------------------------- Futran
def _futran_system(db: Session, actor: Actor, client_id: str, system_id: str, action: Action) -> RegisterSystem:
    if not actor.is_futran:
        raise NotFound()
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, action, org_id=org.id)
    s = db.get(RegisterSystem, system_id)
    if s is None or s.organization_id != org.id or s.deleted_at is not None:
        raise NotFound()
    return s


@router.get("/clients/{client_id}/register/{system_id}/assurance")
def futran_page(client_id: str, system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _futran_system(db, actor, client_id, system_id, Action.VIEW_AGENT_ASSURANCE)
    out = _page(db, actor, s)
    out["client_name"] = db.get(Organization, client_id).name
    return out


@router.post("/clients/{client_id}/register/{system_id}/assurance/runs")
def record(client_id: str, system_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _futran_system(db, actor, client_id, system_id, Action.RECORD_AGENT_ASSURANCE)
    return svc.run_out(db, svc.record_run(db, actor.user, s, data))


@router.post("/clients/{client_id}/register/{system_id}/assurance/runs/{run_id}/letter")
def letter(client_id: str, system_id: str, run_id: str, signed_by: str = Form(""), signed_on: str = Form(""), file: UploadFile = File(...),
           actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    s = _futran_system(db, actor, client_id, system_id, Action.RECORD_AGENT_ASSURANCE)
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise Invalid(errors=[{"field": "file", "message": f"Files can be up to {settings.max_upload_mb} MB."}])
    r = svc.attach_letter(db, settings, actor.user, s, run_id, filename=file.filename or "assurance-letter.pdf", data=data, signed_by=signed_by, signed_on=signed_on)
    return svc.run_out(db, r)


@router.post("/clients/{client_id}/agentwarden/sync")
def warden_sync(client_id: str, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"),
                settings=Depends(get_settings_dep)):
    if not actor.is_futran:
        raise NotFound()
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.SYNC_AGENTWARDEN, org_id=org.id)
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise Invalid(errors=[{"field": "file", "message": f"The file is larger than {settings.max_upload_mb} MB."}])
    return svc.sync_warden(db, actor.user, org.id, file.filename, data)


# ---------------------------------------------------------------- the 15-point list (Futran's reference data)
@router.get("/assurance/checklist")
def get_checklist(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.VIEW_AGENT_ASSURANCE, list_view=True)
    return {"items": svc.checklist(db), "note": svc.CHECKLIST_NOTE, "can_edit": _may(db, actor, Action.MANAGE_ASSURANCE_CHECKLIST, list_view=True)}


@router.put("/assurance/checklist")
def put_checklist(body: ChecklistIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.MANAGE_ASSURANCE_CHECKLIST, list_view=True)
    return {"items": svc.save_checklist(db, actor.user, body.items), "note": svc.CHECKLIST_NOTE, "can_edit": True}
