"""Review of workstream P (11-03 fixes, C2–C6): oversized workbooks, formula-safe templates, department moves through
roles, the company-wide sheet, and invitations only after a successful commit."""
import io
import re
import time
import zipfile

import openpyxl

from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.tenancy.test_people_import_1103 import _send


def _bomb(rows: int, cols: str = "XFD") -> bytes:
    """A small workbook whose sheet declares a huge size and has one far-away cell."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Finance"
    ws.append(["Full name", "Work email", "AI compliance role"])
    ws.cell(row=rows, column=1, value="x")
    b = io.BytesIO()
    wb.save(b)
    zin = zipfile.ZipFile(io.BytesIO(b.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in zin.infolist():
            d = zin.read(i.filename)
            if i.filename == "xl/worksheets/sheet1.xml":
                d = re.sub(rb'<dimension ref="[^"]+"', f'<dimension ref="A1:{cols}{rows}"'.encode(), d)
            zout.writestr(i, d)
    return out.getvalue()


def _undeclared_bomb(rows: int) -> bytes:
    """The same, with the size declaration removed, so only the reader's own bound protects it."""
    data = _bomb(rows)
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in zin.infolist():
            d = zin.read(i.filename)
            if i.filename == "xl/worksheets/sheet1.xml":
                d = re.sub(rb'<dimension ref="[^"]+"/>', b"", d)
            zout.writestr(i, d)
    return out.getvalue()


def _inflated(member_mb: int) -> bytes:
    """A valid workbook plus a highly compressible member that unpacks to many megabytes."""
    wb = openpyxl.Workbook()
    wb.active.append(["Full name", "Work email", "AI compliance role"])
    b = io.BytesIO()
    wb.save(b)
    zin = zipfile.ZipFile(io.BytesIO(b.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in zin.infolist():
            zout.writestr(i, zin.read(i.filename))
        zout.writestr("xl/media/padding.bin", b"\0" * (member_mb * 1024 * 1024))
    return out.getvalue()


# ---- P1: oversized workbooks are refused quickly
def test_workbook_declaring_a_million_rows_is_refused_fast(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    data = _bomb(1048576)
    assert len(data) < 20_000
    for path in ("import/preview", "import"):
        t = time.monotonic()
        r = _send(client, cid, path, data, "people.xlsx")
        assert time.monotonic() - t < 2, path
        assert r.status_code == 422, r.text
        assert "rows" in r.json()["detail"]


def test_workbook_declaring_too_many_columns_is_refused(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    t = time.monotonic()
    r = _send(client, cid, "import/preview", _bomb(10, cols="CZ"), "people.xlsx")
    assert time.monotonic() - t < 2
    assert r.status_code == 422 and "columns" in r.json()["detail"]


def test_undeclared_far_away_row_is_bounded(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    t = time.monotonic()
    r = _send(client, cid, "import/preview", _undeclared_bomb(1048576), "people.xlsx")
    assert time.monotonic() - t < 2
    assert r.status_code == 200 and not r.json()["ready"]
    assert any("rows" in x["message"] for x in r.json()["errors"])


def test_workbook_that_unpacks_too_large_is_refused(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    data = _inflated(60)
    assert len(data) < 1_000_000
    t = time.monotonic()
    r = _send(client, cid, "import/preview", data, "people.xlsx")
    assert time.monotonic() - t < 2
    assert r.status_code == 422 and "MB" in r.json()["detail"]


def test_workbook_with_too_many_sheets_is_refused(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    wb = openpyxl.Workbook()
    for i in range(300):
        wb.create_sheet(f"S{i}")
    b = io.BytesIO()
    wb.save(b)
    r = _send(client, cid, "import/preview", b.getvalue(), "people.xlsx")
    assert r.status_code == 422 and "sheets" in r.json()["detail"]


def test_blank_rows_count_toward_the_row_limit():
    """A sheet with no declared size and one cell just past the scan limit stops at the limit instead of scanning on."""
    from app.tenancy.csv_import import MAX_ROWS, ROW_SCAN_LIMIT, read_workbook

    data = _undeclared_bomb(ROW_SCAN_LIMIT + 50)
    errors: list[dict] = []
    tables = read_workbook(data, errors)
    assert errors and str(MAX_ROWS) in errors[0]["message"]
    assert all(n <= ROW_SCAN_LIMIT for t in tables for n, _ in t.rows)
