"""Read the three admin exports G-07 takes (spec B7): the Microsoft 365 Copilot licence and usage report, the Purview
oversharing / data risk assessment, and the SharePoint Advanced Management permission reports. CSV or Excel; Excel
through `app.core.xlsx_guard`. Headers are matched loosely; a file without the columns its kind needs is refused with
the missing columns named, before anything is stored."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.core.errors import Invalid

MAX_ROWS = 200_000
MAX_COLS = 80

# kind: (label, required {field: (display name, aliases)}, optional {field: aliases})
KINDS: dict[str, dict] = {
    "licence_usage": {
        "label": "Copilot licence and usage report",
        "source": "Microsoft 365 admin center",
        "required": {"user": ("User principal name", ("user principal name", "upn", "user", "user email", "email", "username"))},
        "optional": {
            "department": ("department", "dept", "business unit"),
            "licensed": ("has copilot license", "has copilot licence", "copilot license", "copilot licence", "assigned products", "licenses", "licences"),
            "last_activity": ("last activity date of microsoft 365 copilot (utc)", "last activity date of microsoft 365 copilot", "copilot last activity date",
                              "last activity date (utc)", "last activity date", "last activity"),
            "report_date": ("report refresh date", "report date"),
        },
    },
    "purview_oversharing": {
        "label": "Purview oversharing assessment",
        "source": "Microsoft Purview (DSPM for AI)",
        "required": {
            "site": ("Site", ("site url", "site name", "site", "url", "location", "site address")),
            "sensitive_items": ("Sensitive items", ("sensitive items", "sensitive item count", "items with sensitive information", "sensitive files",
                                                    "sensitive info items", "sensitive information items")),
        },
        "optional": {
            "url": ("site url", "url", "site address"),
            "name": ("site name", "site title", "title"),
            "owner": ("site owner", "owner", "primary admin", "owners"),
            "sharing": ("sharing scope", "sharing", "access scope", "shared with", "sharing link type", "link type"),
            "label_coverage": ("label coverage", "sensitivity label coverage", "labelled items %", "labeled items %", "% labelled", "% labeled", "label coverage (%)"),
            "last_activity": ("last activity", "last activity date", "last modified", "last accessed"),
        },
    },
    "sharepoint_permissions": {
        "label": "SharePoint permission report",
        "source": "SharePoint Advanced Management",
        "required": {
            "site": ("Site", ("site url", "site name", "site", "url", "site address")),
            "sharing": ("Sharing scope", ("sharing scope", "sharing link type", "link type", "permission scope", "sharing", "access scope", "shared with")),
        },
        "optional": {
            "url": ("site url", "url", "site address"),
            "name": ("site name", "site title", "title"),
            "owner": ("site owner", "owner", "primary admin", "owners"),
            "label": ("sensitivity label", "site sensitivity label", "label"),
            "last_activity": ("last activity", "last activity date", "last modified", "last accessed"),
        },
    },
}


@dataclass
class Parsed:
    rows_read: int = 0
    rows_used: int = 0
    licences: int | None = None
    active_users: int | None = None
    usage_as_of: date | None = None
    by_department: list[dict] = field(default_factory=list)
    sites: list[dict] = field(default_factory=list)


def _norm(h) -> str:
    return " ".join(str(h or "").replace("_", " ").split()).lower()


def _text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _table(data: bytes, filename: str) -> tuple[list[str], list[list]]:
    ext = Path(filename or "").suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        from app.core import xlsx_guard

        try:
            wb = xlsx_guard.open_workbook(data, max_rows=MAX_ROWS, max_cols=MAX_COLS)
        except xlsx_guard.WorkbookTooLarge as exc:
            raise Invalid(str(exc), [{"field": "file", "message": str(exc)}]) from exc
        except Exception as exc:
            raise Invalid("This workbook could not be read.", [{"field": "file", "message": "Upload the export as CSV or Excel (.xlsx)."}]) from exc
        rows = [list(r) for r in xlsx_guard.rows(wb.worksheets[0], max_rows=MAX_ROWS, max_cols=MAX_COLS)]
        rows = [r for r in rows if any(v not in (None, "") for v in r)]
    elif ext in (".csv", ".txt", ""):
        text = _text(data)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = []
        for i, r in enumerate(csv.reader(io.StringIO(text), dialect)):
            if i > MAX_ROWS:
                raise Invalid(errors=[{"field": "file", "message": f"The file has more than {MAX_ROWS:,} rows. Split it and upload each part."}])
            if any(c.strip() for c in r):
                rows.append(r)
    else:
        raise Invalid(errors=[{"field": "file", "message": "Upload the export as CSV or Excel (.xlsx)."}])
    if not rows:
        raise Invalid(errors=[{"field": "file", "message": "The file is empty."}])
    return [_norm(h) for h in rows[0]], rows[1:]


def _find(header: list[str], aliases) -> int | None:
    for a in aliases:
        if a in header:
            return header.index(a)
    return None


def columns(kind: str, header: list[str]) -> dict[str, int | None]:
    spec = KINDS[kind]
    out, missing = {}, []
    for f, (display, aliases) in spec["required"].items():
        out[f] = _find(header, aliases)
        if out[f] is None:
            missing.append(display)
    if missing:
        raise Invalid(f"This file is not a {spec['label'].lower()}: it is missing {', '.join(missing)}.",
                      [{"field": "file", "message": f"Missing column{'s' if len(missing) > 1 else ''}: {', '.join(missing)}. Export the {spec['label'].lower()} from {spec['source']} and upload it unchanged."}])
    for f, aliases in spec["optional"].items():
        out[f] = _find(header, aliases)
    return out


def _cell(row: list, i: int | None):
    if i is None or i >= len(row):
        return None
    v = row[i]
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def parse_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s[:11].strip(), fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_int(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = re.sub(r"[,\s]", "", str(v))
    return int(float(s)) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def parse_pct(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    pct = s.endswith("%")
    s = s.rstrip("%").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    if not pct and 0 < x <= 1 and "." in s:  # a fraction, as some exports give it
        x *= 100
    return round(max(0.0, min(100.0, x)), 1)


def sharing_of(v) -> str:
    s = _norm(v)
    if not s:
        return "unknown"
    if "except external" in s or "eeeu" in s:
        return "everyone_except_external"
    if "anyone" in s or "anonymous" in s:
        return "anyone_link"
    if "everyone" in s:
        return "everyone"
    if "external" in s or "guest" in s:
        return "external"
    if "specific" in s or "direct" in s:
        return "specific"
    if "org" in s or "company" in s or "people in" in s or "tenant" in s:
        return "org"
    return "unknown"


def _truthy(v) -> bool:
    s = _norm(v)
    return s in ("yes", "true", "1", "y") or "copilot" in s


def site_key(url: str | None, name: str | None) -> str:
    if url:
        return url.strip().lower().rstrip("/")[:400]
    return ("name:" + _norm(name))[:400]


def parse(kind: str, data: bytes, filename: str, today: date) -> Parsed:
    header, rows = _table(data, filename)
    col = columns(kind, header)
    out = Parsed(rows_read=len(rows))
    if kind == "licence_usage":
        report = None
        depts: dict[str, dict] = {}
        users = 0
        active = 0
        lasts = []
        for r in rows:
            if not _cell(r, col["user"]):
                continue
            report = report or parse_date(_cell(r, col["report_date"]))
            if col["licensed"] is not None and not _truthy(_cell(r, col["licensed"])):
                continue
            users += 1
            lasts.append((r, parse_date(_cell(r, col["last_activity"]))))
        as_of = report or today
        for r, last in lasts:
            is_active = last is not None and 0 <= (as_of - last).days <= 28
            active += is_active
            d = str(_cell(r, col["department"]) or "Not given")
            row = depts.setdefault(d, {"department": d, "licences": 0, "active": 0})
            row["licences"] += 1
            row["active"] += int(is_active)
        out.rows_used, out.licences, out.usage_as_of = users, users, as_of
        out.active_users = active if col["last_activity"] is not None else None
        out.by_department = sorted(depts.values(), key=lambda x: (-x["licences"], x["department"]))
        return out
    for r in rows:
        raw = _cell(r, col["site"])
        if raw is None:
            continue
        url = _cell(r, col.get("url")) if col.get("url") is not None else (str(raw) if str(raw).lower().startswith("http") else None)
        name = _cell(r, col.get("name")) if col.get("name") is not None else None
        name = str(name or raw)
        site = {"key": site_key(str(url) if url else None, name), "name": name[:300], "url": str(url)[:600] if url else None,
                "owner": (str(_cell(r, col["owner"]))[:200] if _cell(r, col.get("owner")) else None), "last_activity": parse_date(_cell(r, col.get("last_activity")))}
        if kind == "purview_oversharing":
            site["sensitive_items"] = parse_int(_cell(r, col["sensitive_items"]))
            site["label_coverage"] = parse_pct(_cell(r, col.get("label_coverage")))
            if col.get("sharing") is not None:
                site["sharing"] = sharing_of(_cell(r, col["sharing"]))
        else:
            site["sharing"] = sharing_of(_cell(r, col["sharing"]))
        out.sites.append(site)
    out.rows_used = len(out.sites)
    return out


BROAD = {"everyone", "everyone_except_external", "org", "anyone_link", "external"}


def risk_of(sharing: str | None, sensitive: int | None, coverage: float | None) -> str:
    """High: broadly shared sensitive content with little labelling. Medium: broad sharing, or labelling under 80%.
    Low: nothing sensitive, or sensitive content shared narrowly and labelled."""
    if sensitive == 0:
        return "low"
    broad = (sharing or "unknown") in BROAD
    if sensitive is None:  # a permission report alone: broad sharing needs a look, nothing more is known
        return "medium" if broad else "low"
    if broad and (coverage is None or coverage < 50):
        return "high"
    if broad or (coverage is not None and coverage < 80):
        return "medium"
    return "low"
