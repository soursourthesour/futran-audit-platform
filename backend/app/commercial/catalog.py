"""Read access to the master price list (R1, `app.catalog`) for orders, change orders and hours-bank overage.

The catalog is the only price source (spec §4.9). It is built by another Release 2 workstream, so this module imports it
lazily and answers None when it is not installed; callers then use the prices frozen on the order or proposal line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session


@dataclass
class Item:
    code: str
    name: str = ""
    billing: str | None = None
    basis: str = "$"
    periods_per_year: int | None = None
    list_price: float | None = None
    low: float | None = None
    high: float | None = None
    deliverables: str | None = None
    engagement_type: str | None = None
    entitlement_key: str | None = None
    included_quantities: dict = field(default_factory=dict)
    sellable_status: str = "available"
    price_status: str = "approved"


def _num(v) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def parse_included(v) -> dict[str, float]:
    """Included quantities as a dict. The workbook may hold them as text ("ai_systems 50, seats 5" or "ai_systems=50")."""
    if not v:
        return {}
    if isinstance(v, dict):
        return {str(k): float(n) for k, n in v.items() if _num(n) is not None}
    out: dict[str, float] = {}
    for part in re.split(r"[,;\n]", str(v)):
        m = re.match(r"\s*([a-z_]+)\s*[:= ]\s*([0-9.]+)", part.strip().lower())
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def _view(row) -> Item:
    g = lambda *names: next((getattr(row, n) for n in names if getattr(row, n, None) is not None), None)  # noqa: E731
    return Item(
        code=row.code, name=g("name", "line_item") or "", billing=g("billing"), basis=g("basis") or "$", periods_per_year=g("periods_per_year"),
        list_price=_num(g("list", "list_price")), low=_num(g("low")), high=_num(g("high")), deliverables=g("deliverables"),
        engagement_type=g("engagement_type"), entitlement_key=g("entitlement_key"), included_quantities=parse_included(g("included_quantities")),
        sellable_status=g("sellable_status") or "available", price_status=g("price_status") or "approved",
    )


def _service():
    try:
        from app.catalog import service  # R1
    except ImportError:
        return None
    return service


def items_by_codes(db: Session, codes) -> dict[str, Item]:
    svc = _service()
    if svc is None or not codes:
        return {}
    rows = svc.items_by_codes(db, list(dict.fromkeys(codes)))
    return {c: _view(r) for c, r in (rows or {}).items() if r is not None}


def get_item(db: Session, code: str) -> Item | None:
    svc = _service()
    if svc is None:
        return None
    row = svc.get_item(db, code)
    return _view(row) if row is not None else None


def current_version(db: Session) -> int | None:
    svc = _service()
    return svc.current_version(db) if svc is not None else None


def is_one_time(billing: str | None) -> bool:
    b = (billing or "").strip().lower().replace("-", " ").replace("_", " ")
    return b.startswith("one") or b in ("once", "fixed", "per engagement", "per event")
