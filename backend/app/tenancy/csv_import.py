"""Reading the client department and user lists (spec §12; 11-03 review C4–C6).

A file is one CSV table or an XLSX workbook of tables (a "Departments" sheet and one sheet of users per department).
Columns are found by name, so the old CSV headers (first_name, last_name, email, job_title, department, role, location;
department, head_name, head_email, headcount) still read. Every bad row gets its own error with its sheet and row number.
Checks that need the database (existing people, departments, scope) are made by app.tenancy.people_import."""
import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field

from app.policy.roles import CSV_ROLE_NAMES, ROLE_LABELS
from app.tenancy.job_levels import parse_job_level

USER_HEADER = ["Full name", "Work email", "Department", "Job title", "Job level", "AI compliance role"]
DEPARTMENT_HEADER = ["Department", "Parent department", "Head of department", "Headcount"]
DEPARTMENT_ROLES = {"dept_compliance_lead", "contributor"}
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
EXAMPLE_DOMAINS = {"example.com", "example.org", "example.net"}
MAX_ROWS = 5000
ROW_SCAN_LIMIT = MAX_ROWS + 1000  # rows read across a workbook, blank ones included
MAX_COLUMNS = 50
MAX_SHEETS = 250
MAX_UNPACKED_MB = 50
ROLE_KEYS = set(CSV_ROLE_NAMES.values())
UNREADABLE = "The file could not be read. Save it as CSV (comma delimited) or as an Excel workbook (.xlsx) from the template and try again."

# Column name (normalised) -> field. The first name in each list is the one the templates use.
USER_COLUMNS = {
    "name": ["full name", "name"], "first_name": ["first name"], "last_name": ["last name"],
    "email": ["work email", "email", "email address"], "department": ["department"], "job_title": ["job title", "title"],
    "job_level": ["job level", "level"], "role": ["ai compliance role", "ai compliance roles", "role", "roles"], "location": ["location"],
}
DEPARTMENT_COLUMNS = {
    "department": ["department", "department name"], "parent": ["parent department", "parent"],
    "head": ["head of department", "department head", "head"], "head_name": ["head name"], "head_email": ["head email"],
    "headcount": ["headcount", "head count"],
}


@dataclass
class Table:
    """One CSV file or one worksheet: the header row and the data rows with their row numbers in the file."""
    sheet: str | None
    header: list[str]
    rows: list[tuple[int, list[str]]]


@dataclass
class CsvResult:
    rows_ok: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"rows_ok": self.rows_ok, "errors": self.errors, "warnings": self.warnings}


def issue(sheet: str | None, row: int | None, fld: str, message: str) -> dict:
    out = {"row": row, "field": fld, "message": message}
    if sheet is not None:
        out = {"sheet": sheet, **out}
    return out


def key(name: str) -> str:
    """Names that differ only in spacing or case are the same."""
    return " ".join(str(name or "").split()).casefold()


_key = key


def _header_name(h) -> str:
    h = re.sub(r"\(.*?\)", "", str(h or "")).replace("_", " ").replace("*", "")
    return " ".join(h.split()).casefold()


def columns(header: list[str], spec: dict[str, list[str]]) -> dict[str, int]:
    """Field -> column index, by column name; the first matching column wins."""
    names = [_header_name(h) for h in header]
    out = {}
    for f, aliases in spec.items():
        for a in aliases:
            if a in names:
                out[f] = names.index(a)
                break
    return out


def is_user_table(t: Table) -> bool:
    return "email" in columns(t.header, USER_COLUMNS)


def is_department_table(t: Table) -> bool:
    return not is_user_table(t) and "department" in columns(t.header, DEPARTMENT_COLUMNS)


# ---- reading files
def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    return str(v).strip()


def read_csv(text: str, errors: list[dict]) -> list[Table]:
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    try:
        first = next(reader)
    except csv.Error:
        errors.append(issue(None, 1, "file", UNREADABLE))
        return []
    except StopIteration:
        errors.append(issue(None, 1, "file", "The file is empty."))
        return []
    rows: list[tuple[int, list[str]]] = []
    n = 1
    try:
        for n, raw in enumerate(reader, start=2):
            if not any(c.strip() for c in raw):
                continue
            if len(rows) >= MAX_ROWS:
                errors.append(issue(None, n, "file", f"Only the first {MAX_ROWS} rows can be imported at once."))
                break
            rows.append((n, [c.strip() for c in raw]))
    except csv.Error:
        errors.insert(0, issue(None, n + 1, "file", UNREADABLE))
        return []
    return [Table(None, [c.strip() for c in first], rows)]


class FileRefused(Exception):
    """A workbook too large to read safely; refused before reading it."""


def _workbook_size_check(data: bytes) -> None:
    import zipfile

    try:
        members = zipfile.ZipFile(io.BytesIO(data)).infolist()
    except Exception:  # not a zip: openpyxl reports it as unreadable
        return
    if sum(m.file_size for m in members) > MAX_UNPACKED_MB * 1024 * 1024:
        raise FileRefused(f"This workbook unpacks to more than {MAX_UNPACKED_MB} MB. Copy your rows into the template and upload that.")
    sheets = sum(1 for m in members if m.filename.startswith("xl/worksheets/") and m.filename.endswith(".xml"))
    if sheets > MAX_SHEETS:
        raise FileRefused(f"This workbook has more than {MAX_SHEETS} sheets. Upload at most {MAX_SHEETS} sheets at a time.")


def read_workbook(data: bytes, errors: list[dict]) -> list[Table]:
    """Read every sheet but Instructions. Refuses (FileRefused) a workbook that unpacks too large, has too many sheets,
    or has a sheet declaring more rows or columns than an upload can hold. Every row read, blank or not, counts toward
    ROW_SCAN_LIMIT, so a sheet with one far-away cell cannot keep the reader busy."""
    import openpyxl

    _workbook_size_check(data)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # not a workbook, or a damaged one
        errors.append(issue(None, None, "file", UNREADABLE))
        return []
    tables, total, scanned = [], 0, 0
    try:
        if len(wb.worksheets) > MAX_SHEETS:
            raise FileRefused(f"This workbook has more than {MAX_SHEETS} sheets. Upload at most {MAX_SHEETS} sheets at a time.")
        for ws in wb.worksheets:
            if key(ws.title) == "instructions":
                continue
            if (ws.max_row or 0) > ROW_SCAN_LIMIT:
                raise FileRefused(f"Sheet '{ws.title}' has more than {ROW_SCAN_LIMIT} rows. Up to {MAX_ROWS} people can be imported at once; delete the empty rows below your list, or split it into several files.")
            if (ws.max_column or 0) > MAX_COLUMNS:
                raise FileRefused(f"Sheet '{ws.title}' has more than {MAX_COLUMNS} columns. Keep only the template's columns and upload it again.")
            header, rows = None, []
            budget = ROW_SCAN_LIMIT - scanned
            if budget <= 0:
                errors.append(issue(ws.title, None, "file", f"Only the first {MAX_ROWS} rows can be imported at once."))
                break
            n = 0
            for n, values in enumerate(ws.iter_rows(min_row=1, max_row=budget + 1, max_col=MAX_COLUMNS, values_only=True), start=1):
                if n > budget:
                    errors.append(issue(ws.title, n, "file", f"Only the first {MAX_ROWS} rows can be imported at once."))
                    total = MAX_ROWS + 1
                    break
                cells = [_cell(v) for v in values]
                if not any(cells):
                    continue
                if header is None:
                    header = cells
                    continue
                total += 1
                if total > MAX_ROWS:
                    errors.append(issue(ws.title, n, "file", f"Only the first {MAX_ROWS} rows can be imported at once."))
                    break
                rows.append((n, cells))
            scanned += min(n, budget)
            if header is not None:
                tables.append(Table(ws.title, header, rows))
            if total > MAX_ROWS:
                break
    finally:
        wb.close()
    return tables


def read_file(filename: str, data: bytes, errors: list[dict]) -> list[Table]:
    if data[:2] == b"PK" or (filename or "").lower().endswith((".xlsx", ".xlsm")):
        return read_workbook(data, errors)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            errors.append(issue(None, 1, "file", UNREADABLE))
            return []
    return read_csv(text, errors)


def _values(t: Table, cols: dict[str, int], raw: list[str]) -> dict[str, str]:
    return {f: (raw[i].strip() if i < len(raw) else "") for f, i in cols.items()}


def _too_long(sheet, n, row: dict, limits: dict[str, tuple[str, int]]) -> list[dict]:
    return [issue(sheet, n, f, f"{label} must be {lim} characters or fewer.") for f, (label, lim) in limits.items() if len(row.get(f) or "") > lim]


def _unused(t: Table, cols: dict[str, int], warnings: list[dict]) -> None:
    used = set(cols.values())
    extra = [h for i, h in enumerate(t.header) if i not in used and h]
    if extra:
        warnings.append(issue(t.sheet, 1, "header", f"Not read: {', '.join(extra)}. Only the template's columns are imported."))


# ---- departments
def parse_departments(t: Table, result: CsvResult) -> None:
    cols = columns(t.header, DEPARTMENT_COLUMNS)
    if "department" not in cols:
        result.errors.append(issue(t.sheet, 1, "header", f"The first row must name the columns: {', '.join(DEPARTMENT_HEADER)}. Download the template and copy your rows into it."))
        return
    _unused(t, cols, result.warnings)
    seen = {key(r["department"]) for r in result.rows_ok}
    for n, raw in t.rows:
        row = _values(t, cols, raw)
        errs = []
        name = " ".join(row.get("department", "").split())
        if not name:
            errs.append(issue(t.sheet, n, "department", "Department name is required."))
        elif key(name) in seen:
            errs.append(issue(t.sheet, n, "department", f"Department '{row['department']}' appears more than once in this file."))
        errs += _too_long(t.sheet, n, row, {"department": ("Department name", 120), "parent": ("Parent department", 120), "head": ("Head of department", 254),
                                             "head_name": ("Head name", 120), "head_email": ("Head email", 254)})
        if row.get("head_email") and not EMAIL.match(row["head_email"]):
            errs.append(issue(t.sheet, n, "head_email", f"Email '{row['head_email']}' is not a valid email address."))
        headcount = None
        hc = row.get("headcount", "")
        if hc:
            if hc.isascii() and hc.isdecimal() and len(hc) < 8:
                headcount = int(hc)
            else:
                errs.append(issue(t.sheet, n, "headcount", "Headcount must be a whole number."))
        if errs:
            result.errors += errs
            continue
        seen.add(key(name))
        out = {"row": n, "department": name, "head_name": row.get("head_name") or None, "head_email": (row.get("head_email") or "").lower() or None, "headcount": headcount}
        if t.sheet is not None:
            out["sheet"] = t.sheet
        if "parent" in cols:
            out["parent"] = " ".join(row["parent"].split()) or None
        if "head" in cols:
            out["head"] = " ".join(row["head"].split()) or None
        result.rows_ok.append(out)


def parse_department_csv(text: str) -> CsvResult:
    r = CsvResult()
    for t in read_csv(text, r.errors):
        parse_departments(t, r)
    return r


# ---- users
def _roles(cell: str) -> tuple[list[str], list[str]]:
    """Several AI compliance roles may share one cell, separated by semicolons."""
    good, bad = [], []
    for part in [p for p in re.split(r"[;\n]", cell) if p.strip()]:
        role = CSV_ROLE_NAMES.get(key(part))
        if role is None and key(part).replace(" ", "_") in ROLE_KEYS:  # the stored key, such as dept_compliance_lead
            role = key(part).replace(" ", "_")
        if role:
            good.append(role)
        else:
            bad.append(part.strip())
    return list(dict.fromkeys(good)), bad


def parse_users(t: Table, result: CsvResult, departments: list[str] | None = None, sheet_department: str | None = None, seen: set[str] | None = None) -> None:
    """Rows of a user table. `departments`, when given, is the list a department must be in; `sheet_department` fills a
    blank Department cell (a department's own sheet, or the department chosen for the upload)."""
    cols = columns(t.header, USER_COLUMNS)
    has_name = "name" in cols or {"first_name", "last_name"} <= cols.keys()
    missing = [label for label, ok in (("Full name", has_name), ("Work email", "email" in cols), ("AI compliance role", "role" in cols)) if not ok]
    if missing:
        result.errors.append(issue(t.sheet, 1, "header", f"The first row must name the columns: {', '.join(USER_HEADER)}. Missing: {', '.join(missing)}. Download the template and copy your rows into it."))
        return
    _unused(t, cols, result.warnings)
    by_name = {key(d): d for d in (departments or [])}
    seen = seen if seen is not None else set()
    for n, raw in t.rows:
        row = _values(t, cols, raw)
        errs = []
        first, last = " ".join(row.get("first_name", "").split()), " ".join(row.get("last_name", "").split())
        name = " ".join(row.get("name", "").split()) or " ".join(x for x in (first, last) if x)
        if "name" in cols and not name:
            errs.append(issue(t.sheet, n, "name", "Full name is required."))
        elif "name" not in cols:
            for f, label, v in (("first_name", "First name", first), ("last_name", "Last name", last)):
                if not v:
                    errs.append(issue(t.sheet, n, f, f"{label} is required."))
        email = row.get("email", "").lower()
        if not email:
            errs.append(issue(t.sheet, n, "email", "Email is required."))
        elif not EMAIL.match(email):
            errs.append(issue(t.sheet, n, "email", f"Email '{row['email']}' is not a valid email address."))
        elif email.rsplit("@", 1)[1] in EXAMPLE_DOMAINS:
            errs.append(issue(t.sheet, n, "email", f"{row['email']} is one of the template's example rows. Delete it or replace it with a real person."))
        elif email in seen:
            errs.append(issue(t.sheet, n, "email", "Email appears more than once in this file."))
        errs += _too_long(t.sheet, n, row | {"name": name}, {"name": ("Full name", 160), "first_name": ("First name", 80), "last_name": ("Last name", 80), "email": ("Email", 254),
                                                             "job_title": ("Job title", 160), "location": ("Location", 160)})
        roles, bad = _roles(row.get("role", ""))
        if bad:
            errs.append(issue(t.sheet, n, "role", f"AI compliance role '{bad[0]}' is not recognised."))
        elif not roles:
            errs.append(issue(t.sheet, n, "role", "AI compliance role is required."))
        level = None
        try:
            level = parse_job_level(row.get("job_level"))
        except ValueError as exc:
            errs.append(issue(t.sheet, n, "job_level", str(exc)))
        given = " ".join(row.get("department", "").split()) or sheet_department
        dept = given
        if given and departments is not None:
            dept = by_name.get(key(given))
            if dept is None:
                errs.append(issue(t.sheet, n, "department", f"Department '{given}' is not in the department list."))
        if not given and DEPARTMENT_ROLES & set(roles):
            errs.append(issue(t.sheet, n, "department", f"A {ROLE_LABELS[next(r for r in roles if r in DEPARTMENT_ROLES)]} needs a department."))
        if email:
            seen.add(email)
        if errs:
            result.errors += errs
            continue
        parts = name.split(" ", 1)
        out = {"row": n, "name": name, "first_name": first or parts[0], "last_name": last or (parts[1] if len(parts) > 1 else ""), "email": email,
               "job_title": row.get("job_title") or None, "job_level": level, "department": dept or None, "role": roles[0], "roles": roles,
               "location": row.get("location") or None, "department_given": bool(row.get("department"))}
        if t.sheet is not None:
            out["sheet"] = t.sheet
        result.rows_ok.append(out)


def parse_user_csv(text: str, departments: list[str]) -> CsvResult:
    r = CsvResult()
    for t in read_csv(text, r.errors):
        parse_users(t, r, departments)
    return r
