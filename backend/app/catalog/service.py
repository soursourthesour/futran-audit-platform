"""Master price list service (spec §4.9). Other workstreams read prices only through `get_item`, `items_by_codes` and
`current_version`; every change goes through a saved batch here, so history, reasons and versions are never skipped."""
import math
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog import fields as F
from app.catalog.models import CatalogChange, CatalogItem, CatalogSetting, CatalogVersion, PackageTemplate, PriceSuggestion
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.tenancy.models import RoleAssignment, User
from app.tenancy.service import roles_of

OWNER_ROLE = "price_list_owner"


# ---- the shared lookups (plan "Shared names")
def get_item(db: Session, code: str, *, include_retired: bool = False) -> CatalogItem | None:
    stmt = select(CatalogItem).where(CatalogItem.code == code)
    if not include_retired:
        stmt = stmt.where(CatalogItem.status == "active")
    return db.scalar(stmt)


def current_version(db: Session) -> int:
    return db.scalar(select(func.max(CatalogVersion.version))) or 0


def items_by_codes(db: Session, codes) -> dict[str, CatalogItem]:
    """Items for these codes, retired ones included: old estimates and proposals keep lines whose item has since retired."""
    codes = [c for c in dict.fromkeys(codes or []) if c]
    if not codes:
        return {}
    return {i.code: i for i in db.scalars(select(CatalogItem).where(CatalogItem.code.in_(codes)))}


# ---- people
def is_owner(db: Session, user: User) -> bool:
    return OWNER_ROLE in {r.role for r in roles_of(db, user.id)}


def owners(db: Session) -> list[User]:
    users = db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id)
                       .where(RoleAssignment.role == OWNER_ROLE, RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None)))
    return [u for u in dict.fromkeys(users) if u.status != "disabled" and is_owner(db, u)]


def _require_owner(db: Session, user: User) -> None:
    if not is_owner(db, user):
        raise Forbidden("Only the Price List Owners (CEO and President) can change the master price list.")


def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


# ---- settings
def settings(db: Session) -> CatalogSetting:
    s = db.scalar(select(CatalogSetting).where(CatalogSetting.key == "platform"))
    return s or CatalogSetting(key="platform", second_check=False, second_check_pct=10, manager_discount_limit_pct=15)


def update_settings(db: Session, user: User, *, second_check: bool | None = None, second_check_pct: float | None = None,
                    manager_discount_limit_pct: float | None = None) -> CatalogSetting:
    _require_owner(db, user)
    s = db.scalar(select(CatalogSetting).where(CatalogSetting.key == "platform"))
    if s is None:
        s = CatalogSetting(key="platform", second_check=False, second_check_pct=10, manager_discount_limit_pct=15)
        db.add(s)
    if second_check_pct is not None and not 0 < second_check_pct <= 100:
        raise Invalid(errors=[{"field": "second_check_pct", "message": "Enter a percentage between 0 and 100."}])
    if manager_discount_limit_pct is not None and not 0 <= manager_discount_limit_pct <= 100:
        raise Invalid(errors=[{"field": "manager_discount_limit_pct", "message": "Enter a percentage between 0 and 100."}])
    if second_check is not None:
        s.second_check = second_check
    if second_check_pct is not None:
        s.second_check_pct = second_check_pct
    if manager_discount_limit_pct is not None:
        s.manager_discount_limit_pct = manager_discount_limit_pct
    s.updated_by = user.id
    db.flush()
    _audit(db, user, "catalog.settings", None, f"Price list settings: second check {'on' if s.second_check else 'off'} above {s.second_check_pct:g}%; "
                                              f"Sales Manager discount limit {s.manager_discount_limit_pct:g}%")
    return s


# ---- values
def values(item: CatalogItem) -> dict:
    return {f: getattr(item, f) for f in F.FIELDS}


def _audit(db: Session, user: User, action: str, v: CatalogVersion | None, summary: str) -> None:
    from app.audit_log import service as audit

    audit.record(db, actor_id=user.id if user else None, action=action, organization_id=user.organization_id if user else _futran_org_id(db),
                 object_type="CatalogVersion" if v else "CatalogSetting", object_id=v.id if v else None, summary=summary[:500],
                 after={"version": v.version, "changes": v.change_count, "reason": v.reason} if v else None)


def _futran_org_id(db: Session) -> str:
    from app.tenancy.models import Organization

    org = db.scalar(select(Organization).where(Organization.type == "futran").order_by(Organization.is_internal))
    return org.id if org else "futran"


def _new_version(db: Session, user: User | None, reason: str, source: str, count: int) -> CatalogVersion:
    from app.core.db import hold_transaction

    hold_transaction(db)
    v = CatalogVersion(version=current_version(db) + 1, saved_by=user.id if user else None, saved_at=utcnow(), reason=reason, source=source, change_count=count)
    db.add(v)
    db.flush()
    return v


def _check_reason(reason: str | None) -> str:
    r = (reason or "").strip()
    if not r:
        raise Invalid(errors=[{"field": "reason", "message": "Give one reason for this batch of changes."}])
    return r[:2000]


def _check_effective(effective_from: date | None) -> date | None:
    if effective_from is None or effective_from <= today():
        if effective_from is not None and effective_from < today():
            raise Invalid(errors=[{"field": "effective_from", "message": "Choose today or a future date."}])
        return None
    return effective_from


def _rel(old, new) -> float:
    if not old:
        return math.inf if new else 0.0
    return abs((new or 0) - old) / old


def needs_second_check(cfg: CatalogSetting, field: str, old, new) -> bool:
    """A price change above the second-check limit waits for the other Price List Owner (grid, bulk and import alike)."""
    return bool(cfg.second_check) and field in F.PRICE_FIELDS and _rel(old, new) * 100 > cfg.second_check_pct


def save_batch(db: Session, user: User, changes: list[dict], *, reason: str, effective_from: date | None = None, base_version: int | None = None,
               confirm_warnings: bool = False, source: str = "grid") -> CatalogVersion:
    """Save one batch of field changes [{code, field, value}] with one reason. Raises Invalid with every problem found
    (`kind` "error", or "warning" when only a confirmation is missing), or Conflict when someone saved the same item
    after `base_version`. The batch becomes the next catalog version."""
    _require_owner(db, user)
    reason = _check_reason(reason)
    eff = _check_effective(effective_from)
    from app.core.db import hold_transaction

    hold_transaction(db)  # take the write lock before reading the rows, so the stale check below and the save are one step
    by_code: dict[str, dict] = defaultdict(dict)
    errors: list[dict] = []
    for ch in changes or []:
        code, field = ch.get("code"), ch.get("field")
        try:
            by_code[code][field] = F.parse(field, ch.get("value"))
        except F.FieldError as exc:
            errors.append({"code": code, "field": field, "message": str(exc), "kind": "error"})
    items = items_by_codes(db, list(by_code))
    for code in by_code:
        if code not in items:
            errors.append({"code": code, "field": "code", "message": f"{code} is not on the price list.", "kind": "error"})
        elif items[code].status != "active":
            errors.append({"code": code, "field": "status", "message": f"{code} is retired. Restore it before changing it.", "kind": "error"})
    if errors:
        raise Invalid(errors=errors)
    if base_version is not None:
        stale = [c for c in by_code if items[c].version_no > base_version]
        if stale:
            raise Conflict(f"Someone saved {', '.join(stale)} after you opened the price list. Reload to see their change, then make yours again.")
    cfg = settings(db)
    plan: list[tuple[CatalogItem, str, object, object, str]] = []  # item, field, old, new, status
    warnings: list[dict] = []
    for code, new_vals in by_code.items():
        item = items[code]
        before = values(item)
        after = {**before, **new_vals}
        for msg in F.item_errors(after):
            errors.append({"code": code, "field": "row", "message": f"{code}: {msg}", "kind": "error"})
        w = F.list_move_warning(before.get("list_price"), after.get("list_price")) if "list_price" in new_vals else None
        if w:
            warnings.append({"code": code, "field": "list_price", "message": f"{code}: {w}", "kind": "warning"})
        for field, new in new_vals.items():
            old = before.get(field)
            if new == old:
                continue
            status = "pending" if eff else "applied"
            if needs_second_check(cfg, field, old, new):
                status = "awaiting_check"
            plan.append((item, field, old, new, status))
    if errors:
        raise Invalid(errors=errors + warnings)
    if warnings and not confirm_warnings:
        raise Invalid("Check these changes, then confirm to save.", errors=warnings)
    if not plan:
        raise Invalid("Nothing to save: every value is as it was.", errors=[{"field": "changes", "message": "Nothing changed.", "kind": "error"}])
    v = _new_version(db, user, reason, source, len(plan))
    now = utcnow()
    waiting = []
    for item, field, old, new, status in plan:
        ch = CatalogChange(catalog_version_id=v.id, item_code=item.code, field=field, old_value=old, new_value=new, effective_from=eff, status=status,
                           reason=reason, changed_by=user.id, changed_at=now)
        db.add(ch)
        db.flush()
        if status == "applied":
            _apply(item, field, new, v, user.id, now)
            ch.applied_at, ch.applied_version_id = now, v.id
        else:
            item.pending_change_id = ch.id
            if status == "awaiting_check":
                waiting.append(ch)
    db.flush()
    when = f" from {eff:%d %b %Y}" if eff else ""
    _audit(db, user, "catalog.save", v, f"Price list version {v.version}: {len(plan)} change(s){when} — {reason}")
    if waiting:
        _ask_second_check(db, user, v, waiting)
    return v


def _apply(item: CatalogItem, field: str, new, v: CatalogVersion, uid: str | None, now) -> None:
    setattr(item, field, new)
    item.catalog_version_id, item.version_no, item.updated_by, item.updated_at = v.id, v.version, uid, now


def _ask_second_check(db: Session, user: User, v: CatalogVersion, waiting: list[CatalogChange]) -> None:
    from app.notifications.service import notify

    others = [u for u in owners(db) if u.id != user.id]
    codes = ", ".join(sorted({c.item_code for c in waiting}))
    notify(db, others, "catalog_second_check", f"Confirm price changes in version {v.version}", f"{user.name} changed {codes} by more than the second-check limit.",
           "/staff/admin/catalog?panel=checks")


def _refresh_pending_pointer(db: Session, code: str) -> None:
    item = get_item(db, code, include_retired=True)
    if item is None:
        return
    last = db.scalar(select(CatalogChange.id).where(CatalogChange.item_code == code, CatalogChange.status.in_(("pending", "awaiting_check")))
                     .order_by(CatalogChange.changed_at.desc()).limit(1))
    item.pending_change_id = last


def pending_for(db: Session, code: str | None = None) -> list[dict]:
    stmt = select(CatalogChange).where(CatalogChange.status.in_(("pending", "awaiting_check")))
    if code:
        stmt = stmt.where(CatalogChange.item_code == code)
    return [_change_out(db, c) for c in db.scalars(stmt.order_by(CatalogChange.effective_from, CatalogChange.changed_at))]


def apply_due_changes(db: Session, on: date | None = None) -> int:
    """The daily job: apply pending changes whose effective date has come, as one new catalog version. A change that
    would now break a rule (the row changed meanwhile) is not applied; the owners are told."""
    on = on or today()
    due = list(db.scalars(select(CatalogChange).where(CatalogChange.status == "pending", CatalogChange.effective_from <= on)
                          .order_by(CatalogChange.effective_from, CatalogChange.changed_at)))
    if not due:
        return 0
    now = utcnow()
    applied, failed = [], []
    by_code: dict[str, list[CatalogChange]] = defaultdict(list)
    for c in due:
        by_code[c.item_code].append(c)
    v = None
    for code, chs in by_code.items():
        item = get_item(db, code, include_retired=True)
        after = {**values(item), **{c.field: c.new_value for c in chs}} if item else {}
        if item is None or item.status != "active" or F.item_errors(after):
            failed.extend(chs)
            continue
        if v is None:
            v = _new_version(db, None, f"Changes with an effective date of {on:%d %b %Y} took effect", "scheduled", 0)
        for c in chs:
            _apply(item, c.field, c.new_value, v, c.changed_by, now)
            c.status, c.applied_at, c.applied_version_id = "applied", now, v.id
            applied.append(c)
    if v is not None:
        v.change_count = len(applied)
    for c in failed:
        c.status = "declined"
    for code in by_code:
        _refresh_pending_pointer(db, code)
    db.flush()
    if failed:
        from app.notifications.service import notify

        notify(db, owners(db), "catalog_change_failed", "Scheduled price list changes were not applied",
               f"{', '.join(sorted({c.item_code for c in failed}))}: the row changed after the change was saved, or the item was retired. Save them again if still needed.",
               "/staff/admin/catalog")
    return len(applied)


def decide_second_check(db: Session, user: User, change_ids: list[str], *, confirm: bool, note: str | None = None) -> CatalogVersion | None:
    """The other Price List Owner confirms (or declines) changes held by the second check. Confirmed changes take effect
    now, or on their effective date."""
    _require_owner(db, user)
    chs = list(db.scalars(select(CatalogChange).where(CatalogChange.id.in_(change_ids or []), CatalogChange.status == "awaiting_check")))
    if not chs:
        raise NotFound("Nothing is waiting for a second check.")
    if any(c.changed_by == user.id for c in chs):
        raise Forbidden("The other Price List Owner confirms these changes, not the person who made them.")
    now = utcnow()
    v = None
    for c in chs:
        c.confirmed_by, c.confirmed_at = user.id, now
        if not confirm:
            c.status = "declined"
            continue
        if c.effective_from and c.effective_from > today():
            c.status = "pending"
            continue
        item = get_item(db, c.item_code, include_retired=True)
        after = {**values(item), c.field: c.new_value}
        if F.item_errors(after):
            raise Invalid(errors=[{"code": c.item_code, "field": c.field, "message": f"{c.item_code}: {m}", "kind": "error"} for m in F.item_errors(after)])
        if v is None:
            v = _new_version(db, user, f"Second check confirmed{': ' + note if note else ''}", "confirmed", 0)
        _apply(item, c.field, c.new_value, v, c.changed_by, now)
        c.status, c.applied_at, c.applied_version_id = "applied", now, v.id
        v.change_count += 1
    for code in {c.item_code for c in chs}:
        _refresh_pending_pointer(db, code)
    db.flush()
    _audit(db, user, "catalog.second_check", v, f"{'Confirmed' if confirm else 'Declined'} {len(chs)} held price change(s){': ' + note if note else ''}")
    return v


# ---- items
def _defaults(data: dict) -> dict:
    billing = data.get("billing") or "one_time"
    return {"billing": billing, "basis": data.get("basis") or "$", "periods_per_year": data.get("periods_per_year", F.BILLING_PERIODS.get(billing, 1)),
            "included_quantities": {}, "applies_to": [], "remediation_of": []}


def _create(db: Session, user: User, code: str, vals: dict, v: CatalogVersion, now) -> CatalogItem:
    item = CatalogItem(code=code, catalog_version_id=v.id, version_no=v.version, is_starter=False, created_at=now, updated_at=now, updated_by=user.id,
                       status="active", **vals)
    db.add(item)
    db.add(CatalogChange(catalog_version_id=v.id, item_code=code, field="created", old_value=None, new_value=vals.get("name"), status="applied",
                         applied_at=now, applied_version_id=v.id, reason=v.reason, changed_by=user.id, changed_at=now))
    db.flush()
    return item


def _new_item_values(db: Session, data: dict, *, existing: set[str] | None = None) -> tuple[str, dict]:
    errors = []
    try:
        code = F.check_code(data.get("code"))
    except F.FieldError as exc:
        raise Invalid(errors=[{"field": "code", "message": str(exc), "kind": "error"}]) from exc
    if get_item(db, code, include_retired=True) is not None or code in (existing or set()):
        raise Invalid(errors=[{"field": "code", "message": f"{code} is already on the price list. Codes must be unique.", "kind": "error"}])
    vals: dict = {}
    for field in F.FIELDS:
        if field in data:
            try:
                vals[field] = F.parse(field, data[field])
            except F.FieldError as exc:
                errors.append({"field": field, "message": str(exc), "kind": "error"})
    if "product" not in data:
        errors.append({"field": "product", "message": "Choose a product.", "kind": "error"})
    if "name" not in data:
        errors.append({"field": "name", "message": "Give the line item a name.", "kind": "error"})
    if errors:
        raise Invalid(errors=errors)
    vals = {**_defaults(vals), **{k: v for k, v in vals.items() if v is not None or k not in ("billing", "basis", "periods_per_year")}}
    vals["price_status"], vals["sellable_status"] = "proposed", "available"  # spec §4.9: new items start Proposed and available
    errs = F.item_errors(vals)
    if errs:
        raise Invalid(errors=[{"field": "row", "message": m, "kind": "error"} for m in errs])
    return code, vals


def add_item(db: Session, user: User, data: dict, *, reason: str) -> CatalogItem:
    _require_owner(db, user)
    reason = _check_reason(reason)
    code, vals = _new_item_values(db, data)
    v = _new_version(db, user, reason, "item", 1)
    item = _create(db, user, code, vals, v, utcnow())
    _audit(db, user, "catalog.add", v, f"Added {code} {item.name} to the price list — {reason}")
    return item


def duplicate_item(db: Session, user: User, code: str, new_code: str, *, reason: str, name: str | None = None) -> CatalogItem:
    src = get_item(db, code, include_retired=True)
    if src is None:
        raise NotFound()
    data = {**values(src), "code": new_code}
    if name:
        data["name"] = name
    return add_item(db, user, data, reason=reason)


def _set_status(db: Session, user: User, code: str, status: str, reason: str) -> CatalogItem:
    _require_owner(db, user)
    reason = _check_reason(reason)
    item = get_item(db, code, include_retired=True)
    if item is None:
        raise NotFound()
    if item.status == status:
        raise Invalid(f"{code} is already {status}.")
    v = _new_version(db, user, reason, "item", 1)
    now = utcnow()
    db.add(CatalogChange(catalog_version_id=v.id, item_code=code, field="status", old_value=item.status, new_value=status, status="applied", applied_at=now,
                         applied_version_id=v.id, reason=reason, changed_by=user.id, changed_at=now))
    _apply(item, "status", status, v, user.id, now)
    db.flush()
    _audit(db, user, f"catalog.{'retire' if status == 'retired' else 'restore'}", v, f"{'Retired' if status == 'retired' else 'Restored'} {code} — {reason}")
    return item


def retire_item(db: Session, user: User, code: str, *, reason: str) -> CatalogItem:
    """Retired items can't be added to new estimates or proposals but stay on old ones. Nothing is ever deleted."""
    return _set_status(db, user, code, "retired", reason)


def restore_item(db: Session, user: User, code: str, *, reason: str) -> CatalogItem:
    return _set_status(db, user, code, "active", reason)


def _round(x: float, step: int | None) -> float:
    if not step:
        return round(x, 2)
    return math.floor(x / step + 0.5) * step


def bulk_changes(db: Session, codes: list[str], op: dict) -> list[dict]:
    """The field changes a bulk edit makes: set a field, or move prices by % or amount, rounded to $10 / $50 / $100."""
    items = items_by_codes(db, codes)
    missing = [c for c in codes if c not in items]
    if missing:
        raise Invalid(errors=[{"field": "codes", "message": f"Not on the price list: {', '.join(missing)}.", "kind": "error"}])
    kind, field = op.get("kind"), op.get("field")
    if kind == "set":
        return [{"code": c, "field": field, "value": op.get("value")} for c in codes]
    if kind not in ("percent", "amount") or field not in F.PRICE_FIELDS + ("prices",):
        raise Invalid(errors=[{"field": "kind", "message": "Choose set a field, change by %, or change by an amount.", "kind": "error"}])
    try:
        amount = float(op.get("amount"))
    except (TypeError, ValueError) as exc:
        raise Invalid(errors=[{"field": "amount", "message": "Enter a number.", "kind": "error"}]) from exc
    step = op.get("rounding")
    if step not in (None, 0, 10, 50, 100):
        raise Invalid(errors=[{"field": "rounding", "message": "Round to the nearest $10, $50 or $100.", "kind": "error"}])
    targets = F.PRICE_FIELDS if field == "prices" else (field,)
    out = []
    for c in codes:
        item = items[c]
        for f in targets:
            old = getattr(item, f)
            if old is None:
                continue
            new = old * (1 + amount / 100) if kind == "percent" else old + amount
            new = _round(new, None if item.basis == "%" else step)
            out.append({"code": c, "field": f, "value": int(new) if new == int(new) else new})
    return out


def bulk_edit(db: Session, user: User, codes: list[str], op: dict, *, reason: str, effective_from: date | None = None, confirm_warnings: bool = False) -> CatalogVersion:
    _require_owner(db, user)
    return save_batch(db, user, bulk_changes(db, codes, op), reason=reason, effective_from=effective_from, confirm_warnings=confirm_warnings, source="bulk")


# ---- history
def _change_out(db: Session, c: CatalogChange, versions: dict | None = None) -> dict:
    v = (versions or {}).get(c.catalog_version_id) or db.get(CatalogVersion, c.catalog_version_id)
    return {
        "id": c.id, "code": c.item_code, "field": c.field, "label": F.FIELD_LABELS.get(c.field, c.field), "old_value": c.old_value, "new_value": c.new_value,
        "old_display": F.display(c.field, c.old_value), "new_display": F.display(c.field, c.new_value), "reason": c.reason, "by": _name(db, c.changed_by) or "Futran Audit Platform",
        "by_id": c.changed_by, "at": c.changed_at.isoformat(), "version": v.version if v else None, "source": v.source if v else None, "status": c.status,
        "effective_from": c.effective_from.isoformat() if c.effective_from else None, "confirmed_by": _name(db, c.confirmed_by),
        "applied_at": c.applied_at.isoformat() if c.applied_at else None,
    }


def change_log(db: Session, *, code: str | None = None, user_id: str | None = None, version: int | None = None, field: str | None = None,
               since: date | None = None, q: str | None = None, limit: int | None = None) -> list[dict]:
    stmt = select(CatalogChange, CatalogVersion).join(CatalogVersion, CatalogVersion.id == CatalogChange.catalog_version_id)
    if code:
        stmt = stmt.where(CatalogChange.item_code == code)
    if user_id:
        stmt = stmt.where(CatalogChange.changed_by == user_id)
    if version is not None:
        stmt = stmt.where(CatalogVersion.version == version)
    if field:
        stmt = stmt.where(CatalogChange.field == field)
    if since:
        from datetime import datetime, time

        stmt = stmt.where(CatalogChange.changed_at >= datetime.combine(since, time.min))
    stmt = stmt.order_by(CatalogVersion.version.desc(), CatalogChange.changed_at.desc())
    rows = []
    for c, v in db.execute(stmt):
        out = _change_out(db, c, {v.id: v})
        if q and q.casefold() not in f"{out['code']} {out['label']} {out['reason']} {out['by']} {out['old_display']} {out['new_display']}".casefold():
            continue
        rows.append(out)
        if limit and len(rows) >= limit:
            break
    return rows


def history(db: Session, code: str) -> list[dict]:
    return change_log(db, code=code)


def versions(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(CatalogVersion).order_by(CatalogVersion.version.desc()).limit(limit))
    return [{"version": v.version, "saved_by": _name(db, v.saved_by) or ("Starter data" if v.source == "seed" else "Futran Audit Platform"), "saved_at": v.saved_at.isoformat(), "reason": v.reason,
             "source": v.source, "change_count": v.change_count} for v in rows]


# ---- suggestions (a task for the Price List Owners)
SUGGESTION_FIELDS = {"list_price": "List price", "low": "Low", "high": "High", "deliverables": "Deliverables", "description": "Description",
                     "sellable_status": "Sellable status", "new_item": "New item", "other": "Something else"}


def suggest(db: Session, user: User, *, item_code: str | None, field: str, suggested_value: str, reason: str) -> PriceSuggestion:
    from app.notifications.service import notify

    if field not in SUGGESTION_FIELDS:
        raise Invalid(errors=[{"field": "field", "message": "Choose what you are suggesting.", "kind": "error"}])
    if not (reason or "").strip():
        raise Invalid(errors=[{"field": "reason", "message": "Say why, so the Price List Owners can decide.", "kind": "error"}])
    if field != "new_item":
        if not item_code or get_item(db, item_code, include_retired=True) is None:
            raise Invalid(errors=[{"field": "item_code", "message": "Choose the item this is about.", "kind": "error"}])
    s = PriceSuggestion(item_code=item_code if field != "new_item" else (item_code or None), suggested_by=user.id, field=field,
                        suggested_value=(suggested_value or "").strip()[:4000], reason=reason.strip()[:2000], status="open")
    db.add(s)
    db.flush()
    what = f"{item_code} {SUGGESTION_FIELDS[field].lower()}" if field != "new_item" else "a new item"
    notify(db, [u for u in owners(db) if u.id != user.id], "price_suggestion", f"Price list suggestion from {user.name}: {what}", s.reason,
           "/staff/admin/catalog?panel=suggestions")
    from app.audit_log import service as audit

    audit.record(db, actor_id=user.id, action="catalog.suggest", organization_id=user.organization_id, object_type="PriceSuggestion", object_id=s.id,
                 summary=f"Suggested a change to {what}")
    return s


def suggestion_out(db: Session, s: PriceSuggestion) -> dict:
    return {"id": s.id, "item_code": s.item_code, "field": s.field, "field_label": SUGGESTION_FIELDS.get(s.field, s.field), "suggested_value": s.suggested_value,
            "reason": s.reason, "status": s.status, "by": _name(db, s.suggested_by), "at": s.created_at.isoformat(), "decided_by": _name(db, s.decided_by),
            "decided_at": s.decided_at.isoformat() if s.decided_at else None, "decision_note": s.decision_note}


def decide_suggestion(db: Session, user: User, sid: str, *, accept: bool, note: str | None = None) -> PriceSuggestion:
    from app.notifications.service import notify

    _require_owner(db, user)
    s = db.get(PriceSuggestion, sid)
    if s is None:
        raise NotFound()
    if s.status != "open":
        raise Conflict("This suggestion has already been decided.")
    s.status, s.decided_by, s.decided_at, s.decision_note = ("accepted" if accept else "declined"), user.id, utcnow(), (note or "").strip() or None
    db.flush()
    notify(db, [db.get(User, s.suggested_by)], "price_suggestion_decided", f"Your price list suggestion was {s.status}", s.decision_note, "/staff/admin/catalog")
    return s


# ---- packages
def package_out(db: Session, p: PackageTemplate, items: dict | None = None) -> dict:
    items = items if items is not None else items_by_codes(db, [ln["code"] for ln in p.lines or []])
    lines = []
    for ln in p.lines or []:
        it = items.get(ln["code"])
        lines.append({"code": ln["code"], "qty": ln.get("qty", 1), "name": it.name if it else None, "list_price": it.list_price if it else None,
                      "billing": it.billing if it else None, "sellable_status": it.sellable_status if it else None, "price_status": it.price_status if it else None,
                      "problem": None if it and it.status == "active" else ("Retired item" if it else "Not on the price list")})
    return {"id": p.id, "key": p.key, "name": p.name, "description": p.description, "lines": lines, "is_starter": p.is_starter,
            "updated_by": _name(db, p.updated_by), "updated_at": p.updated_at.isoformat() if p.updated_at else None}


def packages(db: Session) -> list[PackageTemplate]:
    return list(db.scalars(select(PackageTemplate).order_by(PackageTemplate.sort, PackageTemplate.name)))


def update_package(db: Session, user: User, pid: str, *, name: str | None = None, description: str | None = None, lines: list[dict] | None = None) -> PackageTemplate:
    from app.audit_log import service as audit

    p = db.get(PackageTemplate, pid)
    if p is None:
        raise NotFound()
    if name is not None:
        if not name.strip():
            raise Invalid(errors=[{"field": "name", "message": "Give the package a name.", "kind": "error"}])
        p.name = name.strip()[:80]
    if description is not None:
        p.description = description.strip() or None
    if lines is not None:
        clean, errors = [], []
        known = items_by_codes(db, [ln.get("code") for ln in lines])
        for ln in lines:
            code = ln.get("code")
            it = known.get(code)
            qty = ln.get("qty", 1)
            if it is None or it.status != "active":
                errors.append({"field": "lines", "message": f"{code} is not an active item on the price list.", "kind": "error"})
            elif it.sellable_status == "roadmap":
                errors.append({"field": "lines", "message": f"{code} is a roadmap item and can't be sold yet.", "kind": "error"})
            elif not isinstance(qty, (int, float)) or qty <= 0:
                errors.append({"field": "lines", "message": f"Give {code} a quantity of 1 or more.", "kind": "error"})
            else:
                clean.append({"code": code, "qty": int(qty) if qty == int(qty) else qty})
        if errors:
            raise Invalid(errors=errors)
        p.lines = clean
    p.updated_by, p.updated_at = user.id, utcnow()
    v = db.scalar(select(CatalogVersion).where(CatalogVersion.version == current_version(db)))
    p.catalog_version_id = v.id if v else None
    db.flush()
    audit.record(db, actor_id=user.id, action="catalog.package", organization_id=user.organization_id, object_type="PackageTemplate", object_id=p.id,
                 summary=f"Package {p.name}: {len(p.lines)} line(s)", after={"lines": p.lines})
    return p


# ---- mapping rules that point at retired or missing items (R3 owns MappingRule; this only reads it)
def rule_flags(db: Session) -> list[dict]:
    try:
        from app.scoping.models import MappingRule
    except ImportError:
        return []
    out = []
    rules = list(db.scalars(select(MappingRule)))
    codes = {getattr(r, "line_code", None) for r in rules}
    known = items_by_codes(db, [c for c in codes if c])
    for r in rules:
        if getattr(r, "active", True) is False:
            continue
        code = getattr(r, "line_code", None)
        it = known.get(code)
        if it is None or it.status != "active":
            out.append({"rule_code": getattr(r, "code", r.id), "line_code": code, "problem": "Retired item" if it else "Not on the price list"})
    return out


def run_effective_dates(db: Session, settings, now) -> int:
    """Daily job entry point (notifications.jobs): apply the price list changes whose effective date has come."""
    return apply_due_changes(db, now.date() if hasattr(now, "date") else now)


def usage(db: Session, code: str) -> dict:
    """Where an item is used now: saved estimates (latest version of each) and, once R4 lands, draft proposals."""
    from app.catalog.models import Estimate

    latest: dict[str, Estimate] = {}
    for e in db.scalars(select(Estimate)):
        if e.thread_id not in latest or e.version > latest[e.thread_id].version:
            latest[e.thread_id] = e
    estimates = sum(any(ln.get("code") == code for ln in e.lines or []) for e in latest.values())
    proposals = None
    try:
        from app.proposals.models import Proposal, ProposalLine

        proposals = db.scalar(select(func.count(func.distinct(Proposal.id))).join(ProposalLine, ProposalLine.proposal_id == Proposal.id)
                              .where(ProposalLine.catalog_code == code, Proposal.status.in_(("draft", "awaiting_approval", "approved"))))
    except Exception:  # the proposal builder is not installed yet, or its tables differ
        proposals = None
    return {"estimates": estimates, "proposals": proposals}
