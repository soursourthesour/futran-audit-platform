"""G-07 Copilot readiness (`/e/:id/copilot`; client view at `/copilot` for the CAICO). Every endpoint authorizes
against the engagement, whose tenant is the client; the tenant never comes from the request."""
from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.copilot_readiness import imports as imp
from app.copilot_readiness import service as svc
from app.core.db import get_db
from app.core.errors import Forbidden, Invalid, NotFound
from app.documents.csvsafe import to_csv
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.policy.actions import Action
from app.policy.authorize import authorize, can_see_engagement
from app.tenancy.models import Organization

router = APIRouter(tags=["Copilot readiness"])


class SiteIn(BaseModel):
    action: str | None = None
    action_owner: str | None = Field(default=None, max_length=200)
    status: str | None = None
    risk_override: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class WaveIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    groups: str | None = Field(default=None, max_length=400)
    user_count: int | None = None
    planned_on: str | None = None
    gate_site_ids: list[str] | None = None
    gate_control_keys: list[str] | None = None
    hold_note: str | None = Field(default=None, max_length=400)


class ControlIn(BaseModel):
    status: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class PhaseIn(BaseModel):
    phase: str


class RegisterIn(BaseModel):
    register_system_id: str | None = None


def _may(db: Session, actor: Actor, action: Action, e: Engagement) -> bool:
    try:
        authorize(db, actor, action, engagement_id=e.id)
        return True
    except (Forbidden, NotFound):
        return False


def _load(db: Session, actor: Actor, engagement_id: str, action: Action) -> Engagement:
    e = authorize(db, actor, action, engagement_id=engagement_id)
    if e.type != svc.ENGAGEMENT_TYPE:
        raise NotFound()
    return e


def _out(db: Session, actor: Actor, e: Engagement) -> dict:
    perms = {"can_manage": _may(db, actor, Action.MANAGE_COPILOT_READINESS, e), "can_update_sites": _may(db, actor, Action.UPDATE_COPILOT_REMEDIATION, e)}
    ws = svc.find_workspace(db, e)
    if ws is None:  # not started: nothing is created by reading it
        org = db.get(Organization, e.client_id)
        return {"started": False, "engagement": {"id": e.id, "name": e.name, "audit_ref": e.audit_ref}, "client": {"id": org.id, "name": org.name},
                "client_view": not actor.is_futran} | perms
    return svc.view(db, e, ws, client=not actor.is_futran) | {"started": True} | perms


def _read(request: Request, file: UploadFile) -> bytes:
    settings = request.app.state.settings
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise Invalid(errors=[{"field": "file", "message": f"Files can be up to {settings.max_upload_mb} MB. Split the export and upload each part."}])
    return data


@router.get("/copilot")
def client_list(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The client's Copilot readiness engagements (client view)."""
    if actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.VIEW_COPILOT_READINESS, org_id=actor.organization.id)
    rows = db.scalars(select(Engagement).where(Engagement.client_id == actor.organization.id, Engagement.type == svc.ENGAGEMENT_TYPE,
                                               Engagement.deleted_at.is_(None)).order_by(Engagement.created_at.desc()))
    return [{"engagement_id": e.id, "name": e.name, "audit_ref": e.audit_ref, "status": e.status} for e in rows if can_see_engagement(db, actor, e)]


@router.get("/e/{engagement_id}/copilot")
def get_workspace(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _out(db, actor, _load(db, actor, engagement_id, Action.VIEW_COPILOT_READINESS))


@router.post("/e/{engagement_id}/copilot/start")
def start(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    svc.workspace_for(db, e, actor.id)
    db.commit()
    return _out(db, actor, e)


@router.post("/e/{engagement_id}/copilot/imports/{kind}")
def post_import(engagement_id: str, kind: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor),
                db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    if kind not in imp.KINDS:
        raise NotFound()
    ws = svc.workspace_for(db, e, actor.id)
    svc.import_file(db, request.app.state.settings, actor.user, e, ws, kind, _read(request, file), file.filename or f"{kind}.csv")
    db.commit()
    return _out(db, actor, e)


@router.get("/e/{engagement_id}/copilot/sites.csv")
def sites_csv(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.VIEW_COPILOT_READINESS)
    ws = svc.find_workspace(db, e)
    v = svc.view(db, e, ws, client=not actor.is_futran) if ws is not None else {"sites": []}
    rows = [[s["name"], s["url"], s["site_owner"], s["sharing_label"], s["sensitive_items"], s["label_coverage"], s["last_activity"], s["risk"].capitalize(),
             s["action_label"], s["action_owner"], s["status_label"]] for s in v["sites"]]
    body = to_csv(["Site", "URL", "Owner", "Sharing", "Sensitive items", "Label coverage %", "Last activity", "Risk", "Action", "Action owner", "Status"], rows)
    return Response(content=body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="copilot-site-risk-list.csv"'})


@router.put("/e/{engagement_id}/copilot/sites/{site_id}")
def put_site(engagement_id: str, site_id: str, body: SiteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.UPDATE_COPILOT_REMEDIATION)
    data = body.model_dump(exclude_unset=True)
    if set(data) - svc.CLIENT_SITE_FIELDS and not _may(db, actor, Action.MANAGE_COPILOT_READINESS, e):
        raise Forbidden("The audit team sets a site's risk and action; you can record the owner, status and a note.")
    ws = svc.find_workspace(db, e)  # a site exists only in a started workspace; the client never starts one
    if ws is None:
        raise NotFound()
    svc.update_site(db, actor.user, ws, site_id, data)
    db.commit()
    return _out(db, actor, e)


@router.post("/e/{engagement_id}/copilot/waves")
def post_wave(engagement_id: str, body: WaveIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    svc.add_wave(db, actor.user, svc.workspace_for(db, e, actor.id), body.model_dump(exclude_unset=True))
    db.commit()
    return _out(db, actor, e)


@router.put("/e/{engagement_id}/copilot/waves/{wave_id}")
def put_wave(engagement_id: str, wave_id: str, body: WaveIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    svc.update_wave(db, actor.user, svc.workspace_for(db, e, actor.id), wave_id, body.model_dump(exclude_unset=True))
    db.commit()
    return _out(db, actor, e)


@router.delete("/e/{engagement_id}/copilot/waves/{wave_id}")
def delete_wave(engagement_id: str, wave_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    svc.delete_wave(db, actor.user, svc.workspace_for(db, e, actor.id), wave_id)
    db.commit()
    return _out(db, actor, e)


@router.put("/e/{engagement_id}/copilot/controls/{key}")
def put_control(engagement_id: str, key: str, body: ControlIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    svc.update_control(db, actor.user, svc.workspace_for(db, e, actor.id), key, body.status, body.note)
    db.commit()
    return _out(db, actor, e)


@router.post("/e/{engagement_id}/copilot/controls/{key}/evidence")
def post_control_evidence(engagement_id: str, key: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor),
                          db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    svc.control_evidence(db, request.app.state.settings, actor.user, svc.workspace_for(db, e, actor.id), key, _read(request, file), file.filename or "evidence")
    db.commit()
    return _out(db, actor, e)


@router.put("/e/{engagement_id}/copilot/phase")
def put_phase(engagement_id: str, body: PhaseIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    svc.set_phase(db, actor.user, svc.workspace_for(db, e, actor.id), body.phase)
    db.commit()
    return _out(db, actor, e)


@router.post("/e/{engagement_id}/copilot/register")
def post_register(engagement_id: str, body: RegisterIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    svc.register_entry(db, actor.user, e, svc.workspace_for(db, e, actor.id), body.register_system_id)
    db.commit()
    return _out(db, actor, e)


@router.post("/e/{engagement_id}/copilot/report")
def post_report(engagement_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _load(db, actor, engagement_id, Action.MANAGE_COPILOT_READINESS)
    svc.make_report(db, request.app.state.settings, actor.user, e, svc.workspace_for(db, e, actor.id))
    db.commit()
    return _out(db, actor, e)


# Files: the raw admin exports and control evidence stay with the Futran team; the readiness report also goes to the
# client's CAICO (it is their deliverable).
def _import_access(db: Session, actor: Actor, f: FileObject) -> None:
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.VIEW_COPILOT_READINESS, engagement_id=f.engagement_id)


def _report_access(db: Session, actor: Actor, f: FileObject) -> None:
    authorize(db, actor, Action.VIEW_COPILOT_READINESS, engagement_id=f.engagement_id)


def _register_file_rules() -> None:
    from app.files.router import FILE_ACCESS

    FILE_ACCESS.setdefault("copilot_import", _import_access)
    FILE_ACCESS.setdefault("copilot_report", _report_access)


_register_file_rules()
