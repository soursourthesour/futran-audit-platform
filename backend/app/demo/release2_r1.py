"""Release 2 R1 demo step: the price list and Estimator with something on them. The President schedules a price change
from 1 January (pending on the row), the Sales Officer suggests a change for the Price List Owners, and an estimate built
from the Governed package (A-02a edited to $13,500, as in the SM-15 design) is saved twice on an open opportunity."""
from datetime import date

from sqlalchemy import select

from app.demo.seed_demo import Demo

GOVERNED = [{"code": "A-02a", "qty": 1, "edited_price": 13500}, {"code": "A-05", "qty": 3}, {"code": "A-06b", "qty": 1}, {"code": "A-08a", "qty": 3},
            {"code": "M-07a", "qty": 2}, {"code": "M-01a", "qty": 1}, {"code": "M-03a", "qty": 1}, {"code": "M-06a", "qty": 1}]


def seed(m: Demo, ids: dict) -> dict:
    from app.catalog import service
    from app.catalog.models import CatalogChange
    from app.core.clock import today
    from app.sales.models import Opportunity

    db = m.db
    if service.current_version(db) == 0:
        from app.catalog.seed import seed_starter

        seed_starter(db)
        db.commit()
    out: dict = {}
    president = m.user("president@futran.demo")
    if not db.scalar(select(CatalogChange.id).where(CatalogChange.status == "pending").limit(1)):
        jan = date(today().year + 1, 1, 1)
        service.save_batch(db, president, [{"code": "A-02b", "field": "list_price", "value": 36500}], reason="Q1 price review: wider scope for 11–50 systems",
                           effective_from=jan)
        db.commit()
    m.as_(m.user("sales@futran.demo"))
    m.post("/catalog/suggestions", {"item_code": "A-05", "field": "list_price", "suggested_value": "1,750",
                                    "reason": "Clients with Okta and Google Workspace ask for both sources; $1,500 per source undersells the work."})
    opp = db.scalar(select(Opportunity).where(Opportunity.stage.not_in(("won", "lost"))).order_by(Opportunity.created_at).limit(1))
    if opp is not None:
        e1 = m.post("/sales/estimates", {"name": "Governed package, first pass", "opportunity_id": opp.id, "package": "governed", "lines": GOVERNED,
                                         "discount_recurring_pct": 0, "term": 1, "data_region": "us"})
        e2 = m.post("/sales/estimates", {"thread_id": e1["thread_id"], "lines": [dict(ln, qty=2) if ln["code"] == "A-05" else ln for ln in GOVERNED],
                                         "discount_recurring_pct": 5, "term": 2, "data_region": "us"})
        out["estimate"] = e2["id"]
    return out
