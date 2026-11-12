"""Release 2 R1 demo step on top of the full demo: a pending price change, an open suggestion, a two-version estimate."""
from tests.demo.test_demo_v061 import as_user, world  # noqa: F401  (one demo world per module)


def _get(c, path):
    r = c.get(f"/api/v1{path}")
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"
    return r.json()


def test_price_list_has_starter_items_a_pending_change_and_a_suggestion(world, as_user):  # noqa: F811
    grid = _get(as_user("president@futran.demo"), "/catalog")
    assert grid["can_edit"] and grid["counts"]["items"] == 13 and grid["starter"] is True
    a02b = next(i for i in grid["items"] if i["code"] == "A-02b")
    assert a02b["list_price"] == 35000 and a02b["pending"][0]["new_value"] == 36500
    assert grid["open_suggestions"] == 1
    assert _get(as_user("chief@futran.demo"), "/catalog")["can_edit"] is False


def test_estimate_saved_twice_on_an_opportunity(world, as_user):  # noqa: F811
    e = _get(as_user("sales@futran.demo"), f"/sales/estimates/{world['ids']['estimate']}")
    assert e["version"] == 2 and [v["version"] for v in e["versions"]] == [2, 1]
    assert e["totals"]["one_time"] == 38000 and e["approvals"][0]["rule"] == "P-1"
