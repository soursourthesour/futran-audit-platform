"""SM-14 master price list API (spec §4.9). Price List Owners edit; the Futran Admin, Chief Auditor and sales roles view,
export and suggest. Every endpoint authorizes; the tenant is Futran's own (no client holds these actions)."""
from datetime import date

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.catalog import fields as F
from app.catalog import io as cio
from app.catalog import pricing
from app.catalog import service as svc
from app.catalog.models import CatalogItem, PackageTemplate, PriceSuggestion
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(tags=["catalog"])


def _can(db: Session, actor: Actor, action: Action) -> bool:
    try:
        authorize(db, actor, action)
        return True
    except Exception:
        return False


def _edit(db: Session, actor: Actor) -> None:
    authorize(db, actor, Action.EDIT_CATALOG)


def _range(it: CatalogItem) -> str:
    if it.low is None and it.high is None:
        return ""
    if it.basis == "%":
        return f"{it.low:g}–{it.high:g}%" if it.low is not None and it.high is not None else ""
    if it.low is not None and it.low == it.high == it.list_price:
        return "fixed"
    lo = f"${it.low:,.0f}" if it.low is not None else "—"
    hi = f"{it.high:,.0f}" if it.high is not None else "—"
    return f"{lo}–{hi}"


def item_out(db: Session, it: CatalogItem, pending: dict[str, list] | None = None, names: dict | None = None) -> dict:
    names = names if names is not None else {}
    if it.updated_by and it.updated_by not in names:
        names[it.updated_by] = svc._name(db, it.updated_by)
    d = {f: getattr(it, f) for f in F.FIELDS}
    return {
        **d, "id": it.id, "code": it.code, "status": it.status, "is_starter": it.is_starter, "range": _range(it), "billing_label": pricing.billing_label(it),
        "included_text": F.quantities_text(it.included_quantities), "version_no": it.version_no,
        "last_changed_by": names.get(it.updated_by) or ("Starter data" if it.is_starter else None), "last_changed_at": it.updated_at.isoformat() if it.updated_at else None,
        "pending": (pending or {}).get(it.code, []),
    }


@router.get("/catalog")
def grid(include_retired: bool = False, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_CATALOG)
    all_items = list(db.scalars(select(CatalogItem).order_by(CatalogItem.code)))
    shown = [i for i in all_items if include_retired or i.status == "active"]
    pending: dict[str, list] = {}
    for p in svc.pending_for(db):
        pending.setdefault(p["code"], []).append(p)
    names: dict = {}
    active = [i for i in all_items if i.status == "active"]
    can_edit = _can(db, actor, Action.EDIT_CATALOG)
    v = svc.versions(db, limit=1)
    flags = svc.rule_flags(db)
    return {
        "items": [item_out(db, i, pending, names) for i in shown], "version": svc.current_version(db), "last_saved": v[0] if v else None,
        "counts": {"items": len(active), "available": sum(i.sellable_status == "available" for i in active),
                   "manual_delivery": sum(i.sellable_status == "manual_delivery" for i in active), "roadmap": sum(i.sellable_status == "roadmap" for i in active),
                   "retired": len(all_items) - len(active)},
        "starter": any(i.is_starter for i in active),
        "can_edit": can_edit, "can_suggest": _can(db, actor, Action.SUGGEST_CATALOG_CHANGE), "can_manage_packages": _can(db, actor, Action.MANAGE_PACKAGES),
        "open_suggestions": db.query(PriceSuggestion).filter_by(status="open").count() if can_edit else None,
        "awaiting_check": [p for ps in pending.values() for p in ps if p["status"] == "awaiting_check"] if can_edit else [],
        "settings": _settings_out(svc.settings(db)),
        "rule_flags": flags,
        "enums": {"products": list(F.PRODUCTS), "billing": F.BILLING, "price_status": F.PRICE_STATUS, "sellable_status": F.SELLABLE, "delivery_mode": F.DELIVERY,
                  "fields": F.FIELDS, "suggestion_fields": svc.SUGGESTION_FIELDS},
        "package_count": db.query(PackageTemplate).count(),
    }


class SaveIn(BaseModel):
    changes: list[dict] = Field(default_factory=list, max_length=2000)
    reason: str = ""
    effective_from: date | None = None
    base_version: int | None = None
    confirm_warnings: bool = False


def _version_out(v) -> dict:
    return {"version": v.version, "change_count": v.change_count, "reason": v.reason, "source": v.source, "saved_at": v.saved_at.isoformat()}


@router.post("/catalog/save")
def save(body: SaveIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    v = svc.save_batch(db, actor.user, body.changes, reason=body.reason, effective_from=body.effective_from, base_version=body.base_version,
                       confirm_warnings=body.confirm_warnings)
    return _version_out(v)


class ItemIn(BaseModel):
    model_config = {"extra": "allow"}
    reason: str = ""


@router.post("/catalog/items")
def add(body: ItemIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    data = {k: v for k, v in body.model_dump().items() if k != "reason"}
    return item_out(db, svc.add_item(db, actor.user, data, reason=body.reason))


class DuplicateIn(BaseModel):
    new_code: str
    name: str | None = None
    reason: str = ""


@router.post("/catalog/items/{code}/duplicate")
def duplicate(code: str, body: DuplicateIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    return item_out(db, svc.duplicate_item(db, actor.user, code, body.new_code, reason=body.reason, name=body.name))


class ReasonIn(BaseModel):
    reason: str = ""


@router.post("/catalog/items/{code}/retire")
def retire(code: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    return item_out(db, svc.retire_item(db, actor.user, code, reason=body.reason))


@router.post("/catalog/items/{code}/restore")
def restore(code: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    return item_out(db, svc.restore_item(db, actor.user, code, reason=body.reason))


@router.get("/catalog/items/{code}/history")
def history(code: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_CATALOG)
    if svc.get_item(db, code, include_retired=True) is None:
        raise NotFound()
    return {"items": svc.history(db, code), "pending": svc.pending_for(db, code)}


class BulkIn(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=500)
    op: dict
    reason: str = ""
    effective_from: date | None = None
    confirm_warnings: bool = False


@router.post("/catalog/bulk/preview")
def bulk_preview(body: BulkIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The changes a bulk edit would make, for the grid to show as unsaved highlights before saving."""
    _edit(db, actor)
    return {"changes": svc.bulk_changes(db, body.codes, body.op)}


@router.post("/catalog/bulk")
def bulk(body: BulkIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    v = svc.bulk_edit(db, actor.user, body.codes, body.op, reason=body.reason, effective_from=body.effective_from, confirm_warnings=body.confirm_warnings)
    return _version_out(v)


@router.get("/catalog/changes")
def changes(code: str | None = None, user_id: str | None = None, version: int | None = None, field: str | None = None, since: date | None = None,
            q: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_CATALOG)
    rows = svc.change_log(db, code=code or None, user_id=user_id or None, version=version, field=field or None, since=since, q=q or None, limit=1000)
    people = sorted({(r["by_id"], r["by"]) for r in svc.change_log(db) if r["by_id"]}, key=lambda x: x[1])
    return {"items": rows, "people": [{"id": i, "name": n} for i, n in people], "versions": svc.versions(db)}


@router.get("/catalog/changes/export.xlsx")
def changes_export(code: str | None = None, user_id: str | None = None, version: int | None = None, field: str | None = None, since: date | None = None,
                   q: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_CATALOG)
    rows = svc.change_log(db, code=code or None, user_id=user_id or None, version=version, field=field or None, since=since, q=q or None)
    return Response(cio.change_log_xlsx(rows), media_type=cio.XLSX,
                    headers={"Content-Disposition": 'attachment; filename="price-list-change-log.xlsx"', "Cache-Control": "private, no-store"})


@router.get("/catalog/versions")
def versions(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_CATALOG)
    return {"items": svc.versions(db)}


@router.get("/catalog/export.xlsx")
def export(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_CATALOG)
    from app.audit_log import service as audit

    audit.record(db, actor_id=actor.id, action="catalog.export", organization_id=actor.organization.id, object_type="CatalogVersion",
                 summary=f"Exported the master price list (version {svc.current_version(db)})", request=request)
    return Response(cio.export_xlsx(db), media_type=cio.XLSX,
                    headers={"Content-Disposition": f'attachment; filename="master-price-list-v{svc.current_version(db)}.xlsx"', "Cache-Control": "private, no-store"})


@router.post("/catalog/import")
async def import_preview(file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    data = await file.read(cio.MAX_BYTES + 1)
    imp = cio.preview(db, actor.user, file.filename or "price-list.xlsx", data)
    return cio.import_out(db, imp)


@router.get("/catalog/imports/{import_id}")
def import_get(import_id: str, retire_missing: bool = True, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    from app.catalog.models import CatalogImport

    imp = db.get(CatalogImport, import_id)
    if imp is None or imp.uploaded_by != actor.id:
        raise NotFound()
    return cio.import_out(db, imp, retire_missing=retire_missing)


class ImportSaveIn(BaseModel):
    reason: str = ""
    retire_missing: bool = True
    confirm_warnings: bool = False


@router.post("/catalog/imports/{import_id}/save")
def import_save(import_id: str, body: ImportSaveIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    v, d = cio.save_import(db, actor.user, import_id, reason=body.reason, retire_missing=body.retire_missing, confirm_warnings=body.confirm_warnings)
    return {**_version_out(v), "added": len(d["adds"]), "changed": len(d["changes"]), "retired": len(d["retirements"]), "restored": len(d["restores"])}


@router.post("/catalog/imports/{import_id}/discard")
def import_discard(import_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    cio.discard(db, actor.user, import_id)
    return {"ok": True}


class SuggestIn(BaseModel):
    item_code: str | None = None
    field: str
    suggested_value: str = ""
    reason: str = ""


@router.post("/catalog/suggestions")
def suggest(body: SuggestIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.SUGGEST_CATALOG_CHANGE)
    return svc.suggestion_out(db, svc.suggest(db, actor.user, item_code=body.item_code, field=body.field, suggested_value=body.suggested_value, reason=body.reason))


@router.get("/catalog/suggestions")
def suggestions(status: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    stmt = select(PriceSuggestion).order_by(PriceSuggestion.created_at.desc())
    if status:
        stmt = stmt.where(PriceSuggestion.status == status)
    return {"items": [svc.suggestion_out(db, s) for s in db.scalars(stmt.limit(500))]}


class DecideIn(BaseModel):
    accept: bool
    note: str | None = None


@router.post("/catalog/suggestions/{suggestion_id}/decide")
def decide(suggestion_id: str, body: DecideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    return svc.suggestion_out(db, svc.decide_suggestion(db, actor.user, suggestion_id, accept=body.accept, note=body.note))


def _settings_out(s) -> dict:
    return {"second_check": bool(s.second_check), "second_check_pct": s.second_check_pct, "manager_discount_limit_pct": s.manager_discount_limit_pct}


@router.get("/catalog/settings")
def get_settings(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_CATALOG)
    return _settings_out(svc.settings(db))


class SettingsIn(BaseModel):
    second_check: bool | None = None
    second_check_pct: float | None = None
    manager_discount_limit_pct: float | None = None


@router.put("/catalog/settings")
def put_settings(body: SettingsIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    return _settings_out(svc.update_settings(db, actor.user, **body.model_dump()))


class CheckIn(BaseModel):
    change_ids: list[str] = Field(min_length=1, max_length=500)
    confirm: bool
    note: str | None = None


@router.post("/catalog/checks/decide")
def decide_checks(body: CheckIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _edit(db, actor)
    v = svc.decide_second_check(db, actor.user, body.change_ids, confirm=body.confirm, note=body.note)
    return {"version": v.version if v else None}


@router.get("/catalog/packages")
def packages(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not (_can(db, actor, Action.VIEW_CATALOG) or _can(db, actor, Action.USE_ESTIMATOR)):
        raise Forbidden()
    return {"items": [svc.package_out(db, p) for p in svc.packages(db)], "can_manage": _can(db, actor, Action.MANAGE_PACKAGES)}


class PackageIn(BaseModel):
    name: str | None = None
    description: str | None = None
    lines: list[dict] | None = Field(default=None, max_length=200)


@router.put("/catalog/packages/{package_id}")
def put_package(package_id: str, body: PackageIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.MANAGE_PACKAGES)
    return svc.package_out(db, svc.update_package(db, actor.user, package_id, name=body.name, description=body.description, lines=body.lines))
