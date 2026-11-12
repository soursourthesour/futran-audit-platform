"""Manual discovery import (Release 2 B5, screen G-05): the bridge until the Phase 3 connectors (F2).

A Futran auditor on an engagement, or the Client Admin from Integrations, uploads a standard admin export. The platform
reads it (CSV through the same reader as the F2 uploads; Excel through `app.core.xlsx_guard`), maps its columns to the
fields the export type needs (a guess from the headings, or a saved preset), shows a preview, and on import turns the
rows into `DiscoveredTool`s with `signal = "manual_import"` — the same entity, and the same confirm/dismiss flow, as F2,
so a connector can replace the import later without changing the data.

- Each export type writes to its own connector row (type "mi_<export type>", status "imported"), so a later import of
  the same export updates its tools as a connector re-sync would.
- Names are matched to AI products with the Futran AI vendor dictionary (ai_vendors.yaml). Rows that are not in the
  dictionary but look like AI tools ("AI", "GPT", "Copilot", "agent" ... as a word) are listed as unmatched; the
  auditor can name the product by hand. Agents from a Gemini Enterprise list are tools of their own (they feed G-09).
- Each import is an evidence item (v0.6.1 §9.6) with SHA-256. Expense and proxy/CASB exports hold personal spending and
  browsing data the F2 privacy rule never keeps, so for those the evidence item is a summary of the AI rows only and the
  import records the SHA-256 of the file as uploaded (`source_sha256`).
- Findings (`discovery_finding`): Copilot licences found (X-04), agents found (AA/AW), undeclared paid AI tools
  (M-07/M-08 follow-up) and an EU-scoped high-risk tool (X-03). Each is listed on the import at once and opens its
  opportunity through `sales.service.open_from_trigger` when one of its tools is confirmed (the finding is final).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.connectors import vendors
from app.connectors.csvparse import DEPARTMENT, DOMAIN, EXPENSE_TEXT, MAX_ROWS, PERSON_EMAIL, PERSON_NAME, REQUESTS, USER, _text
from app.connectors.models import Connector, ConnectorRun, DiscoveredTool, DiscoveryImport, ImportMappingPreset
from app.connectors.signals import Observation
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Invalid, NotFound
from app.tenancy.models import Organization, User

MAX_COLS = 200
PREVIEW_ROWS = 20
SIGNAL = "manual_import"
AI_WORDS = re.compile(r"(?<![a-z0-9])(ai|gpt|llm|llms|copilot|chatbot|genai|gen ai|agent|agents|assistant)(?![a-z0-9])")
NOT_ACTIVE = {"", "never", "none", "-", "n/a", "na", "no activity"}


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    required: bool = False
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExportType:
    key: str
    label: str
    source: str
    parsed_into: str
    fields: tuple[Field, ...]
    account_type: str = "unknown"  # what a confirmed tool is recorded as in the AI inventory
    summary_only: bool = False  # keep a summary of the AI rows as evidence, not the file
    keep_people: bool = True  # names behind a tool for Tier 2-3 named-user checks (never for browsing data)

    @property
    def connector_type(self) -> str:
        return f"mi_{self.key}"


_USER = ("user principal name", "upn", "user", "username", "user name", "email", "user email", "e-mail", "email address", "mail")
_COUNT = ("users", "user count", "number of users", "assigned users", "active users", "total users", "count")
_APP = ("application name", "app name", "application", "app", "display name", "name", "client name", "app display name", "service principal name")
EXPORT_TYPES: dict[str, ExportType] = {t.key: t for t in (
    ExportType("copilot_usage", "Copilot licence and usage report", "Microsoft 365 admin center", "Copilot licences, active users by department",
               (Field("user", "User", True, _USER), Field("department", "Department", False, DEPARTMENT),
                Field("licence", "Licence or products assigned", False, ("products assigned", "assigned products", "licenses", "license", "licence", "licences", "sku", "product")),
                Field("last_activity", "Last activity date", False, ("last activity date (utc)", "last activity date", "last activity", "copilot last activity date",
                                                                     "last activity date of microsoft 365 copilot (utc)"))),
               account_type="enterprise"),
    ExportType("entra_apps", "Enterprise applications and consents", "Microsoft Entra ID", "AI apps with sign-in or consent",
               (Field("app", "Application", True, _APP), Field("users", "Number of users", False, _COUNT), Field("user", "User", False, _USER + ("consented by",)),
                Field("department", "Department", False, DEPARTMENT), Field("consent", "Consent or permission type", False, ("consent type", "permission type", "permissions", "scope", "scopes"))),
               account_type="enterprise"),
    ExportType("google_apps", "Third-party app access", "Google Admin console", "AI apps with OAuth access",
               (Field("app", "App", True, _APP), Field("users", "Number of users", False, _COUNT), Field("user", "User", False, _USER),
                Field("department", "Department or organizational unit", False, DEPARTMENT + ("org unit", "organizational unit", "organisational unit", "ou")),
                Field("scopes", "Access or scopes", False, ("scopes", "access", "services", "api access", "access type"))),
               account_type="unknown"),
    ExportType("gemini_usage", "Gemini usage report", "Google Admin console", "Gemini active users by app",
               (Field("user", "User", False, _USER), Field("department", "Department or organizational unit", False, DEPARTMENT + ("org unit", "organizational unit", "ou")),
                Field("app", "Gemini app", False, ("app", "application", "product", "surface", "gemini app", "service")), Field("users", "Active users", False, _COUNT)),
               account_type="enterprise"),
    ExportType("gemini_agents", "Gemini Enterprise apps and agents", "Google Cloud console", "Agents (feeds agent assurance)",
               (Field("agent", "Agent or app name", True, ("agent name", "agent", "app name", "display name", "name")), Field("type", "Type", False, ("type", "kind", "agent type")),
                Field("owner", "Owner", False, ("owner", "created by", "creator", "owner email")), Field("department", "Department", False, DEPARTMENT)),
               account_type="enterprise"),
    ExportType("expense", "Expense export", "Any expense system", "Paid AI subscriptions",
               (Field("text", "Description or merchant", True, EXPENSE_TEXT), Field("merchant", "Second description column", False, ("merchant", "merchant name", "vendor", "payee")),
                Field("email", "Employee email", False, PERSON_EMAIL), Field("name", "Employee name", False, PERSON_NAME), Field("department", "Department", False, DEPARTMENT)),
               account_type="personal_paid", summary_only=True),
    ExportType("proxy", "Proxy or CASB log summary", "Netskope, Zscaler and others", "Traffic to AI domains",
               (Field("domain", "Domain or URL", True, DOMAIN), Field("user", "User", False, USER), Field("department", "Department", False, DEPARTMENT),
                Field("requests", "Requests", False, REQUESTS)),
               account_type="unknown", summary_only=True, keep_people=False),
)}
CONNECTOR_TYPES = {t.connector_type: t for t in EXPORT_TYPES.values()}
LABELS = {t.connector_type: t.label for t in EXPORT_TYPES.values()}
ALLOWED_SUFFIXES = (".csv", ".txt", ".xlsx")

# Findings and the opportunity each opens (trigger_ref is the key: one opportunity per client and finding).
FINDINGS = {
    "copilot_licences": ("X-04 Copilot governance rollout", "readiness"),
    "agents_found": ("AA/AW Agent Assure and AgentWarden", "other"),
    "undeclared_paid": ("M-07, M-08 Policy and training follow-up", "training"),
    "eu_high_risk": ("X-03 EU AI Act conformity readiness", "readiness"),
}


def export_type(key: str | None) -> ExportType:
    t = EXPORT_TYPES.get(key or "")
    if t is None:
        raise Invalid(errors=[{"field": "export_type", "message": "Choose the type of export."}])
    return t


# ---------------------------------------------------------------- reading the file
def read_table(data: bytes, filename: str | None) -> tuple[list[str], list[list[str]]]:
    """Headings (as written) and rows of a CSV or the first sheet of an .xlsx. Never more than MAX_ROWS rows."""
    suffix = Path(filename or "export.csv").suffix.lower() or ".csv"
    if suffix not in ALLOWED_SUFFIXES:
        raise Invalid(errors=[{"field": "file", "message": "Upload the export as CSV or Excel (.xlsx)."}])
    if suffix == ".xlsx":
        from app.core import xlsx_guard

        try:
            wb = xlsx_guard.open_workbook(data, max_rows=MAX_ROWS + 1, max_cols=MAX_COLS)
            raw = [["" if c is None else str(c).strip() for c in r] for r in xlsx_guard.rows(wb.worksheets[0], max_rows=MAX_ROWS + 1, max_cols=MAX_COLS)]
        except xlsx_guard.WorkbookTooLarge as exc:
            raise Invalid(errors=[{"field": "file", "message": str(exc)}]) from exc
        except Exception as exc:  # noqa: BLE001 (any other failure means the file is not a readable workbook)
            raise Invalid(errors=[{"field": "file", "message": "This file could not be read as an Excel workbook. Save it as .xlsx or CSV and try again."}]) from exc
    else:
        text = _text(data)
        if not text.strip():
            raise Invalid(errors=[{"field": "file", "message": "The file is empty."}])
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        raw = []
        try:
            for r in csv.reader(io.StringIO(text), dialect):
                raw.append([c.strip() for c in r[:MAX_COLS]])
                if len(raw) > MAX_ROWS + 1:
                    break
        except csv.Error as exc:  # a broken quote, a NUL byte, or a cell over the CSV reader's 128 KB limit
            raise Invalid(errors=[{"field": "file", "message": "This file could not be read as CSV. Export it again from the admin console as CSV or Excel (.xlsx) and try again."}]) from exc
    raw = [r for r in raw if any(c for c in r)]
    if not raw:
        raise Invalid(errors=[{"field": "file", "message": "The file is empty."}])
    headers = [" ".join(h.split()) for h in raw[0]]
    rows = raw[1:]
    if len(rows) > MAX_ROWS:
        raise Invalid(errors=[{"field": "file", "message": f"The file has more than {MAX_ROWS:,} rows. Split it and import each part."}])
    return headers, rows


def _norm(h: str) -> str:
    return " ".join(h.replace("_", " ").split()).lower()


def guess_mapping(t: ExportType, headers: list[str]) -> dict[str, str]:
    by = {_norm(h): h for h in headers if h}
    out: dict[str, str] = {}
    used: set[str] = set()
    for f in t.fields:
        for a in f.aliases:
            h = by.get(_norm(a))
            if h and h not in used:
                out[f.key] = h
                used.add(h)
                break
        else:
            out[f.key] = ""
    return out


def check_mapping(t: ExportType, headers: list[str], mapping: dict | None) -> dict[str, str]:
    """The mapping to use: the one given (field key -> heading, "" for not in the file), or the guess. Required fields
    must name a heading of this file."""
    if not mapping:
        mapping = guess_mapping(t, headers)
    out, errors = {}, []
    for f in t.fields:
        v = mapping.get(f.key) or ""
        if not isinstance(v, str) or (v and v not in headers):
            errors.append({"field": f"mapping.{f.key}", "message": f"“{v}” is not a column of this file. Choose the column for {f.label}."})
            continue
        if f.required and not v:
            errors.append({"field": f"mapping.{f.key}", "message": f"Choose the column that holds {f.label}."})
        out[f.key] = v
    if errors:
        raise Invalid(errors=errors)
    return out


# ---------------------------------------------------------------- parsing
@dataclass
class Custom:
    """A tool that is not in the vendor dictionary: an agent, or an unmatched row named by hand."""
    vendor_key: str
    vendor: str
    product: str
    category: str
    department: str | None
    user_count: int
    detail: str | None


@dataclass
class Parsed:
    rows_read: int = 0
    rows_matched: int = 0
    observations: list[Observation] = field(default_factory=list)
    customs: list[Custom] = field(default_factory=list)
    unmatched: list[dict] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)

    @property
    def unmatched_count(self) -> int:
        return self.rows_read - self.rows_matched


class _Groups:
    def __init__(self, keep_people: bool):
        self.keep_people = keep_people
        self.g: dict[tuple[str, str], dict] = {}

    def add(self, vendor_key: str, dept: str | None, *, person: str | None = None, name: str | None = None, users: int | None = None,
            weight: int = 1, detail: str | None = None, active: bool = False) -> None:
        dept = " ".join((dept or "").split()) or None
        e = self.g.setdefault((vendor_key, (dept or "").casefold()), {"dept": dept, "people": {}, "anon": 0, "count": 0, "details": set(), "active": set(), "rows": 0})
        e["rows"] += 1
        if person:
            p = person.strip().lower()
            e["people"].setdefault(p, name)
            if active:
                e["active"].add(p)
        elif users is not None:
            e["anon"] += max(users, 0)
        else:
            e["anon"] += 1
        e["count"] += max(weight, 0)
        if detail:
            e["details"].update(d.strip() for d in re.split(r"[,;]", detail) if d.strip())

    def observations(self, describe) -> list[Observation]:
        out = []
        for (vendor_key, _), e in self.g.items():
            n = len(e["people"]) + e["anon"]
            o = Observation(vendor_key, SIGNAL, e["dept"], n, e["count"], [], dict(e["people"]) if self.keep_people else None)
            o.details = [describe(e, n)]
            o.detail = o.details[0][:300] if o.details[0] else None
            if not o.details[0]:
                o.details = []
            out.append(o)
        return out


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def _int(v: str) -> int | None:
    try:
        return int(float((v or "").replace(",", "")))
    except ValueError:
        return None


def _slug(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", v.lower()).strip("-")[:40] or "unnamed"


def parse(t: ExportType, headers: list[str], rows: list[list[str]], mapping: dict[str, str]) -> Parsed:
    idx = {k: (headers.index(v) if v else None) for k, v in mapping.items()}

    def cell(row: list[str], key: str) -> str:
        i = idx.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    out = Parsed()
    groups = _Groups(t.keep_people)
    unmatched: dict[tuple[str, str], dict] = {}
    customs: dict[str, Custom] = {}

    def miss(name: str, dept: str, users: int | None) -> None:
        if t.summary_only or not AI_WORDS.search(name.lower()):  # spending and browsing text is never kept or shown
            return
        u = unmatched.setdefault((name.casefold(), dept.casefold()), {"name": name, "department": dept or None, "user_count": 0})
        u["user_count"] += users if users is not None else 1

    for row in rows:
        out.rows_read += 1
        dept = cell(row, "department")
        matched: str | None = None
        if t.key == "copilot_usage":
            lic = cell(row, "licence")
            lv = (vendors.match_name(lic) or vendors.match_expense(lic)) if lic else None
            if not lic or (lv is not None and lv.key == "microsoft_copilot"):
                user = cell(row, "user")
                groups.add("microsoft_copilot", dept, person=user or None, active=cell(row, "last_activity").lower() not in NOT_ACTIVE)
                matched = "Microsoft 365 Copilot"
        elif t.key in ("entra_apps", "google_apps"):
            name = cell(row, "app")
            v = vendors.match_name(name)
            users = _int(cell(row, "users")) if mapping.get("users") else None
            if v is not None:
                groups.add(v.key, dept, person=cell(row, "user") or None, users=users, detail=cell(row, "consent" if t.key == "entra_apps" else "scopes"))
                matched = v.product
            elif name:
                miss(name, dept, users)
        elif t.key == "gemini_usage":
            users = _int(cell(row, "users")) if mapping.get("users") else None
            groups.add("google_gemini", dept, person=cell(row, "user") or None, users=users, detail=cell(row, "app"))
            matched = "Gemini"
        elif t.key == "gemini_agents":
            name = cell(row, "agent")
            if name:
                key = f"agent:gemini:{_slug(name)}"
                c = customs.setdefault(key, Custom(key, "Google", name[:120], "AI agent (Gemini Enterprise)", dept or None, 0,
                                                   ", ".join(x for x in (cell(row, "type"), f"owner {cell(row, 'owner')}" if cell(row, "owner") else "") if x)[:300] or None))
                matched = name
        elif t.key == "expense":
            text = " ".join(x for x in (cell(row, "text"), cell(row, "merchant")) if x)
            v = vendors.match_expense(text)
            if v is not None:
                email, name = cell(row, "email").lower(), cell(row, "name")
                groups.add(v.key, dept, person=email or name or None, name=name or None)
                matched = v.product
            elif text:
                miss(text, dept, None)
        elif t.key == "proxy":
            v = vendors.match_domain(cell(row, "domain"))
            if v is not None:
                groups.add(v.key, dept, person=cell(row, "user") or None, weight=_int(cell(row, "requests")) or 1)
                matched = v.product
        if matched:
            out.rows_matched += 1
        if len(out.preview) < PREVIEW_ROWS and (matched or not t.summary_only):  # expense and proxy: only the AI rows
            out.preview.append({"cells": {f.key: cell(row, f.key) for f in t.fields}, "match": matched})

    def describe(e: dict, n: int) -> str:
        if t.key == "copilot_usage":
            return f"{_plural(n, 'licence')} · {len(e['active']):,} active"
        if t.key == "expense":
            return _plural(n, "paid subscription")
        if t.key == "proxy":
            return _plural(e["count"], "request")
        return ", ".join(sorted(e["details"]))

    out.observations = groups.observations(describe)
    out.customs = list(customs.values())
    out.unmatched = sorted(unmatched.values(), key=lambda u: (u["name"].casefold(), (u["department"] or "").casefold()))
    return out


# ---------------------------------------------------------------- findings
def _eu_scoped(db: Session, org_id: str) -> bool:
    """The client has an in-scope site in the EU, or a register system that runs in or uses data of people in the EU."""
    import yaml

    from app.engagements.models import ClientLocation
    from app.reference.jurisdictions import SEEDS
    from app.reference.models import Jurisdiction
    from app.register.models import RegisterSystem

    eu = set(yaml.safe_load((SEEDS / "eu_members.yaml").read_text())["members"])
    eu_id = db.scalar(select(Jurisdiction.id).where(Jurisdiction.code == "EU"))
    for loc in db.scalars(select(ClientLocation).where(ClientLocation.organization_id == org_id, ClientLocation.deleted_at.is_(None), ClientLocation.in_scope.is_(True))):
        if (loc.country_code or "").upper() in eu or (eu_id and eu_id in (loc.jurisdiction_ids or [])):
            return True
    for s in db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None))):
        places = [s.run_location or {}] + list(s.data_locations or [])
        if any(isinstance(p, dict) and (p.get("country") or "").upper() in eu for p in places):
            return True
    return False


def findings_for(db: Session, org_id: str, t: ExportType, tools: list[DiscoveredTool]) -> list[dict]:
    """What this import found that Sales should hear about. `tools` are the rows the import created or updated."""
    from app.connectors.service import declared_keys
    from app.sales.models import Opportunity

    out: list[tuple[str, str, list[DiscoveredTool]]] = []
    copilot = [x for x in tools if x.vendor_key == "microsoft_copilot"]
    if copilot:
        n = sum(x.user_count for x in copilot)
        out.append(("copilot_licences", f"Copilot licences found: {_plural(n, 'person', 'people')}", copilot))
    agents = [x for x in tools if x.vendor_key.startswith("agent:") or (vendors.by_key(x.vendor_key) and "agent" in vendors.by_key(x.vendor_key).category.lower())]
    if agents:
        out.append(("agents_found", f"{_plural(len(agents), 'AI agent')} found", agents))
    if t.key == "expense":
        declared, _ = declared_keys(db, org_id)
        paid = [x for x in tools if x.vendor_key not in declared]
        if paid:
            products = sorted({x.product for x in paid})
            out.append(("undeclared_paid", f"{_plural(len(products), 'undeclared paid AI tool')}: {', '.join(products)}", paid))
    risky = [x for x in tools if (vendors.by_key(x.vendor_key) and vendors.by_key(x.vendor_key).eu_high_risk)]
    if risky and _eu_scoped(db, org_id):
        out.append(("eu_high_risk", f"EU-scoped high-risk AI system: {', '.join(sorted({x.product for x in risky}))}", risky))
    result = []
    for key, label, rows in out:
        opp = db.scalar(select(Opportunity.id).where(Opportunity.organization_id == org_id, Opportunity.trigger == "discovery_finding", Opportunity.trigger_ref == key))
        service, kind = FINDINGS[key]
        result.append({"key": key, "label": label, "service": service, "service_kind": kind, "tool_ids": [x.id for x in rows], "opportunity_id": opp})
    return result


def after_confirm(db: Session, tool: DiscoveredTool, user: User | None) -> list[str]:
    """A manual-import tool was confirmed: each finding it backs is now final and opens its opportunity (once per client).
    Returns the opportunity ids opened or found."""
    from app.sales import service as sales

    opened: list[str] = []
    imports = list(db.scalars(select(DiscoveryImport).where(DiscoveryImport.organization_id == tool.organization_id, DiscoveryImport.deleted_at.is_(None))
                              .order_by(DiscoveryImport.imported_at)))
    by_key: dict[str, str] = {}
    for imp in imports:
        for f in imp.findings or []:
            if tool.id not in (f.get("tool_ids") or []) or f["key"] in by_key:
                continue
            if f.get("opportunity_id"):
                by_key[f["key"]] = f["opportunity_id"]
                continue
            t = EXPORT_TYPES.get(imp.export_type)
            o = sales.open_from_trigger(db, tool.organization_id, "discovery_finding", f["key"], service=f["service"], service_kind=f.get("service_kind") or "other",
                                        why_now=f"{f['label']} (manual import of the {t.label if t else 'export'}, {imp.imported_at:%d %b %Y}); confirmed by {user.name if user else 'the client'}",
                                        created_by=user.id if user else None)
            by_key[f["key"]] = o.id
            audit.record(db, actor_id=user.id if user else None, action="discovery_import.finding_final", obj=imp,
                         summary=f"Finding final: {f['label']}. Opportunity {f['service']} raised for Sales.")
    if by_key:
        for imp in imports:
            fs = [dict(f, opportunity_id=by_key.get(f["key"], f.get("opportunity_id"))) for f in imp.findings or []]
            if fs != (imp.findings or []):
                imp.findings = fs
        opened = list(by_key.values())
    db.flush()
    return opened


# ---------------------------------------------------------------- import
def _connector(db: Session, org: Organization, t: ExportType) -> Connector:
    c = db.scalar(select(Connector).where(Connector.organization_id == org.id, Connector.type == t.connector_type, Connector.deleted_at.is_(None)))
    if c is None:
        c = Connector(organization_id=org.id, type=t.connector_type, status="imported", scopes=[], verified_domains=[])
        db.add(c)
        db.flush()
    return c


def _upsert_custom(db: Session, conn: Connector, c: Custom, now: datetime, extra: dict) -> DiscoveredTool:
    from app.connectors.service import _norm, match_department
    from app.tenancy.models import Department

    depts = list(db.scalars(select(Department).where(Department.organization_id == conn.organization_id, Department.deleted_at.is_(None))))
    d = match_department(c.department, depts)
    key = d.id if d else (f"name:{_norm(c.department)}" if c.department else "unknown")
    row = db.scalar(select(DiscoveredTool).where(DiscoveredTool.connector_id == conn.id, DiscoveredTool.vendor_key == c.vendor_key, DiscoveredTool.signal == SIGNAL,
                                                 DiscoveredTool.department_key == key))
    if row is None:
        row = DiscoveredTool(organization_id=conn.organization_id, connector_id=conn.id, vendor_key=c.vendor_key[:60], signal=SIGNAL, department_key=key, first_seen=now, status="new")
        db.add(row)
    row.vendor, row.product, row.category = c.vendor[:120], c.product[:120], c.category[:120]
    row.department_id, row.department_name = (d.id if d else None), (c.department or None)
    row.user_count, row.detail, row.last_seen = c.user_count, c.detail, now
    for k, v in extra.items():
        setattr(row, k, v)
    db.flush()
    return row


def _summary_csv(db: Session, t: ExportType, parsed: Parsed) -> str:
    from app.documents.csvsafe import to_csv

    rows = []
    for o in parsed.observations:
        v = vendors.by_key(o.vendor_key)
        rows.append([v.vendor if v else o.vendor_key, v.product if v else o.vendor_key, o.department or "", o.user_count, o.detail or ""])
    return to_csv(["Vendor", "Product", "Department", "People", "Detail"], sorted(rows, key=lambda r: (str(r[1]), str(r[2]))))


def run_import(db: Session, settings: Settings, user: User, org: Organization, engagement_id: str | None, export_key: str, filename: str | None, data: bytes,
               mapping: dict | None, save_preset: str | None = None, preset_owner_id: str | None = None) -> DiscoveryImport:
    from app.connectors.service import _finish_run, ingest
    from app.files.service import upload as store_file

    t = export_type(export_key)
    headers, rows = read_table(data, filename)
    mapping = check_mapping(t, headers, mapping)
    parsed = parse(t, headers, rows, mapping)
    now = utcnow()
    name = Path(filename or "export.csv").name[:255] or "export.csv"
    conn = _connector(db, org, t)
    imp = DiscoveryImport(organization_id=org.id, engagement_id=engagement_id, connector_id=conn.id, export_type=t.key, filename=name,
                          source_sha256=hashlib.sha256(data).hexdigest(), source_size=len(data), mapping=mapping, rows_read=parsed.rows_read,
                          rows_matched=parsed.rows_matched, unmatched=[dict(u, matched_tool_id=None) for u in parsed.unmatched], unmatched_count=parsed.unmatched_count,
                          findings=[],
                          imported_by=user.id, imported_at=now, created_by=user.id)
    db.add(imp)
    db.flush()
    # On an engagement the file is engagement evidence (v0.6.1 §9.6); from Integrations it is the client's own import file
    # (download rule: import_router.import_file_access).
    link = "evidence" if engagement_id else "discovery_import"
    if t.summary_only:
        stem = Path(name).stem[:180]
        f = store_file(db, settings, user, data=_summary_csv(db, t, parsed).encode("utf-8"), filename=f"{stem} AI rows summary.csv", content_type="text/csv",
                       organization_id=org.id, engagement_id=engagement_id, linked_type=link, linked_id=engagement_id or imp.id)
    else:
        f = store_file(db, settings, user, data=data, filename=name, content_type=None, organization_id=org.id, engagement_id=engagement_id,
                       linked_type=link, linked_id=engagement_id or imp.id)
    imp.evidence_file_id = f.id
    run = ConnectorRun(organization_id=org.id, connector_id=conn.id, kind="import", started_at=now, status="running", started_by=user.id, filename=name,
                       rows_read=parsed.rows_read, rows_matched=parsed.rows_matched)
    db.add(run)
    db.flush()
    extra = {"import_id": imp.id, "import_type": t.key}
    before = set(db.scalars(select(DiscoveredTool.id).where(DiscoveredTool.connector_id == conn.id)))
    found = ingest(db, conn, parsed.observations, now, extra=extra)
    touched = list(db.scalars(select(DiscoveredTool).where(DiscoveredTool.connector_id == conn.id, DiscoveredTool.import_id == imp.id)))
    for c in parsed.customs:
        touched.append(_upsert_custom(db, conn, c, now, extra))
        found += 1
    run.tools_found = imp.tools_found = found
    imp.findings = findings_for(db, org.id, t, touched)
    if save_preset and save_preset.strip():
        save_mapping_preset(db, user, preset_owner_id or user.organization_id, t, save_preset, mapping)
    audit.record(db, actor_id=user.id, action="discovery_import.imported", obj=imp, organization_id=org.id,
                 summary=f"Imported {t.label} file {name}: {parsed.rows_read} rows, {parsed.rows_matched} matched, {found} AI tool and department pairs "
                         f"({len(touched) - len(before & {x.id for x in touched})} new). Stored as evidence, SHA-256 {imp.source_sha256[:12]}…")
    _finish_run(db, settings, conn, run, now)
    conn.status = "imported"
    db.flush()
    return imp


def save_mapping_preset(db: Session, user: User, owner_id: str, t: ExportType, name: str, mapping: dict) -> ImportMappingPreset:
    name = " ".join(name.split())[:120]
    p = db.scalar(select(ImportMappingPreset).where(ImportMappingPreset.organization_id == owner_id, ImportMappingPreset.export_type == t.key,
                                                    ImportMappingPreset.name == name, ImportMappingPreset.deleted_at.is_(None)))
    if p is None:
        p = ImportMappingPreset(organization_id=owner_id, export_type=t.key, name=name, created_by=user.id)
        db.add(p)
    p.mapping, p.updated_by = dict(mapping), user.id
    db.flush()
    audit.record(db, actor_id=user.id, action="discovery_import.preset_saved", obj=p, organization_id=owner_id, summary=f"Saved column mapping “{name}” for {t.label}")
    return p


def presets(db: Session, owner_id: str) -> list[dict]:
    rows = db.scalars(select(ImportMappingPreset).where(ImportMappingPreset.organization_id == owner_id, ImportMappingPreset.deleted_at.is_(None))
                      .order_by(ImportMappingPreset.export_type, ImportMappingPreset.name))
    return [{"id": p.id, "export_type": p.export_type, "name": p.name, "mapping": p.mapping} for p in rows]


def preset_mapping(db: Session, owner_id: str, preset_id: str | None) -> dict | None:
    if not preset_id:
        return None
    p = db.get(ImportMappingPreset, preset_id)
    if p is None or p.organization_id != owner_id or p.deleted_at is not None:
        raise NotFound()
    return dict(p.mapping)


def match_unmatched(db: Session, user: User, org: Organization, import_id: str, index: int, vendor_key: str | None, vendor: str | None, product: str | None) -> DiscoveredTool:
    """Name an unmatched row by hand: a product from the vendor dictionary, or a vendor and product typed in."""
    imp = db.get(DiscoveryImport, import_id)
    if imp is None or imp.organization_id != org.id or imp.deleted_at is not None:
        raise NotFound()
    items = list(imp.unmatched or [])
    if not 0 <= index < len(items):
        raise NotFound()
    u = items[index]
    t = EXPORT_TYPES[imp.export_type]
    v = vendors.by_key(vendor_key) if vendor_key else None
    if vendor_key and v is None:
        raise Invalid(errors=[{"field": "vendor_key", "message": "Choose a product from the AI vendor list."}])
    if v is None:
        vendor, product = " ".join((vendor or "").split()), " ".join((product or "").split())
        if not vendor or not product:
            raise Invalid(errors=[{"field": "product", "message": "Enter the vendor and the product, or choose one from the AI vendor list."}])
    c = Custom(v.key if v else f"other:{_slug(vendor)}:{_slug(product)}", v.vendor if v else vendor, v.product if v else product, v.category if v else "AI tool (matched by hand)",
               u.get("department"), int(u.get("user_count") or 0), "Matched by hand from a manual import")
    conn = db.get(Connector, imp.connector_id)
    row = _upsert_custom(db, conn, c, utcnow(), {"import_id": imp.id, "import_type": t.key})
    items[index] = dict(u, matched_tool_id=row.id)
    imp.unmatched = items
    audit.record(db, actor_id=user.id, action="discovery_import.matched", obj=imp, organization_id=org.id, summary=f"Matched “{u['name']}” to {row.vendor} {row.product} by hand")
    db.flush()
    return row


# ---------------------------------------------------------------- read models
def type_out(t: ExportType) -> dict:
    return {"value": t.key, "label": t.label, "source": t.source, "parsed_into": t.parsed_into, "summary_only": t.summary_only,
            "fields": [{"key": f.key, "label": f.label, "required": f.required} for f in t.fields]}


def analyse(db: Session, org: Organization, export_key: str, filename: str | None, data: bytes, mapping: dict | None) -> dict:
    """Step 3 and 4 before anything is stored: the headings, the mapping in use, a preview, the tools it would find."""
    from app.connectors.service import declared_keys

    t = export_type(export_key)
    headers, rows = read_table(data, filename)
    mapping = check_mapping(t, headers, mapping)
    parsed = parse(t, headers, rows, mapping)
    declared, has_campaign = declared_keys(db, org.id)
    tools = []
    for o in parsed.observations:
        v = vendors.by_key(o.vendor_key)
        tools.append({"vendor_key": o.vendor_key, "vendor": v.vendor, "product": v.product, "category": v.category, "department": o.department or "Department not recorded",
                      "user_count": o.user_count, "detail": o.detail, "declared": o.vendor_key in declared})
    for c in parsed.customs:
        tools.append({"vendor_key": c.vendor_key, "vendor": c.vendor, "product": c.product, "category": c.category, "department": c.department or "Department not recorded",
                      "user_count": c.user_count, "detail": c.detail, "declared": False})
    tools.sort(key=lambda x: (x["product"].casefold(), x["department"].casefold()))
    return {"export_type": t.key, "filename": filename, "headers": headers, "mapping": mapping, "rows_read": parsed.rows_read, "rows_matched": parsed.rows_matched,
            "preview": parsed.preview, "tools": tools, "unmatched": parsed.unmatched, "unmatched_count": parsed.unmatched_count, "attestation_exists": has_campaign,
            "sha256": hashlib.sha256(data).hexdigest(), "summary_only": t.summary_only}


def import_out(db: Session, imp: DiscoveryImport, *, sales: bool = True) -> dict:
    """An import as a screen shows it. `sales=False` (any client response) leaves out the findings: what Futran sells
    from them is never shown to the client."""
    t = EXPORT_TYPES.get(imp.export_type)
    by = db.get(User, imp.imported_by) if imp.imported_by else None
    out = {"id": imp.id, "export_type": imp.export_type, "export_label": t.label if t else imp.export_type, "filename": imp.filename, "sha256": imp.source_sha256,
            "size": imp.source_size, "rows_read": imp.rows_read, "rows_matched": imp.rows_matched, "tools_found": imp.tools_found, "mapping": imp.mapping,
            "unmatched": imp.unmatched or [], "unmatched_count": imp.unmatched_count, "findings": imp.findings or [], "evidence_file_id": imp.evidence_file_id,
            "summary_only": bool(t and t.summary_only), "engagement_id": imp.engagement_id, "imported_by": by.name if by else None, "imported_at": imp.imported_at.isoformat()}
    if not sales:
        out.pop("findings")
    return out


def own_imports(db: Session, org: Organization) -> list[DiscoveryImport]:
    """The imports the client's own people made (from Integrations): never Futran's engagement imports."""
    mine = set(db.scalars(select(User.id).where(User.organization_id == org.id)))
    return [i for i in imports(db, org) if i.engagement_id is None and i.imported_by in mine]


def imports(db: Session, org: Organization) -> list[DiscoveryImport]:
    return list(db.scalars(select(DiscoveryImport).where(DiscoveryImport.organization_id == org.id, DiscoveryImport.deleted_at.is_(None))
                           .order_by(DiscoveryImport.imported_at.desc())))
