"""Line values and totals for estimates and proposals (spec §4.6, §4.9). Pure functions over line dicts, so the
Estimator (SM-15) and the Proposal builder (SM-09) price lines the same way.

Year-1 value = unit price used × qty × periods per year (the Quote Builder rule). A % item is its percentage of the
year-1 value of the $ lines it applies to (its `applies_to` codes or products; empty means every $ line), times qty.
Totals: one-time; recurring year 1; discount (discount % on recurring); year-1 total; annual recurring after year 1
(recurring at the discounted rate)."""
from sqlalchemy.orm import Session

from app.catalog.fields import BILLING

MANUAL_ASSUMPTION = "Delivered by Futran consultants until the platform feature ships."


def _r(x: float) -> float:
    x = round(x + 0.0, 2)
    return int(x) if x == int(x) else x


def _matches(line: dict, targets: list[str]) -> bool:
    return not targets or line.get("code") in targets or line.get("product") in targets


def compute(lines: list[dict]) -> list[dict]:
    """Fill `line_value` (and `recurring`) on each line in place; returns the list. Needs code, basis, billing, qty,
    periods_per_year, unit_price_used, and for % lines applies_to/product."""
    for ln in lines:
        ln["recurring"] = (ln.get("billing") or "one_time") != "one_time"
        if ln.get("basis") != "%":
            ln["line_value"] = _r((ln.get("unit_price_used") or 0) * (ln.get("qty") or 0) * (ln.get("periods_per_year") or 0))
    dollar = [ln for ln in lines if ln.get("basis") != "%"]
    for ln in lines:
        if ln.get("basis") == "%":
            base = sum(d["line_value"] for d in dollar if _matches(d, ln.get("applies_to") or []))
            ln["percent_of"] = _r(base)
            ln["line_value"] = _r(base * (ln.get("unit_price_used") or 0) / 100 * (ln.get("qty") or 0))
    return lines


def totals(lines: list[dict], discount_recurring_pct: float | None) -> dict:
    if any("line_value" not in ln for ln in lines):
        compute(lines)
    one_time = sum(ln["line_value"] for ln in lines if not ln.get("recurring", (ln.get("billing") or "one_time") != "one_time") and not ln.get("excluded"))
    recurring = sum(ln["line_value"] for ln in lines if ln.get("recurring", (ln.get("billing") or "one_time") != "one_time") and not ln.get("excluded"))
    discount = recurring * (discount_recurring_pct or 0) / 100
    return {"one_time": _r(one_time), "recurring_y1": _r(recurring), "discount": _r(discount), "y1_total": _r(one_time + recurring - discount),
            "arr": _r(recurring - discount)}


def billing_label(item_or_line) -> str:
    get = item_or_line.get if isinstance(item_or_line, dict) else (lambda k, d=None: getattr(item_or_line, k, d))
    billing, unit, ppy = get("billing"), get("pricing_unit"), get("periods_per_year")
    label = BILLING.get(billing, billing or "")
    if billing in ("quarterly", "monthly") and ppy:
        label = f"{label} × {ppy}"
    return f"{label} · {unit}" if unit else label


def price_line(item, raw: dict, catalog_version: int | None = None) -> dict:
    """One line from its catalog item and what the rep typed: qty, edited_price (None = at list), description and
    deliverables overrides. The master is never changed."""
    qty = raw.get("qty", 1)
    edited = raw.get("edited_price")
    lst = item.list_price
    used = edited if edited is not None else lst
    is_edited = edited is not None and edited != lst
    ln = {
        "code": item.code, "name": item.name, "product": item.product, "description": raw.get("description") or item.description,
        "description_override": raw.get("description") or None, "catalog_description": item.description,
        "deliverables": raw.get("deliverables_override") or item.deliverables, "deliverables_override": raw.get("deliverables_override") or None,
        "catalog_deliverables": item.deliverables, "qty": qty, "list_price": lst, "low": item.low, "high": item.high,
        "edited_price": edited if is_edited else None, "unit_price_used": used, "edited": is_edited, "billing": item.billing,
        "billing_label": billing_label(item), "basis": item.basis, "periods_per_year": item.periods_per_year, "pricing_unit": item.pricing_unit,
        "price_status": item.price_status, "sellable_status": item.sellable_status, "item_status": item.status, "applies_to": list(item.applies_to or []),
        "assumption": _assumption(item), "catalog_version": catalog_version, "edited_by": raw.get("edited_by") if is_edited else None,
        "edited_at": raw.get("edited_at") if is_edited else None, "fixed": item.low is not None and item.low == item.high == lst,
    }
    if ln["edited"] and lst is not None:
        ln["unit_difference"] = _r(used - lst)
        ln["value_difference"] = _r((used - lst) * qty * (item.periods_per_year if item.basis != "%" else 1))
    else:
        ln["unit_difference"] = ln["value_difference"] = 0
    return ln


def _assumption(item) -> str | None:
    if item.sellable_status != "manual_delivery":
        return None
    for line in reversed((item.deliverables or "").splitlines()):
        if line.strip().lower().startswith("delivered by futran consultants"):
            return line.strip()
    return MANUAL_ASSUMPTION


def price_lines(db: Session, raw_lines: list[dict]) -> list[dict]:
    """Price raw lines [{code, qty, edited_price, description, deliverables_override}] against the current master."""
    from app.catalog.service import current_version, items_by_codes

    items = items_by_codes(db, [r.get("code") for r in raw_lines])
    v = current_version(db)
    out = [price_line(items[r["code"]], r, v) for r in raw_lines if r.get("code") in items]
    return compute(out)
