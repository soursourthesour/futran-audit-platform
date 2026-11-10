"""Every reader of uploaded Excel files refuses a workbook built to keep the server busy (11-10 review, P1 follow-up).

A few kilobytes can declare a sheet of a million rows, or one far-away cell; read naively, openpyxl walks every row."""
import io
import re
import time
import zipfile

import openpyxl
import pytest

from app.core.errors import Invalid


def _bomb(rows: int = 1_048_576, sheet: str = "AI systems", header=("Name", "Question")) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(list(header))
    ws.cell(row=rows, column=1, value="x")
    b = io.BytesIO()
    wb.save(b)
    zin = zipfile.ZipFile(io.BytesIO(b.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in zin.infolist():
            d = zin.read(i.filename)
            if i.filename == "xl/worksheets/sheet1.xml":
                d = re.sub(rb'<dimension ref="[^"]+"', f'<dimension ref="A1:XFD{rows}"'.encode(), d)
            zout.writestr(i, d)
    return out.getvalue()


def _fast(fn, *args):
    t = time.monotonic()
    try:
        return fn(*args)
    finally:
        assert time.monotonic() - t < 3, "the reader did not refuse the workbook quickly"


def test_register_import_refuses_a_workbook_bomb_quickly():
    from app.register.seeding import rows_from_upload

    with pytest.raises(Invalid):
        _fast(rows_from_upload, _bomb())


def test_questionnaire_upload_refuses_a_workbook_bomb_quickly():
    from app.ai.questionnaires import detect

    with pytest.raises(Invalid):
        _fast(detect, "xlsx", _bomb(sheet="Questions", header=("Question", "Answer")))


def test_copilot_text_extraction_refuses_a_workbook_bomb_quickly():
    from app.ai.text import extract_pages

    method, pages, error = _fast(extract_pages, "evidence.xlsx", _bomb(sheet="Data"))
    assert pages == [] and error


def test_ordinary_workbooks_still_read():
    from app.ai.text import extract_pages
    from app.register.seeding import rows_from_upload

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AI systems"
    ws.append(["Name", "Vendor"])
    ws.append(["Résumé screener", "Acme"])
    b = io.BytesIO()
    wb.save(b)
    assert rows_from_upload(b.getvalue())[1] == ["Résumé screener", "Acme"]
    _, pages, error = extract_pages("evidence.xlsx", b.getvalue())
    assert error is None and "Résumé screener | Acme" in pages[0]["text"]
