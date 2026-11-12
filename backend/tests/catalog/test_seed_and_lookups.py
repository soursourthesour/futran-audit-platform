"""Starter items and packages exactly as the SM-14/SM-15 designs show them; the lookups other workstreams call."""
from app.catalog import service
from app.catalog.models import CatalogItem, CatalogVersion, PackageTemplate
from app.catalog.seed import STARTER_ITEMS, seed_starter


def test_seed_loads_the_design_items_once(db, seeded):
    items = {i.code: i for i in db.query(CatalogItem)}
    assert set(items) == {"A-02a", "A-02b", "A-05", "L-01", "L-09", "M-01a", "M-09", "AA-02", "A-06b", "A-08a", "M-07a", "M-03a", "M-06a"}
    assert all(i.is_starter for i in items.values())
    a = items["A-02a"]
    assert (a.low, a.list_price, a.high, a.price_status, a.sellable_status, a.billing) == (12000, 15000, 18000, "proposed", "available", "one_time")
    b = items["A-02b"]
    assert (b.low, b.list_price, b.high, b.price_status) == (28000, 35000, 45000, "approved")
    assert "AI Governix" not in b.deliverables and "Typical duration: 6–10 weeks." in b.deliverables
    assert b.included_quantities == {"systems": 50, "docs": 5, "readout": 1}
    assert items["A-05"].sellable_status == "manual_delivery" and items["A-05"].pricing_unit == "per source"
    assert items["M-09"].sellable_status == "roadmap"
    m3 = items["M-03a"]
    assert (m3.billing, m3.periods_per_year, m3.low, m3.list_price, m3.high) == ("quarterly", 4, 4200, 4200, 4200)
    assert items["A-08a"].low == items["A-08a"].high == 2500
    assert service.current_version(db) == 1
    v = db.query(CatalogVersion).one()
    assert v.source == "seed" and v.change_count == len(STARTER_ITEMS)
    assert seed_starter(db) == "already loaded"
    assert db.query(CatalogItem).count() == 13


def test_seed_loads_four_packages(db, seeded):
    pk = {p.key: p for p in db.query(PackageTemplate)}
    assert [pk[k].name for k in ("starter", "governed", "agent_ready", "custom")] == ["Starter (LL144)", "Governed", "Agent-ready", "Custom"]
    assert pk["governed"].lines == [{"code": "A-02a", "qty": 1}, {"code": "A-05", "qty": 3}, {"code": "A-06b", "qty": 1}, {"code": "A-08a", "qty": 3},
                                    {"code": "M-07a", "qty": 2}, {"code": "M-01a", "qty": 1}, {"code": "M-03a", "qty": 1}, {"code": "M-06a", "qty": 1}]
    assert pk["starter"].lines == [{"code": "L-01", "qty": 1}]
    assert pk["custom"].lines == []


def test_get_item_hides_retired_unless_asked(db, seeded):
    item = service.get_item(db, "M-09")
    assert item is not None and item.name == "Trust Center"
    item.status = "retired"
    db.flush()
    assert service.get_item(db, "M-09") is None
    assert service.get_item(db, "M-09", include_retired=True).code == "M-09"
    assert service.get_item(db, "Z-99") is None


def test_items_by_codes(db, seeded):
    got = service.items_by_codes(db, ["A-02a", "L-01", "Z-99"])
    assert set(got) == {"A-02a", "L-01"}
    assert got["L-01"].name == "LL144 Readiness Assessment"
