"""SM-14 over HTTP: the §4.9 permission table, the grid, history, change log, packages, suggestions."""
import pytest

from tests.factories import login_as

API = "/api/v1/catalog"


def as_(client, db, user):
    client.cookies.clear()
    return login_as(client, db, user)


def test_everyone_on_the_table_views_the_grid(client, db, seeded, staff):
    for who in ("owner", "admin", "chief", "sales", "manager"):
        r = as_(client, db, staff[who]).get(API)
        assert r.status_code == 200, (who, r.text)
        body = r.json()
        assert body["version"] == 1 and len(body["items"]) == 13
        assert body["can_edit"] is (who == "owner") and body["can_suggest"] is (who != "owner")
    a02b = next(i for i in body["items"] if i["code"] == "A-02b")
    assert a02b["range"] == "$28,000–45,000" and a02b["billing_label"] == "One-time" and a02b["included_text"] == "50 systems; 5 docs; 1 readout"
    assert body["counts"] == {"items": 13, "available": 11, "manual_delivery": 1, "roadmap": 1, "retired": 0}


def test_auditors_and_clients_cannot_see_prices(client, db, seeded, staff):
    for who in ("auditor", "client"):
        assert as_(client, db, staff[who]).get(API).status_code in (403, 404)
        assert client.get(f"{API}/export.xlsx").status_code in (403, 404)


def test_only_owners_edit(client, db, seeded, staff):
    body = {"changes": [{"code": "A-02a", "field": "list_price", "value": 15500}], "reason": "r"}
    for who in ("admin", "chief", "sales", "manager"):
        assert as_(client, db, staff[who]).post(f"{API}/save", json=body).status_code == 403, who
        assert client.post(f"{API}/items", json={"code": "A-15", "product": "Audit", "name": "X", "billing": "one_time", "reason": "r"}).status_code == 403
        assert client.post(f"{API}/items/A-02a/retire", json={"reason": "r"}).status_code == 403
        assert client.post(f"{API}/bulk", json={"codes": ["A-02a"], "op": {"kind": "percent", "field": "list_price", "amount": 5}, "reason": "r"}).status_code == 403
    r = as_(client, db, staff["owner"]).post(f"{API}/save", json=body)
    assert r.status_code == 200 and r.json()["version"] == 2


def test_save_returns_field_errors_and_warnings(client, db, seeded, staff):
    as_(client, db, staff["owner"])
    r = client.post(f"{API}/save", json={"changes": [{"code": "A-02a", "field": "low", "value": 99999}], "reason": "r"})
    assert r.status_code == 422 and "Low must not be above List" in r.json()["errors"][0]["message"]
    r = client.post(f"{API}/save", json={"changes": [{"code": "A-02b", "field": "list_price", "value": 45000}], "reason": "r"})
    assert r.status_code == 422 and r.json()["errors"][0]["kind"] == "warning"
    r = client.post(f"{API}/save", json={"changes": [{"code": "A-02b", "field": "list_price", "value": 45000}], "reason": "r", "confirm_warnings": True})
    assert r.status_code == 200


def test_pending_change_shows_on_the_row(client, db, seeded, staff):
    as_(client, db, staff["owner"])
    r = client.post(f"{API}/save", json={"changes": [{"code": "A-02a", "field": "list_price", "value": 16000}], "reason": "From January", "effective_from": "2099-01-01"})
    assert r.status_code == 200
    a = next(i for i in client.get(API).json()["items"] if i["code"] == "A-02a")
    assert a["list_price"] == 15000 and a["pending"][0]["new_value"] == 16000 and a["pending"][0]["effective_from"] == "2099-01-01"


def test_add_duplicate_retire_restore_history(client, db, seeded, staff):
    as_(client, db, staff["owner"])
    r = client.post(f"{API}/items", json={"code": "A-15", "product": "Audit", "name": "Board pack", "billing": "one_time", "list_price": 2000, "reason": "New"})
    assert r.status_code == 200 and r.json()["price_status"] == "proposed"
    assert client.post(f"{API}/items/A-15/duplicate", json={"new_code": "A-15b", "reason": "Copy"}).json()["code"] == "A-15b"
    assert client.post(f"{API}/items/A-15b/retire", json={"reason": "Not needed"}).json()["status"] == "retired"
    assert "A-15b" not in {i["code"] for i in client.get(API).json()["items"]}
    assert "A-15b" in {i["code"] for i in client.get(f"{API}?include_retired=true").json()["items"]}
    assert client.post(f"{API}/items/A-15b/restore", json={"reason": "Back"}).json()["status"] == "active"
    hist = client.get(f"{API}/items/A-15b/history").json()["items"]
    assert [h["field"] for h in hist] == ["status", "status", "created"]


def test_bulk_edit(client, db, seeded, staff):
    as_(client, db, staff["owner"])
    r = client.post(f"{API}/bulk", json={"codes": ["A-02a", "M-01a"], "op": {"kind": "percent", "field": "list_price", "amount": 5, "rounding": 100}, "reason": "Uplift"})
    assert r.status_code == 200, r.text
    prices = {i["code"]: i["list_price"] for i in client.get(API).json()["items"]}
    assert prices["A-02a"] == 15800 and prices["M-01a"] == 12600


def test_change_log_and_its_export(client, db, seeded, staff):
    as_(client, db, staff["owner"]).post(f"{API}/save", json={"changes": [{"code": "L-01", "field": "notes", "value": "=HYPERLINK(\"x\")"}], "reason": "Note"})
    for who in ("sales", "chief", "admin"):
        as_(client, db, staff[who])
        rows = client.get(f"{API}/changes?code=L-01").json()["items"]
        assert rows[0]["reason"] == "Note"
        r = client.get(f"{API}/changes/export.xlsx")
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    from openpyxl import load_workbook
    import io

    ws = load_workbook(io.BytesIO(r.content)).active
    vals = [c.value for row in ws.iter_rows() for c in row]
    assert "'=HYPERLINK(\"x\")" in vals and not any(isinstance(v, str) and v.startswith("=") for v in vals)


def test_suggest_a_change(client, db, seeded, staff):
    r = as_(client, db, staff["sales"]).post(f"{API}/suggestions", json={"item_code": "A-05", "field": "list_price", "suggested_value": "1750", "reason": "Market"})
    assert r.status_code == 200
    assert client.get(f"{API}/suggestions").status_code == 403  # the queue is the owners' task list
    as_(client, db, staff["owner"])
    items = client.get(f"{API}/suggestions").json()["items"]
    assert items[0]["by"] == "Sam Seller" and items[0]["status"] == "open"
    assert client.get(API).json()["open_suggestions"] == 1
    assert client.post(f"{API}/suggestions/{items[0]['id']}/decide", json={"accept": False, "note": "Hold"}).json()["status"] == "declined"
    assert as_(client, db, staff["owner"]).post(f"{API}/suggestions", json={"item_code": "A-05", "field": "list_price", "suggested_value": "1", "reason": "x"}).status_code == 403


def test_settings(client, db, seeded, staff):
    as_(client, db, staff["owner"])
    assert client.get(f"{API}/settings").json()["second_check"] is False
    assert client.put(f"{API}/settings", json={"second_check": True, "second_check_pct": 10}).json()["second_check"] is True
    assert as_(client, db, staff["admin"]).put(f"{API}/settings", json={"second_check": False}).status_code == 403


def test_packages_tab(client, db, seeded, staff):
    as_(client, db, staff["sales"])
    pk = client.get(f"{API}/packages").json()["items"]
    assert [p["name"] for p in pk] == ["Starter (LL144)", "Governed", "Agent-ready", "Custom"]
    assert client.put(f"{API}/packages/{pk[2]['id']}", json={"lines": [{"code": "AA-02", "qty": 1}]}).status_code == 403
    as_(client, db, staff["admin"])
    r = client.put(f"{API}/packages/{pk[2]['id']}", json={"lines": [{"code": "AA-02", "qty": 2}]})
    assert r.status_code == 200 and r.json()["lines"][0]["name"] == "15-point pre-deploy check and assurance letter"
    assert client.put(f"{API}/packages/{pk[2]['id']}", json={"lines": [{"code": "M-09", "qty": 1}]}).status_code == 422  # roadmap


def test_versions(client, db, seeded, staff):
    as_(client, db, staff["owner"]).post(f"{API}/save", json={"changes": [{"code": "L-01", "field": "notes", "value": "n"}], "reason": "Note"})
    v = client.get(f"{API}/versions").json()["items"]
    assert [x["version"] for x in v] == [2, 1] and v[0]["saved_by"] == "Pat President"
