"""Excel export and import for the master price list (spec §4.9 "Load and initial values").

Export writes every item with the same columns the importer reads, so an exported workbook re-imports unchanged;
text cells are formula-safe. Import reads the "Master Price List" sheet (or the first sheet with a Code and List header)
through app.core.xlsx_guard, previews adds, changes and retirements, and saves them as one catalog version with a reason."""
import hashlib
import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import fields as F
from app.catalog import service as cat
from app.catalog.models import CatalogChange, CatalogImport, CatalogItem
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.core.xlsx_guard import WorkbookTooLarge, open_workbook, rows
from app.documents.csvsafe import FORMULA_START, safe_cell

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_ROWS, MAX_COLS = 2000, 60
MAX_BYTES = 5 * 1024 * 1024

# Export columns in workbook order: the workbook's A–L, the Release 2 columns M–S, then the app's own.
COLUMNS: list[tuple[str, str]] = [
    ("code", "Code"), ("product", "Product"), ("name", "Line item"), ("pricing_unit", "Pricing unit"), ("billing", "Billing"), ("basis", "Basis"),
    ("periods_per_year", "Periods/yr"), ("low", "Low"), ("list_price", "List"), ("high", "High"), ("price_status", "Price status"), ("notes", "Notes"),
    ("deliverables", "Deliverables"), ("sellable_status", "Sellable status"), ("delivery_mode", "Delivery mode"),
    ("platform_feature_ref", "Platform feature / release"), ("included_quantities", "Included quantities"), ("engagement_type", "Engagement type"),
    ("entitlement_key", "Entitlement key"), ("description", "Description"), ("applies_to", "Applies to"), ("remediation_of", "Remediation of"),
    ("status", "Status"),
]
READONLY_COLUMNS = ["Last changed by", "Last changed at"]

HEADER_ALIASES = {
    "code": "code", "product": "product", "line item": "name", "item": "name", "name": "name", "pricing unit": "pricing_unit", "unit": "pricing_unit",
    "billing": "billing", "basis": "basis", "periods yr": "periods_per_year", "periods per year": "periods_per_year", "periods": "periods_per_year",
    "low": "low", "list": "list_price", "list price": "list_price", "high": "high", "price status": "price_status", "notes": "notes",
    "deliverables": "deliverables", "deliverables what the client gets": "deliverables", "description": "description",
    "short proposal description": "description", "sellable status": "sellable_status", "sellable": "sellable_status", "delivery mode": "delivery_mode",
    "platform feature release": "platform_feature_ref", "platform feature": "platform_feature_ref", "included quantities": "included_quantities",
    "included": "included_quantities", "engagement type": "engagement_type", "entitlement key": "entitlement_key", "applies to": "applies_to",
    "remediation of": "remediation_of", "status": "status",
}


KEEP_WHEN_BLANK = {"product", "name", "billing", "basis", "periods_per_year", "price_status", "sellable_status"}


def _unescape(v: str) -> str:
    """Undo the exporter's formula-safe apostrophe (csvsafe.safe_cell): only a leading ' followed by a formula character."""
    return v[1:] if len(v) > 1 and v[0] == "'" and v[1] in "".join(FORMULA_START) else v


def _norm(h) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(h or "").casefold())).strip()


def _cell(field: str, value):
    if value is None:
        return None
    if field in F.NUMBER_FIELDS or field == "periods_per_year":
        return value
    if field == "status":
        return "Retired" if value == "retired" else "Active"
    return safe_cell(F.display(field, value)) or None


def _sheet(ws, header: list[str], data: list[list], widths: dict[int, int] | None = None) -> None:
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in data:
        ws.append(r)
    ws.freeze_panes = "B2"
    for i, w in (widths or {}).items():
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=isinstance(c.value, str) and len(c.value) > 40, vertical="top")


def _bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_xlsx(db: Session, *, include_retired: bool = True) -> bytes:
    stmt = select(CatalogItem).order_by(CatalogItem.code)
    if not include_retired:
        stmt = stmt.where(CatalogItem.status == "active")
    items = list(db.scalars(stmt))
    names = {}
    data = []
    for it in items:
        if it.updated_by and it.updated_by not in names:
            names[it.updated_by] = cat._name(db, it.updated_by)
        data.append([_cell(f, getattr(it, f)) for f, _ in COLUMNS] + [safe_cell(names.get(it.updated_by) or ""), it.updated_at.strftime("%Y-%m-%d %H:%M")])
    wb = Workbook()
    ws = wb.active
    ws.title = "Master Price List"
    _sheet(ws, [h for _, h in COLUMNS] + READONLY_COLUMNS, data, {1: 10, 3: 40, 13: 70})
    info = wb.create_sheet("About")
    info.append(["Futran Audit Platform — master price list"])
    info.append([f"Catalog version {cat.current_version(db)}, exported {utcnow():%Y-%m-%d %H:%M} UTC"])
    info.append(["Edit the Master Price List sheet and import it on the price list screen; you will see a preview before anything is saved."])
    return _bytes(wb)


def change_log_xlsx(rows_: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Change log"
    data = [[r["version"], r["at"][:16].replace("T", " "), safe_cell(r["by"]), safe_cell(r["code"]), safe_cell(r["label"]), safe_cell(r["old_display"]),
             safe_cell(r["new_display"]), safe_cell(r["reason"]), r["effective_from"] or "", r["status"], safe_cell(r["confirmed_by"] or "")] for r in rows_]
    _sheet(ws, ["Version", "When (UTC)", "By", "Code", "Field", "Old value", "New value", "Reason", "Effective from", "Status", "Confirmed by"], data,
           {5: 18, 6: 40, 7: 40, 8: 40})
    return _bytes(wb)


# ---- import
def parse_workbook(data: bytes) -> tuple[list[dict], list[dict]]:
    """Rows as {row, code, values{field: parsed}} and errors [{row, code, field, message}]. Raises Invalid when the file
    can't be read at all."""
    if len(data) > MAX_BYTES:
        raise Invalid(errors=[{"field": "file", "message": "The file is over 5 MB. Remove other sheets and try again."}])
    try:
        wb = open_workbook(data, max_rows=MAX_ROWS, max_cols=MAX_COLS)
    except WorkbookTooLarge as exc:
        raise Invalid(errors=[{"field": "file", "message": str(exc)}]) from exc
    except Exception as exc:
        raise Invalid(errors=[{"field": "file", "message": "This is not a readable Excel workbook (.xlsx)."}]) from exc
    sheets = sorted(wb.worksheets, key=lambda s: 0 if _norm(s.title) == "master price list" else 1)
    for ws in sheets:
        grid = list(rows(ws, max_rows=MAX_ROWS, max_cols=MAX_COLS))
        for hi, header in enumerate(grid[:15]):
            cols = {i: HEADER_ALIASES.get(_norm(h)) for i, h in enumerate(header or [])}
            fields_ = set(cols.values())
            if "code" in fields_ and "list_price" in fields_:
                return _rows(grid[hi + 1:], cols, hi + 2)
    raise Invalid(errors=[{"field": "file", "message": "No sheet has a header row with Code and List columns. Use the Master Price List sheet, or export the price list for a template."}])


def _rows(grid: list, cols: dict[int, str | None], first_row: int) -> tuple[list[dict], list[dict]]:
    out, errors, seen = [], [], set()
    for n, raw in enumerate(grid, start=first_row):
        vals = {cols[i]: v for i, v in enumerate(raw or []) if cols.get(i)}
        code = str(vals.get("code") or "").strip()
        if not code and not any(v not in (None, "") for v in vals.values()):
            continue
        try:
            code = F.check_code(code)
        except F.FieldError as exc:
            errors.append({"row": n, "code": code, "field": "code", "message": str(exc)})
            continue
        if code in seen:
            errors.append({"row": n, "code": code, "field": "code", "message": f"{code} appears twice in the workbook."})
            continue
        seen.add(code)
        parsed: dict = {}
        for field, v in vals.items():
            if field == "code":
                continue
            if field == "status":
                parsed["status"] = "retired" if _norm(v) == "retired" else "active"
                continue
            if isinstance(v, str):
                v = _unescape(v).strip()
            if v in (None, "") and field in KEEP_WHEN_BLANK:
                continue  # a blank cell in a required column leaves the value as it is (a new item takes the default)
            try:
                parsed[field] = F.parse(field, v)
            except F.FieldError as exc:
                errors.append({"row": n, "code": code, "field": field, "message": f"{F.FIELD_LABELS.get(field, field)}: {exc}"})
        if parsed.get("billing") is None and "billing" in parsed:
            parsed.pop("billing")
        out.append({"row": n, "code": code, "values": parsed})
    return out, errors


def _default_new(vals: dict) -> dict:
    billing = vals.get("billing") or "one_time"
    base = {"billing": billing, "basis": "$", "periods_per_year": F.BILLING_PERIODS.get(billing, 1), "price_status": "proposed",
            "sellable_status": "available", "included_quantities": {}, "applies_to": [], "remediation_of": []}
    return {**base, **{k: v for k, v in vals.items() if v is not None or k not in base}}


def diff(db: Session, parsed: list[dict], *, retire_missing: bool = True) -> dict:
    """What saving would do: adds, changes (per field), retirements, restores, plus row errors and warnings."""
    existing = {i.code: i for i in db.scalars(select(CatalogItem))}
    adds, changes, retire, restore, errors, warnings = [], [], [], [], [], []
    in_book = set()
    for r in parsed:
        code, vals = r["code"], dict(r["values"])
        in_book.add(code)
        status = vals.pop("status", None)
        item = existing.get(code)
        if item is None:
            new = _default_new(vals)
            missing = [lbl for f, lbl in (("product", "Product"), ("name", "Line item")) if not new.get(f)]
            if missing:
                errors.append({"row": r["row"], "code": code, "field": "row", "message": f"{code}: {' and '.join(missing)} needed for a new item."})
                continue
            for m in F.item_errors(new):
                errors.append({"row": r["row"], "code": code, "field": "row", "message": f"{code}: {m}"})
            adds.append({"row": r["row"], "code": code, "name": new.get("name"), "values": new, "retired": status == "retired"})
            continue
        before = cat.values(item)
        after = {**before, **vals}
        for m in F.item_errors(after):
            errors.append({"row": r["row"], "code": code, "field": "row", "message": f"{code}: {m}"})
        for field, new in vals.items():
            if new != before.get(field):
                changes.append({"row": r["row"], "code": code, "field": field, "label": F.FIELD_LABELS[field], "old_value": before.get(field), "new_value": new,
                                "old_display": F.display(field, before.get(field)), "new_display": F.display(field, new)})
        if "list_price" in vals:
            w = F.list_move_warning(before.get("list_price"), vals["list_price"])
            if w:
                warnings.append({"row": r["row"], "code": code, "field": "list_price", "message": f"{code}: {w}", "kind": "warning"})
        if status == "retired" and item.status == "active":
            retire.append({"code": code, "name": item.name})
        elif status != "retired" and item.status == "retired":
            restore.append({"code": code, "name": item.name})
    if retire_missing:
        for code, item in sorted(existing.items()):
            if code not in in_book and item.status == "active":
                retire.append({"code": code, "name": item.name, "missing": True})
    return {"adds": adds, "changes": changes, "retirements": retire, "restores": restore, "errors": errors, "warnings": warnings}


def preview(db: Session, user, filename: str, data: bytes) -> CatalogImport:
    cat._require_owner(db, user)
    parsed, errors = parse_workbook(data)
    imp = CatalogImport(filename=(filename or "price-list.xlsx")[:200], sha256=hashlib.sha256(data).hexdigest(), rows=parsed, errors=errors,
                        base_version=cat.current_version(db), status="preview", uploaded_by=user.id)
    db.add(imp)
    db.flush()
    from app.audit_log import service as audit

    audit.record(db, actor_id=user.id, action="catalog.import_preview", organization_id=user.organization_id, object_type="CatalogImport", object_id=imp.id,
                 summary=f"Previewed price list import {imp.filename} ({len(parsed)} rows, sha256 {imp.sha256[:12]})")
    return imp


def import_out(db: Session, imp: CatalogImport, *, retire_missing: bool = True) -> dict:
    d = diff(db, imp.rows, retire_missing=retire_missing)
    errors = imp.errors + d["errors"]
    return {"id": imp.id, "filename": imp.filename, "status": imp.status, "rows": len(imp.rows), "base_version": imp.base_version,
            "adds": d["adds"], "changes": d["changes"], "retirements": d["retirements"], "restores": d["restores"], "errors": errors, "warnings": d["warnings"],
            "can_save": not errors and bool(d["adds"] or d["changes"] or d["retirements"] or d["restores"])}


def save_import(db: Session, user, import_id: str, *, reason: str, retire_missing: bool = True, confirm_warnings: bool = False):
    cat._require_owner(db, user)
    reason = cat._check_reason(reason)
    imp = db.get(CatalogImport, import_id)
    if imp is None or imp.uploaded_by != user.id:
        raise NotFound()
    if imp.status != "preview":
        raise Conflict("This import has already been saved or discarded.")
    if cat.current_version(db) != imp.base_version:
        raise Conflict("The price list changed after this preview. Upload the workbook again to see an up-to-date preview.")
    d = diff(db, imp.rows, retire_missing=retire_missing)
    errors = imp.errors + d["errors"]
    if errors:
        raise Invalid("Fix the rows with problems in the workbook and upload it again.", errors=[{**e, "kind": "error"} for e in errors])
    if d["warnings"] and not confirm_warnings:
        raise Invalid("Check these changes, then confirm to save.", errors=d["warnings"])
    total = len(d["adds"]) + len(d["changes"]) + len(d["retirements"]) + len(d["restores"])
    if not total:
        raise Invalid("Nothing to save: the workbook matches the price list.")
    v = cat._new_version(db, user, reason, "import", total)
    now = utcnow()
    for a in d["adds"]:
        item = cat._create(db, user, a["code"], a["values"], v, now)
        if a["retired"]:
            item.status = "retired"
    items = {i.code: i for i in db.scalars(select(CatalogItem))}
    cfg = cat.settings(db)
    held = []
    for c in d["changes"]:
        if cat.needs_second_check(cfg, c["field"], c["old_value"], c["new_value"]):
            ch = CatalogChange(catalog_version_id=v.id, item_code=c["code"], field=c["field"], old_value=c["old_value"], new_value=c["new_value"],
                               status="awaiting_check", reason=reason, changed_by=user.id, changed_at=now)
            db.add(ch)
            db.flush()
            items[c["code"]].pending_change_id = ch.id
            held.append(ch)
            continue
        db.add(CatalogChange(catalog_version_id=v.id, item_code=c["code"], field=c["field"], old_value=c["old_value"], new_value=c["new_value"], status="applied",
                             applied_at=now, applied_version_id=v.id, reason=reason, changed_by=user.id, changed_at=now))
        cat._apply(items[c["code"]], c["field"], c["new_value"], v, user.id, now)
    if held:
        cat._ask_second_check(db, user, v, held)
    for lst, new in ((d["retirements"], "retired"), (d["restores"], "active")):
        for r in lst:
            item = items[r["code"]]
            db.add(CatalogChange(catalog_version_id=v.id, item_code=r["code"], field="status", old_value=item.status, new_value=new, status="applied",
                                 applied_at=now, applied_version_id=v.id, reason=reason, changed_by=user.id, changed_at=now))
            cat._apply(item, "status", new, v, user.id, now)
    for code in {r["code"] for r in imp.rows} & set(items):
        items[code].is_starter = False  # loaded from the real workbook now
    imp.status, imp.saved_version_id = "saved", v.id
    db.flush()
    cat._audit(db, user, "catalog.import", v, f"Imported {imp.filename}: {len(d['adds'])} added, {len(d['changes'])} changes, "
                                              f"{len(d['retirements'])} retired, {len(d['restores'])} restored — {reason}")
    return v, d


def discard(db: Session, user, import_id: str) -> None:
    cat._require_owner(db, user)
    imp = db.get(CatalogImport, import_id)
    if imp is None or imp.uploaded_by != user.id:
        raise NotFound()
    if imp.status == "preview":
        imp.status = "discarded"
