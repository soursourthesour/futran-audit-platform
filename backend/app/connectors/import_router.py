"""G-05 manual discovery import (Release 2 B5). Futran auditors work at /engagements/{id}/discovery on the engagement's
client; the Client Admin works at /integrations/import on their own organisation (tenant from the session). Every
endpoint calls `authorize`."""
import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor, get_settings_dep
from app.connectors import manual_import as mi
from app.connectors import service as svc
from app.connectors.models import DiscoveredTool
from app.core.db import get_db
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization

router = APIRouter(tags=["discovery-import"])


class MatchIn(BaseModel):
    vendor_key: str | None = None
    vendor: str | None = None
    product: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


def _read(settings, file: UploadFile) -> bytes:
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise Invalid(errors=[{"field": "file", "message": f"The file is larger than {settings.max_upload_mb} MB. Split it and import each part."}])
    return data


def _mapping(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        m = json.loads(raw)
    except ValueError as exc:
        raise Invalid(errors=[{"field": "mapping", "message": "The column mapping could not be read."}]) from exc
    if not isinstance(m, dict):
        raise Invalid(errors=[{"field": "mapping", "message": "The column mapping could not be read."}])
    return m


def _page(db: Session, actor: Actor, org: Organization, engagement: Engagement | None, *, can_decide: bool) -> dict:
    """Futran sees every import of the client with its findings for Sales; a client sees only its own imports, with no
    findings, services or opportunities."""
    tools = [t for t in svc.tools(db, org) if t["signal"] == "manual_import"]
    futran = actor.is_futran
    return {
        "engagement": {"id": engagement.id, "name": engagement.name, "audit_ref": engagement.audit_ref, "client_id": org.id, "client_name": org.name} if engagement else None,
        "organization": {"id": org.id, "name": org.name},
        "export_types": [mi.type_out(t) for t in mi.EXPORT_TYPES.values()],
        "presets": mi.presets(db, actor.organization.id),
        "imports": [mi.import_out(db, i, sales=futran) for i in (mi.imports(db, org) if futran else mi.own_imports(db, org))],
        "tools": tools,
        "vendors": [{"key": v.key, "label": f"{v.vendor} {v.product}" if v.product.lower().find(v.vendor.lower()) < 0 else v.product} for v in sorted(svc.vendors.all_vendors(), key=lambda v: v.product.lower())],
        "can_decide": can_decide,
    }


# ---------------------------------------------------------------- Futran: on an engagement
def _engagement(db: Session, actor: Actor, engagement_id: str) -> tuple[Engagement, Organization]:
    if not actor.is_futran:
        raise NotFound()
    e = authorize(db, actor, Action.IMPORT_DISCOVERY, engagement_id=engagement_id)
    org = db.get(Organization, e.client_id)
    if org is None or org.deleted_at is not None:
        raise NotFound()
    return e, org


def _open_engagement(db: Session, actor: Actor, engagement_id: str) -> tuple[Engagement, Organization]:
    """For changes: an archived engagement is read-only."""
    e, org = _engagement(db, actor, engagement_id)
    if e.status == "archived":
        raise Conflict("This engagement is archived. Imports and decisions are no longer taken on it.")
    return e, org


@router.get("/engagements/{engagement_id}/discovery/import")
def futran_page(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e, org = _engagement(db, actor, engagement_id)
    return _page(db, actor, org, e, can_decide=True)


@router.post("/engagements/{engagement_id}/discovery/import/analyse")
def futran_analyse(engagement_id: str, export_type: str = Form(...), mapping: str | None = Form(None), preset_id: str | None = Form(None), file: UploadFile = File(...),
                   actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    _, org = _engagement(db, actor, engagement_id)
    m = _mapping(mapping) or mi.preset_mapping(db, actor.organization.id, preset_id)
    return mi.analyse(db, org, export_type, file.filename, _read(settings, file), m)


@router.post("/engagements/{engagement_id}/discovery/imports")
def futran_import(engagement_id: str, export_type: str = Form(...), mapping: str | None = Form(None), preset_id: str | None = Form(None), save_preset: str | None = Form(None),
                  file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    e, org = _open_engagement(db, actor, engagement_id)
    m = _mapping(mapping) or mi.preset_mapping(db, actor.organization.id, preset_id)
    imp = mi.run_import(db, settings, actor.user, org, e.id, export_type, file.filename, _read(settings, file), m, save_preset=save_preset,
                        preset_owner_id=actor.organization.id)
    return _import_result(db, org, imp)


def _import_result(db: Session, org: Organization, imp, *, sales: bool = True) -> dict:
    out = mi.import_out(db, imp, sales=sales)
    out["tools"] = [t for t in svc.tools(db, org) if t["import_id"] == imp.id]
    return out


@router.post("/engagements/{engagement_id}/discovery/imports/{import_id}/unmatched/{index}/match")
def futran_match(engagement_id: str, import_id: str, index: int, body: MatchIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _, org = _open_engagement(db, actor, engagement_id)
    row = mi.match_unmatched(db, actor.user, org, import_id, index, body.vendor_key, body.vendor, body.product)
    return next(t for t in svc.tools(db, org) if t["id"] == row.id)


def _import_tool(db: Session, org: Organization, tool_id: str) -> DiscoveredTool:
    t = svc._load_tool(db, org, tool_id)
    if t.signal != "manual_import":
        raise Forbidden("Only tools found by a manual import are decided here. The client decides on what its connectors found.")
    return t


@router.post("/engagements/{engagement_id}/discovery/tools/{tool_id}/confirm")
def futran_confirm(engagement_id: str, tool_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    _, org = _open_engagement(db, actor, engagement_id)
    _import_tool(db, org, tool_id)
    svc.confirm(db, settings, actor.user, org, tool_id)
    return next(t for t in svc.tools(db, org) if t["id"] == tool_id)


@router.post("/engagements/{engagement_id}/discovery/tools/{tool_id}/dismiss")
def futran_dismiss(engagement_id: str, tool_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _, org = _open_engagement(db, actor, engagement_id)
    _import_tool(db, org, tool_id)
    svc.dismiss(db, actor.user, org, tool_id, body.reason)
    return next(t for t in svc.tools(db, org) if t["id"] == tool_id)


# ---------------------------------------------------------------- Client Admin: from Integrations
def _client(db: Session, actor: Actor) -> Organization:
    if actor.is_futran:
        raise Forbidden("Futran imports on the engagement: open Discovery import from the audit.")
    authorize(db, actor, Action.IMPORT_DISCOVERY, org_id=actor.organization.id)
    return actor.organization


def _may(db: Session, actor: Actor, action: Action, org_id: str) -> bool:
    try:
        authorize(db, actor, action, org_id=org_id)
        return True
    except (Forbidden, NotFound):
        return False


@router.get("/integrations/import")
def client_page(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(db, actor)
    return _page(db, actor, org, None, can_decide=_may(db, actor, Action.DECIDE_DISCOVERED_TOOLS, org.id))


@router.post("/integrations/import/analyse")
def client_analyse(export_type: str = Form(...), mapping: str | None = Form(None), preset_id: str | None = Form(None), file: UploadFile = File(...),
                   actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor)
    m = _mapping(mapping) or mi.preset_mapping(db, org.id, preset_id)
    return mi.analyse(db, org, export_type, file.filename, _read(settings, file), m)


@router.post("/integrations/imports")
def client_import(export_type: str = Form(...), mapping: str | None = Form(None), preset_id: str | None = Form(None), save_preset: str | None = Form(None),
                  file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor)
    m = _mapping(mapping) or mi.preset_mapping(db, org.id, preset_id)
    imp = mi.run_import(db, settings, actor.user, org, None, export_type, file.filename, _read(settings, file), m, save_preset=save_preset, preset_owner_id=org.id)
    return _import_result(db, org, imp, sales=False)


@router.post("/integrations/imports/{import_id}/unmatched/{index}/match")
def client_match(import_id: str, index: int, body: MatchIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(db, actor)
    if import_id not in {i.id for i in mi.own_imports(db, org)}:
        raise NotFound()
    row = mi.match_unmatched(db, actor.user, org, import_id, index, body.vendor_key, body.vendor, body.product)
    return next(t for t in svc.tools(db, org) if t["id"] == row.id)


# ---------------------------------------------------------------- downloading a client's own import file
def import_file_access(db: Session, actor: Actor, f) -> None:
    """Rule for files.router: an import the Client Admin made from Integrations (no engagement). The importing
    organisation's people who may import, and Futran auditors assigned to that client, may download it."""
    if f.organization_id is None:
        raise NotFound()
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_INTEGRATIONS, org_id=f.organization_id)
        return
    if actor.organization.id != f.organization_id:
        raise NotFound()
    authorize(db, actor, Action.IMPORT_DISCOVERY, org_id=f.organization_id)


def _register_file_rule() -> None:
    from app.files.router import FILE_ACCESS

    FILE_ACCESS.setdefault("discovery_import", import_file_access)


_register_file_rule()
