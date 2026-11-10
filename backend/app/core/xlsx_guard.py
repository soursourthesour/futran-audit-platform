"""Open uploaded Excel workbooks safely.

A workbook of a few kilobytes can declare a sheet of a million rows, or hold one far-away cell, and openpyxl will
walk (or build) every row up to it; a zip of shared strings can unpack to gigabytes. Every reader of an uploaded
.xlsx opens it here, checks the declared size before reading, and reads rows with explicit bounds.
(The People import has its own reader with the same limits: app/tenancy/csv_import.read_workbook.)"""
from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator

MAX_UNPACKED_MB = 50
MAX_SHEETS = 250


class WorkbookTooLarge(ValueError):
    """The workbook is larger than an upload of this kind can hold. The message is safe to show to the user."""


def _check_zip(data: bytes) -> None:
    try:
        members = zipfile.ZipFile(io.BytesIO(data)).infolist()
    except zipfile.BadZipFile:
        return  # not a workbook; openpyxl reports it as unreadable
    if sum(m.file_size for m in members) > MAX_UNPACKED_MB * 1024 * 1024:
        raise WorkbookTooLarge(f"This workbook unpacks to more than {MAX_UNPACKED_MB} MB. Copy the rows you need into a new workbook and upload that.")
    if sum(1 for m in members if m.filename.startswith("xl/worksheets/") and m.filename.endswith(".xml")) > MAX_SHEETS:
        raise WorkbookTooLarge(f"This workbook has more than {MAX_SHEETS} sheets.")


def open_workbook(data: bytes, *, max_rows: int, max_cols: int, read_only: bool = True, data_only: bool = True):
    """Load the workbook after the size checks, and refuse it if any sheet declares more rows or columns than allowed.
    Raises WorkbookTooLarge; any other exception means the file is not a readable workbook."""
    from openpyxl import load_workbook

    _check_zip(data)
    wb = load_workbook(io.BytesIO(data), read_only=read_only, data_only=data_only)
    for ws in wb.worksheets:
        if (ws.max_row or 0) > max_rows:
            raise WorkbookTooLarge(f"Sheet '{ws.title}' has more than {max_rows:,} rows. Delete the empty rows below your data, or split it into smaller files.")
        if (ws.max_column or 0) > max_cols:
            raise WorkbookTooLarge(f"Sheet '{ws.title}' has more than {max_cols} columns. Delete the empty columns to the right of your data.")
    return wb


def rows(ws, *, max_rows: int, max_cols: int) -> Iterator[tuple]:
    """Cell values row by row, never past max_rows or max_cols, even when the sheet declares no size. Rows are as wide
    as the sheet says it is (within the limit), so an ordinary file reads exactly as before."""
    last_row = min(ws.max_row or max_rows, max_rows)
    last_col = min(ws.max_column or max_cols, max_cols)
    yield from ws.iter_rows(min_row=1, max_row=last_row, max_col=last_col, values_only=True)
