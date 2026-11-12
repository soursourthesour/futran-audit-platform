"""G-03: time and hours (spec B3) — weekly timesheets, hours banks, retainers, standard cost and margin."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.commercial import catalog as cat
from app.commercial.models import HoursBank, OrderLine, TimeEntry


def bank_used(db: Session, bank: HoursBank, *, upto: date | None = None) -> float:
    q = select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(TimeEntry.hours_bank_id == bank.id, TimeEntry.deleted_at.is_(None), TimeEntry.status != "returned")
    if upto is not None:
        q = q.where(TimeEntry.on_date <= upto)
    return float(db.scalar(q) or 0)


def overage_rate(db: Session, bank: HoursBank) -> float:
    """Hours beyond the bank are priced from the catalog (the bank's own code), else at the price the bank was sold at."""
    item = cat.get_item(db, bank.code)
    if item is not None and item.list_price is not None:
        return float(item.list_price)
    ln = db.get(OrderLine, bank.order_line_id) if bank.order_line_id else None
    return float(ln.unit_price) if ln else 0.0
