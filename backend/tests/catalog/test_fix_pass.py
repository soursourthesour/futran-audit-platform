"""Review fix pass: formula-safe round trip, second check on imports, one-time discount, grid saves need base_version."""
from datetime import datetime

import pytest

from app.catalog import io as cio
from app.catalog import pricing, service
from app.core.clock import set_now
from tests.catalog.test_import_export import book
from tests.factories import login_as


@pytest.fixture(autouse=True)
def _clock():
    set_now(datetime(2026, 11, 12, 9, 0))
    yield
    set_now(None)


def test_export_reimport_keeps_text_that_starts_with_formula_characters(db, seeded, staff):
    service.save_batch(db, staff["owner"], [{"code": "A-02b", "field": "deliverables", "value": "- Inventory of every AI system\n- Findings report"},
                                            {"code": "L-01", "field": "notes", "value": "+5% from January"},
                                            {"code": "A-05", "field": "notes", "value": "'quoted on purpose"}], reason="r")
    imp = cio.preview(db, staff["owner"], "export.xlsx", cio.export_xlsx(db))
    out = cio.import_out(db, imp)
    assert out["changes"] == [] and out["errors"] == []


def test_import_respects_the_second_check(db, seeded, staff):
    service.update_settings(db, staff["owner2"], second_check=True, second_check_pct=10)
    data = book([["A-02a", "Audit", "Audit, up to 10 systems", None, "One-time", "$", 1, 12000, 18000, 18000, "Proposed"] + [None] * 8])
    imp = cio.preview(db, staff["owner"], "R2.xlsx", data)
    cio.save_import(db, staff["owner"], imp.id, reason="Load", retire_missing=False)
    assert service.get_item(db, "A-02a").list_price == 15000
    held = {(p["field"], p["status"]) for p in service.pending_for(db, "A-02a")}
    assert ("list_price", "awaiting_check") in held
    service.decide_second_check(db, staff["owner2"], [p["id"] for p in service.pending_for(db, "A-02a")], confirm=True)
    assert service.get_item(db, "A-02a").list_price == 18000


def test_one_time_discount_is_applied_to_the_totals(db, seeded):
    lines = pricing.price_lines(db, [{"code": "A-02a", "qty": 1, "edited_price": 13500}, {"code": "A-05", "qty": 3}, {"code": "A-06b", "qty": 1},
                                     {"code": "A-08a", "qty": 3}, {"code": "M-07a", "qty": 2}, {"code": "M-01a", "qty": 1}, {"code": "M-03a", "qty": 1},
                                     {"code": "M-06a", "qty": 1}])
    t = pricing.totals(lines, 10, discount_one_time_pct=20)
    assert (t["one_time"], t["one_time_discount"], t["one_time_net"]) == (39500, 7900, 31600)
    assert (t["recurring_y1"], t["discount"], t["arr"]) == (31200, 3120, 28080)
    assert t["y1_total"] == 31600 + 31200 - 3120
    assert pricing.totals(lines, 0)["one_time_discount"] == 0


def test_estimator_preview_applies_the_one_time_discount(client, db, seeded, staff):
    login_as(client, db, staff["sales"])
    r = client.post("/api/v1/sales/estimates/preview", json={"lines": [{"code": "A-02a", "qty": 1}], "terms": {"discount_one_time_pct": 20}})
    t = r.json()["totals"]
    assert (t["one_time_discount"], t["one_time_net"], t["y1_total"]) == (3000, 12000, 12000)


def test_grid_save_needs_base_version(client, db, seeded, staff):
    login_as(client, db, staff["owner"])
    r = client.post("/api/v1/catalog/save", json={"changes": [{"code": "L-01", "field": "notes", "value": "n"}], "reason": "r"})
    assert r.status_code == 422
    assert client.post("/api/v1/catalog/save", json={"changes": [{"code": "L-01", "field": "notes", "value": "n"}], "reason": "r", "base_version": 1}).status_code == 200
