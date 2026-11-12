"""The commercial package reads the price list (R1) through app.commercial.catalog."""
from app.commercial import catalog as cat


def test_reads_price_list_rows(db):
    from app.catalog.models import CatalogItem

    db.add(CatalogItem(code="M-01a", product="Monitor", name="Monitor, up to 10 systems", billing="annual", periods_per_year=1, low=10000, list_price=12000,
                       high=15000, included_quantities={"systems": 10}, status="active"))
    db.add(CatalogItem(code="A-05", product="Audit", name="Shadow AI discovery sweep", billing="one_time", list_price=1500, status="retired"))
    db.commit()
    items = cat.items_by_codes(db, ["M-01a", "A-05", "Z-99"])
    assert set(items) == {"M-01a", "A-05"}  # retired rows stay readable for old orders
    m = items["M-01a"]
    assert m.list_price == 12000 and m.included_quantities == {"systems": 10} and not cat.is_one_time(m.billing)
    assert cat.is_one_time(items["A-05"].billing)
    assert cat.get_item(db, "A-05") is None and cat.get_item(db, "M-01a").name == "Monitor, up to 10 systems"
