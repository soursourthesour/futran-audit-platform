"""Expense and CASB/proxy CSV uploads (spec §21 F2). Files are read in memory and not kept: only the aggregate per AI
product × department is stored (and, for expenses, the cardholders behind a paid subscription, for named-user checks).
Headers are matched loosely, so most expense systems' and proxies' exports load without editing."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from app.connectors import vendors
from app.connectors.signals import Observation, Signal, aggregate
from app.core.errors import Invalid

MAX_ROWS = 500_000

EXPENSE_TEXT = ("description", "merchant", "merchant name", "vendor", "payee", "memo", "transaction description", "details")
PERSON_EMAIL = ("email", "employee email", "user email", "cardholder email", "e-mail")
PERSON_NAME = ("employee", "employee name", "cardholder", "cardholder name", "name", "user name", "submitter")
DEPARTMENT = ("department", "dept", "cost center", "cost centre", "business unit", "team", "group")
DOMAIN = ("domain", "host", "hostname", "destination", "destination host", "destination_host", "url", "site", "dest host", "server name", "sni")
USER = ("user", "username", "user name", "user email", "email", "source user", "src user")
REQUESTS = ("requests", "count", "hits", "events", "sessions", "transactions")


@dataclass
class Parsed:
    rows_read: int
    rows_matched: int
    observations: list[Observation]


def _text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _reader(data: bytes) -> tuple[list[str], csv.reader]:
    text = _text(data)
    if not text.strip():
        raise Invalid(errors=[{"field": "file", "message": "The file is empty."}])
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = csv.reader(io.StringIO(text), dialect)
    header = next(rows, None) or []
    return [" ".join(h.replace("_", " ").split()).lower() for h in header], rows


def _col(header: list[str], names: tuple[str, ...]) -> int | None:
    norm = {n.replace("_", " ") for n in names}
    for i, h in enumerate(header):
        if h in norm:
            return i
    return None


def _cell(row: list[str], i: int | None) -> str:
    return row[i].strip() if i is not None and i < len(row) else ""


def parse_expense(data: bytes) -> Parsed:
    header, rows = _reader(data)
    text_cols = [i for i in (_col(header, (n,)) for n in EXPENSE_TEXT) if i is not None]
    if not text_cols:
        raise Invalid(errors=[{"field": "file", "message": "The file needs a description or merchant column, for example “Description” or “Merchant”."}])
    email_i, name_i, dept_i = _col(header, PERSON_EMAIL), _col(header, PERSON_NAME), _col(header, DEPARTMENT)
    signals, n, matched = [], 0, 0
    for row in rows:
        if not any(c.strip() for c in row):
            continue
        n += 1
        if n > MAX_ROWS:
            raise Invalid(errors=[{"field": "file", "message": f"The file has more than {MAX_ROWS:,} rows. Split it by month and upload each part."}])
        v = vendors.match_expense(" ".join(_cell(row, i) for i in text_cols))
        if v is None:
            continue
        matched += 1
        email, name = _cell(row, email_i).lower(), _cell(row, name_i)
        signals.append(Signal(v.key, "expense", _cell(row, dept_i) or None, person=email or name or None, person_name=name or None))
    return Parsed(n, matched, aggregate(signals, keep_people=True))


def parse_casb(data: bytes) -> Parsed:
    header, rows = _reader(data)
    dom_i = _col(header, DOMAIN)
    if dom_i is None:
        raise Invalid(errors=[{"field": "file", "message": "The file needs a domain or URL column, for example “Destination host” or “URL”."}])
    user_i, dept_i, req_i = _col(header, USER), _col(header, DEPARTMENT), _col(header, REQUESTS)
    signals, n, matched = [], 0, 0
    for row in rows:
        if not any(c.strip() for c in row):
            continue
        n += 1
        if n > MAX_ROWS:
            raise Invalid(errors=[{"field": "file", "message": f"The file has more than {MAX_ROWS:,} rows. Export it aggregated by user and domain, or split it."}])
        v = vendors.match_domain(_cell(row, dom_i))
        if v is None:
            continue
        matched += 1
        try:
            weight = int(float(_cell(row, req_i) or 1))
        except ValueError:
            weight = 1
        # the person is used only to count distinct users here; aggregate(keep_people=False) drops it
        signals.append(Signal(v.key, "traffic", _cell(row, dept_i) or None, person=_cell(row, user_i) or None, weight=weight))
    return Parsed(n, matched, aggregate(signals, keep_people=False))
