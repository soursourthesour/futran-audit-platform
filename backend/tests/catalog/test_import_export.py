"""Excel export (formula-safe, re-importable) and import with a preview of adds, changes and retirements (spec §4.9)."""
import io

import pytest
from openpyxl import Workbook, load_workbook

from app.catalog import io as cio
from app.catalog import service
from app.core.errors import Conflict, Forbidden, Invalid

HEAD = ["Code", "Product", "Line item", "Pricing unit", "Billing", "Basis", "Periods/yr", "Low", "List", "High", "Price status", "Notes",
        "Deliverables", "Sellable status", "Delivery mode", "Platform feature / release", "Included quantities", "Engagement type", "Entitlement key"]


def book(rows, title="Master Price List", head=HEAD, preamble=0):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for _ in range(preamble):
        ws.append(["Futran master price list R2"])
    ws.append(head)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_export_has_every_column_and_is_formula_safe(db, seeded, staff):
    service.save_batch(db, staff["owner"], [{"code": "L-01", "field": "notes", "value": "=cmd|' /C calc'!A0"}], reason="r")
    ws = load_workbook(io.BytesIO(cio.export_xlsx(db)))["Master Price List"]
    header = [c.value for c in ws[1]]
    assert header[:19] == HEAD
    rows = {r[0]: r for r in ws.iter_rows(min_row=2, values_only=True)}
    assert rows["L-01"][header.index("Notes")] == "'=cmd|' /C calc'!A0"
    assert rows["A-02b"][header.index("List")] == 35000 and rows["A-02b"][header.index("Included quantities")] == "50 systems; 5 docs; 1 readout"
    assert rows["M-03a"][header.index("Billing")] == "Quarterly" and rows["A-05"][header.index("Sellable status")] == "Manual delivery"


def test_exported_workbook_reimports_with_nothing_to_change(db, seeded, staff):
    imp = cio.preview(db, staff["owner"], "export.xlsx", cio.export_xlsx(db))
    out = cio.import_out(db, imp)
    assert (out["adds"], out["changes"], out["retirements"], out["errors"]) == ([], [], [], []) and out["can_save"] is False


def test_preview_shows_adds_changes_and_retirements_before_saving(db, seeded, staff):
    data = book([
        ["A-02a", "Audit", "Audit, up to 10 systems", None, "One-time", "$", 1, 12000, 15500, 18000, "Proposed", None, "Same text", "Available", None, None, None, "initial_assessment", None],
        ["A-14", "Audit", "Annual re-audit", None, "Annual", "%", 1, 50, 60, 70, "Proposed", None, None, "Available", None, None, None, None, None],
    ], preamble=2)
    imp = cio.preview(db, staff["owner"], "R2.xlsx", data)
    out = cio.import_out(db, imp)
    assert [a["code"] for a in out["adds"]] == ["A-14"]
    ch = {(c["code"], c["field"]): c for c in out["changes"]}
    assert ch[("A-02a", "list_price")]["old_value"] == 15000 and ch[("A-02a", "list_price")]["new_value"] == 15500
    assert ("A-02a", "deliverables") in ch
    assert {r["code"] for r in out["retirements"]} == {"A-02b", "A-05", "L-01", "L-09", "M-01a", "M-09", "AA-02", "A-06b", "A-08a", "M-07a", "M-03a", "M-06a"}
    assert service.get_item(db, "A-02a").list_price == 15000  # nothing saved by a preview
    assert cio.import_out(db, imp, retire_missing=False)["retirements"] == []

    v, d = cio.save_import(db, staff["owner"], imp.id, reason="Load R2 workbook", retire_missing=False)
    assert v.source == "import" and v.change_count == len(d["adds"]) + len(d["changes"])
    assert service.get_item(db, "A-02a").list_price == 15500 and service.get_item(db, "A-02a").is_starter is False
    a14 = service.get_item(db, "A-14")
    assert a14.basis == "%" and a14.billing == "annual" and a14.price_status == "proposed"
    assert service.history(db, "A-02a")[0]["reason"] == "Load R2 workbook"
    with pytest.raises(Conflict):
        cio.save_import(db, staff["owner"], imp.id, reason="again")


def test_row_errors_block_the_save(db, seeded, staff):
    data = book([["bad code", "Audit", "X", None, "One-time", "$", 1, 1, 2, 3, "Proposed"] + [None] * 8,
                 ["A-20", "Audit", "Y", None, "One-time", "$", 2, 1, 2, 3, "Proposed"] + [None] * 8,
                 ["A-21", "Audit", "Z", None, "One-time", "$", 1, 5, 2, 3, "Approved"] + [None] * 8])
    imp = cio.preview(db, staff["owner"], "x.xlsx", data)
    out = cio.import_out(db, imp, retire_missing=False)
    msgs = " ".join(e["message"] for e in out["errors"])
    assert "XX-00" in msgs and "Periods per year" in msgs and "Low must not be above List" in msgs and "deliverables before it can be Approved" in msgs
    assert out["can_save"] is False
    with pytest.raises(Invalid):
        cio.save_import(db, staff["owner"], imp.id, reason="r", retire_missing=False)


def test_stale_preview_is_refused(db, seeded, staff):
    imp = cio.preview(db, staff["owner"], "e.xlsx", cio.export_xlsx(db))
    service.save_batch(db, staff["owner2"], [{"code": "L-01", "field": "notes", "value": "n"}], reason="r")
    with pytest.raises(Conflict):
        cio.save_import(db, staff["owner"], imp.id, reason="r")


def test_unreadable_files_and_wrong_sheets(db, seeded, staff):
    with pytest.raises(Invalid):
        cio.preview(db, staff["owner"], "x.xlsx", b"not a workbook")
    with pytest.raises(Invalid) as e:
        cio.preview(db, staff["owner"], "x.xlsx", book([["x"]], head=["Something", "Else"]))
    assert "Code and List" in e.value.errors[0]["message"]


def test_only_owners_import(db, seeded, staff):
    with pytest.raises(Forbidden):
        cio.preview(db, staff["admin"], "e.xlsx", cio.export_xlsx(db))


def test_import_over_http(client, db, seeded, staff):
    from tests.factories import login_as

    login_as(client, db, staff["owner"])
    data = book([["A-02a", "Audit", "Audit, up to 10 systems", None, "One-time", "$", 1, 12000, 15500, 18000, "Proposed"] + [None] * 8])
    r = client.post("/api/v1/catalog/import", files={"file": ("R2.xlsx", data, cio.XLSX)})
    assert r.status_code == 200, r.text
    p = r.json()
    assert len(p["changes"]) >= 1 and len(p["retirements"]) == 12
    r = client.post(f"/api/v1/catalog/imports/{p['id']}/save", json={"reason": "Load", "retire_missing": False})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] >= 1 and r.json()["retired"] == 0
