"""A repeal keeps its date. A future-dated repeal leaves the law in scope until that date; the daily run takes it out
of scope when the date arrives."""
from datetime import date, datetime

import pytest

from app.core import clock
from app.regmaster import changes
from app.regmaster.models import LawVersion
from tests.regmaster.test_engine import _geo, _row, master  # noqa: F401
from tests.factories import make_org
from app.regmaster.seed import find_law


@pytest.fixture(autouse=True)
def _today():
    clock.set_now(datetime(2027, 3, 1, 9, 0))
    yield
    clock.set_now(None)


def _repeal(db, on):
    reg = find_law(db, "US-NYC", "Local Law 144")
    value = {"status": "repealed"} | ({"effective_on": on} if on else {})
    pc = changes.propose(db, actor_id="u1", regulation_id=reg.id, field_path="repeal", new_value=value, summary="Repealed", origin="admin_edit", change_type="repeal")
    return changes.apply_changes(db, [pc], reviewer_id="chief")


def test_repeal_keeps_its_date(master):
    v = _repeal(master, "2027-07-01")
    assert v.status == "repealed" and v.repealed_on == date(2027, 7, 1)


def test_future_repeal_keeps_the_law_in_scope_until_then(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-NYC")
    _repeal(db, "2027-07-01")
    row = _row(db, org, "US-NYC", "Local Law 144")
    assert row.in_scope and "repealed from 1 July 2027" in row.reason_text


def test_past_repeal_takes_the_law_out(master):
    db = master
    org = make_org(db)
    _geo(db, org, "US-NYC")
    _repeal(db, "2027-01-01")
    row = _row(db, org, "US-NYC", "Local Law 144")
    assert not row.in_scope and row.reason_text == "Repealed or lapsed"


def test_daily_run_takes_the_law_out_when_the_date_arrives(master, settings):
    from app.notifications.jobs import JOBS

    db = master
    org = make_org(db)
    _geo(db, org, "US-NYC")
    _repeal(db, "2027-07-01")
    assert _row(db, org, "US-NYC", "Local Law 144").in_scope
    for day, reruns in ((datetime(2027, 6, 30, 6, 0), 0), (datetime(2027, 7, 1, 6, 0), 1)):
        clock.set_now(day)
        assert JOBS["repeal_dates"](db, settings, day) == reruns
    assert not _row(db, org, "US-NYC", "Local Law 144").in_scope


def test_a_copied_version_keeps_the_repeal_date(master):
    db = master
    v = _repeal(db, "2027-07-01")
    from app.regmaster.versioning import clone_version

    assert clone_version(db, v).repealed_on == date(2027, 7, 1)


def test_repeal_date_must_be_a_date(master):
    from app.core.errors import Invalid

    reg = find_law(master, "US-NYC", "Local Law 144")
    with pytest.raises(Invalid):
        changes.propose(master, actor_id="u1", regulation_id=reg.id, field_path="repeal", new_value={"status": "repealed", "effective_on": "soon"}, summary="Repealed", origin="admin_edit", change_type="repeal")
