"""SM-14 saved batches: one reason per batch, a new catalog version per batch, validation, effective dates, history."""
from datetime import date, datetime

import pytest

from app.catalog import service
from app.catalog.models import CatalogChange, CatalogItem
from app.core.clock import set_now
from app.core.errors import Conflict, Forbidden, Invalid


@pytest.fixture(autouse=True)
def _clock():
    set_now(datetime(2026, 11, 12, 9, 0))
    yield
    set_now(None)


def save(db, user, changes, reason="Q1 2027 price review", **kw):
    return service.save_batch(db, user, changes, reason=reason, **kw)


def test_save_batch_changes_items_records_history_and_bumps_version(db, seeded, staff):
    v = save(db, staff["owner"], [{"code": "A-02b", "field": "list_price", "value": 36500},
                                  {"code": "A-02b", "field": "deliverables", "value": "New text for the client."}])
    assert v.version == 2 and v.change_count == 2 and v.source == "grid" and v.reason == "Q1 2027 price review"
    item = service.get_item(db, "A-02b")
    assert item.list_price == 36500 and item.deliverables == "New text for the client."
    assert item.updated_by == staff["owner"].id and item.catalog_version_id == v.id
    hist = {h["field"]: h for h in service.history(db, "A-02b")}
    lp = hist["list_price"]
    assert (lp["old_value"], lp["new_value"], lp["reason"], lp["by"], lp["version"]) == (35000, 36500, "Q1 2027 price review", "Pat President", 2)
    assert hist["deliverables"]["new_value"] == "New text for the client."
    assert service.current_version(db) == 2


def test_reason_is_required(db, seeded, staff):
    with pytest.raises(Invalid) as e:
        save(db, staff["owner"], [{"code": "A-02a", "field": "list_price", "value": 15500}], reason="  ")
    assert e.value.errors[0]["field"] == "reason"


def test_only_price_list_owners_edit(db, seeded, staff):
    for who in ("admin", "chief", "sales", "manager"):
        with pytest.raises(Forbidden):
            save(db, staff[who], [{"code": "A-02a", "field": "list_price", "value": 15500}])


@pytest.mark.parametrize("change,message", [
    ({"code": "A-02a", "field": "low", "value": 16000}, "Low must not be above List"),
    ({"code": "A-02a", "field": "high", "value": 14000}, "List must not be above High"),
    ({"code": "A-02a", "field": "periods_per_year", "value": 2}, "Periods per year must be 1, 4 or 12"),
    ({"code": "A-06b", "field": "price_status", "value": "approved"}, "deliverables before it can be Approved"),
    ({"code": "A-02a", "field": "billing", "value": "weekly"}, "Choose a billing"),
    ({"code": "A-02a", "field": "product", "value": "Widgets"}, "Choose a product"),
])
def test_validation_rules(db, seeded, staff, change, message):
    with pytest.raises(Invalid) as e:
        save(db, staff["owner"], [change])
    assert any(message in err["message"] for err in e.value.errors), e.value.errors
    assert service.current_version(db) == 1


def test_percent_items_stay_between_0_and_100(db, seeded, staff):
    with pytest.raises(Invalid) as e:
        save(db, staff["owner"], [{"code": "M-06a", "field": "basis", "value": "%"}])
    assert any("between 0 and 100" in err["message"] for err in e.value.errors)
    v = save(db, staff["owner"], [{"code": "M-06a", "field": "basis", "value": "%"}, {"code": "M-06a", "field": "low", "value": 5},
                                  {"code": "M-06a", "field": "list_price", "value": 10}, {"code": "M-06a", "field": "high", "value": 15}], confirm_warnings=True)
    assert v.version == 2


def test_list_move_over_25_percent_needs_confirmation(db, seeded, staff):
    with pytest.raises(Invalid) as e:
        save(db, staff["owner"], [{"code": "A-02b", "field": "list_price", "value": 45000}])
    assert e.value.errors[0]["kind"] == "warning" and "more than 25%" in e.value.errors[0]["message"]
    v = save(db, staff["owner"], [{"code": "A-02b", "field": "list_price", "value": 45000}], confirm_warnings=True)
    assert v.version == 2 and service.get_item(db, "A-02b").list_price == 45000


def test_future_effective_date_is_pending_until_the_daily_job(db, seeded, staff):
    v = save(db, staff["owner"], [{"code": "A-02a", "field": "list_price", "value": 16000}], effective_from=date(2027, 1, 1))
    item = service.get_item(db, "A-02a")
    assert item.list_price == 15000
    pend = service.pending_for(db, "A-02a")
    assert [(p["field"], p["new_value"], p["effective_from"]) for p in pend] == [("list_price", 16000, "2027-01-01")]
    assert service.apply_due_changes(db, date(2026, 12, 31)) == 0
    assert service.apply_due_changes(db, date(2027, 1, 1)) == 1
    item = service.get_item(db, "A-02a")
    assert item.list_price == 16000 and service.pending_for(db, "A-02a") == []
    assert service.current_version(db) == v.version + 1
    ch = db.query(CatalogChange).filter_by(item_code="A-02a", field="list_price").one()
    assert ch.status == "applied" and ch.applied_at is not None


def test_past_effective_date_is_refused(db, seeded, staff):
    with pytest.raises(Invalid):
        save(db, staff["owner"], [{"code": "A-02a", "field": "list_price", "value": 16000}], effective_from=date(2026, 11, 1))


def test_stale_grid_conflicts(db, seeded, staff):
    save(db, staff["owner2"], [{"code": "A-02a", "field": "list_price", "value": 15500}])
    with pytest.raises(Conflict):
        save(db, staff["owner"], [{"code": "A-02a", "field": "high", "value": 19000}], base_version=1)
    # an item nobody touched since version 1 saves fine
    assert save(db, staff["owner"], [{"code": "L-01", "field": "notes", "value": "x"}], base_version=1).version == 3


def test_code_cannot_be_edited(db, seeded, staff):
    with pytest.raises(Invalid):
        save(db, staff["owner"], [{"code": "A-02a", "field": "code", "value": "A-02z"}])


def test_add_item_rules(db, seeded, staff):
    owner = staff["owner"]
    with pytest.raises(Invalid) as e:
        service.add_item(db, owner, {"code": "bad", "product": "Audit", "name": "X", "billing": "one_time"}, reason="new")
    assert "XX-00" in e.value.errors[0]["message"]
    with pytest.raises(Invalid):
        service.add_item(db, owner, {"code": "A-02a", "product": "Audit", "name": "X", "billing": "one_time"}, reason="new")
    with pytest.raises(Invalid):
        service.add_item(db, owner, {"code": "A-15", "product": "Nope", "name": "X", "billing": "one_time"}, reason="new")
    item = service.add_item(db, owner, {"code": "A-15", "product": "Audit", "name": "Board pack", "billing": "one_time", "price_status": "approved"}, reason="new")
    assert (item.price_status, item.sellable_status, item.status, item.is_starter) == ("proposed", "available", "active", False)
    assert service.current_version(db) == 2
    assert [h["field"] for h in service.history(db, "A-15")] == ["created"]


def test_duplicate_copies_fields_under_a_new_code(db, seeded, staff):
    dup = service.duplicate_item(db, staff["owner"], "A-02b", "A-02d", reason="Tier for 51–100")
    src = service.get_item(db, "A-02b")
    assert dup.code == "A-02d" and dup.deliverables == src.deliverables and dup.list_price == src.list_price
    assert dup.price_status == "proposed" and dup.status == "active"


def test_retire_and_restore_never_delete(db, seeded, staff):
    service.retire_item(db, staff["owner"], "M-09", reason="Replaced")
    assert service.get_item(db, "M-09") is None
    assert db.query(CatalogItem).filter_by(code="M-09").one().status == "retired"
    service.restore_item(db, staff["owner"], "M-09", reason="Back")
    assert service.get_item(db, "M-09").status == "active"
    assert [h["field"] for h in service.history(db, "M-09")][:2] == ["status", "status"]
    assert service.current_version(db) == 3


def test_bulk_edit_by_percent_with_rounding(db, seeded, staff):
    v = service.bulk_edit(db, staff["owner"], ["A-02a", "A-05", "M-01a"], {"kind": "percent", "field": "list_price", "amount": 5, "rounding": 100},
                          reason="Uplift", confirm_warnings=True)
    assert v.source == "bulk"
    got = service.items_by_codes(db, ["A-02a", "A-05", "M-01a"])
    assert (got["A-02a"].list_price, got["A-05"].list_price, got["M-01a"].list_price) == (15800, 1600, 12600)


def test_bulk_edit_by_amount_and_set_field(db, seeded, staff):
    service.bulk_edit(db, staff["owner"], ["A-02a"], {"kind": "amount", "field": "high", "amount": 1000, "rounding": 50}, reason="Wider")
    assert service.get_item(db, "A-02a").high == 19000
    service.bulk_edit(db, staff["owner"], ["A-02a", "A-05"], {"kind": "set", "field": "sellable_status", "value": "roadmap"}, reason="Pause")
    assert {i.sellable_status for i in service.items_by_codes(db, ["A-02a", "A-05"]).values()} == {"roadmap"}


def test_bulk_edit_validates_every_row(db, seeded, staff):
    with pytest.raises(Invalid):  # +40% list puts A-08a's fixed price above its High
        service.bulk_edit(db, staff["owner"], ["A-08a"], {"kind": "percent", "field": "list_price", "amount": 40, "rounding": 10}, reason="x", confirm_warnings=True)


def test_change_log_filters(db, seeded, staff):
    save(db, staff["owner"], [{"code": "A-02a", "field": "list_price", "value": 15500}], reason="One")
    save(db, staff["owner2"], [{"code": "L-01", "field": "notes", "value": "n"}], reason="Two")
    rows = service.change_log(db)
    assert [r["reason"] for r in rows[:2]] == ["Two", "One"]
    assert [r["code"] for r in service.change_log(db, code="A-02a") if r["source"] != "seed"] == ["A-02a"]
    assert {r["by"] for r in service.change_log(db, user_id=staff["owner2"].id)} == {"Cara Ceo"}
    assert all(r["version"] == 2 for r in service.change_log(db, version=2))
