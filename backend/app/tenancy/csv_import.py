"""Client department and user CSV parsing (spec §12). Every bad row gets its own error; good rows import."""
import csv
import io
import re
from dataclasses import dataclass, field

from app.policy.roles import CSV_ROLE_NAMES, ROLE_LABELS

USER_HEADER = ["first_name", "last_name", "email", "job_title", "department", "role", "location"]
DEPARTMENT_HEADER = ["department", "head_name", "head_email", "headcount"]
DEPARTMENT_ROLES = {"dept_compliance_lead", "contributor"}
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
MAX_ROWS = 5000


@dataclass
class CsvResult:
    rows_ok: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"rows_ok": self.rows_ok, "errors": self.errors}


def _rows(text: str, header: list[str], result: CsvResult) -> list[tuple[int, dict]]:
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    try:
        first = next(reader)
    except StopIteration:
        result.errors.append({"row": 1, "field": "file", "message": "The file is empty."})
        return []
    got = [h.strip().lower() for h in first]
    if got[: len(header)] != header:
        result.errors.append({"row": 1, "field": "header", "message": f"The first row must be: {','.join(header)}. Download the template and copy your rows into it."})
        return []
    out = []
    for n, raw in enumerate(reader, start=2):
        if not any(c.strip() for c in raw):
            continue
        if len(out) >= MAX_ROWS:
            result.errors.append({"row": n, "field": "file", "message": f"Only the first {MAX_ROWS} rows can be imported at once."})
            break
        out.append((n, {h: (raw[i].strip() if i < len(raw) else "") for i, h in enumerate(header)}))
    return out


def parse_department_csv(text: str) -> CsvResult:
    r = CsvResult()
    seen: set[str] = set()
    for n, row in _rows(text, DEPARTMENT_HEADER, r):
        errs = []
        name = row["department"]
        if not name:
            errs.append(("department", "Department name is required."))
        elif name.casefold() in seen:
            errs.append(("department", f"Department '{name}' appears more than once in this file."))
        if row["head_email"] and not EMAIL.match(row["head_email"]):
            errs.append(("head_email", f"Email '{row['head_email']}' is not a valid email address."))
        headcount = None
        if row["headcount"]:
            try:
                headcount = int(row["headcount"])
                if headcount < 0:
                    raise ValueError
            except ValueError:
                errs.append(("headcount", "Headcount must be a whole number."))
        if errs:
            r.errors += [{"row": n, "field": f, "message": m} for f, m in errs]
            continue
        seen.add(name.casefold())
        r.rows_ok.append({"department": name, "head_name": row["head_name"] or None, "head_email": row["head_email"].lower() or None, "headcount": headcount})
    return r


def parse_user_csv(text: str, departments: list[str]) -> CsvResult:
    r = CsvResult()
    by_name = {d.casefold(): d for d in departments}
    seen: set[str] = set()
    for n, row in _rows(text, USER_HEADER, r):
        errs = []
        for f, label in (("first_name", "First name"), ("last_name", "Last name"), ("email", "Email")):
            if not row[f]:
                errs.append((f, f"{label} is required."))
        email = row["email"].lower()
        if email and not EMAIL.match(email):
            errs.append(("email", f"Email '{row['email']}' is not a valid email address."))
        elif email in seen:
            errs.append(("email", "Email appears more than once in this file."))
        role = CSV_ROLE_NAMES.get(" ".join(row["role"].split()).casefold())
        if role is None:
            errs.append(("role", f"Role '{row['role']}' is not recognised." if row["role"] else "Role is required."))
        dept = None
        if row["department"]:
            dept = by_name.get(row["department"].casefold())
            if dept is None:
                errs.append(("department", f"Department '{row['department']}' is not in the department list."))
        elif role in DEPARTMENT_ROLES:
            errs.append(("department", f"A {ROLE_LABELS[role]} needs a department."))
        if email:
            seen.add(email)
        if errs:
            r.errors += [{"row": n, "field": f, "message": m} for f, m in errs]
            continue
        r.rows_ok.append({
            "first_name": row["first_name"], "last_name": row["last_name"], "email": email, "job_title": row["job_title"] or None,
            "department": dept, "role": role, "location": row["location"] or None,
        })
    return r
