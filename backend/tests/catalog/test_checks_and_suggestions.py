"""Optional second check (off by default), "Suggest a change" as a task for the Price List Owners, the daily job."""
from datetime import date, datetime

import pytest

from app.catalog import service
from app.core.clock import set_now
from app.core.errors import Forbidden, Invalid
from app.notifications.models import Notification


@pytest.fixture(autouse=True)
def _clock():
    set_now(datetime(2026, 11, 12, 9, 0))
    yield
    set_now(None)


def test_second_check_is_off_by_default(db, seeded, staff):
    assert service.settings(db).second_check is False
    service.save_batch(db, staff["owner"], [{"code": "A-02a", "field": "list_price", "value": 17000}], reason="r")
    assert service.get_item(db, "A-02a").list_price == 17000


def test_second_check_holds_big_price_changes_for_the_other_owner(db, seeded, staff):
    service.update_settings(db, staff["owner"], second_check=True, second_check_pct=10)
    service.save_batch(db, staff["owner"], [{"code": "A-02a", "field": "list_price", "value": 17000},
                                            {"code": "A-02a", "field": "notes", "value": "small"}], reason="Review")
    item = service.get_item(db, "A-02a")
    assert item.list_price == 15000 and item.notes == "small"
    held = service.pending_for(db, "A-02a")
    assert [(h["field"], h["status"]) for h in held] == [("list_price", "awaiting_check")]
    assert db.query(Notification).filter_by(user_id=staff["owner2"].id, kind="catalog_second_check").count() == 1
    with pytest.raises(Forbidden):
        service.decide_second_check(db, staff["owner"], [held[0]["id"]], confirm=True)
    v = service.decide_second_check(db, staff["owner2"], [held[0]["id"]], confirm=True)
    assert service.get_item(db, "A-02a").list_price == 17000 and v.source == "confirmed"
    assert service.history(db, "A-02a")[0]["confirmed_by"] == "Cara Ceo"


def test_second_check_decline(db, seeded, staff):
    service.update_settings(db, staff["owner2"], second_check=True, second_check_pct=5)
    service.save_batch(db, staff["owner"], [{"code": "L-01", "field": "high", "value": 13000}], reason="r")
    hid = service.pending_for(db, "L-01")[0]["id"]
    service.decide_second_check(db, staff["owner2"], [hid], confirm=False, note="Not now")
    assert service.get_item(db, "L-01").high == 12000 and service.pending_for(db, "L-01") == []


def test_only_owners_change_settings(db, seeded, staff):
    with pytest.raises(Forbidden):
        service.update_settings(db, staff["admin"], second_check=True)


def test_suggestion_goes_to_owners_and_is_decided(db, seeded, staff):
    s = service.suggest(db, staff["sales"], item_code="A-05", field="list_price", suggested_value="1,750", reason="Clients expect more sources")
    for o in ("owner", "owner2"):
        assert db.query(Notification).filter_by(user_id=staff[o].id, kind="price_suggestion").count() == 1
    with pytest.raises(Forbidden):
        service.decide_suggestion(db, staff["admin"], s.id, accept=True)
    service.decide_suggestion(db, staff["owner"], s.id, accept=True, note="Will apply in Q1")
    assert s.status == "accepted"
    assert db.query(Notification).filter_by(user_id=staff["sales"].id, kind="price_suggestion_decided").count() == 1


def test_suggestion_needs_a_reason_and_an_item(db, seeded, staff):
    with pytest.raises(Invalid):
        service.suggest(db, staff["sales"], item_code="A-05", field="list_price", suggested_value="1", reason=" ")
    with pytest.raises(Invalid):
        service.suggest(db, staff["sales"], item_code="Z-99", field="list_price", suggested_value="1", reason="x")
    assert service.suggest(db, staff["chief"], item_code=None, field="new_item", suggested_value="A-15 Board pack", reason="Asked for").status == "open"


def test_daily_job_is_registered_and_applies_due_changes(db, seeded, staff, settings):
    from app.notifications.jobs import JOBS

    assert "catalog_effective_dates" in JOBS
    service.save_batch(db, staff["owner"], [{"code": "M-01a", "field": "list_price", "value": 12500}], reason="r", effective_from=date(2027, 1, 1))
    assert JOBS["catalog_effective_dates"](db, settings, datetime(2027, 1, 1, 10)) == 1
    assert service.get_item(db, "M-01a").list_price == 12500


def test_scheduled_change_that_now_breaks_a_rule_is_not_applied(db, seeded, staff):
    service.save_batch(db, staff["owner"], [{"code": "A-02a", "field": "list_price", "value": 17500}], reason="r", effective_from=date(2027, 1, 1))
    service.save_batch(db, staff["owner"], [{"code": "A-02a", "field": "high", "value": 17000}], reason="r2")
    assert service.apply_due_changes(db, date(2027, 1, 1)) == 0
    assert service.get_item(db, "A-02a").list_price == 15000
    assert db.query(Notification).filter_by(kind="catalog_change_failed").count() == 2
