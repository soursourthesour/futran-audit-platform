"""Seeding the register: CSV import and "Import from inventory" (spec §24.4; v0.6 plan, WS-B integration).

Import from inventory is an action the user runs, never a background job. Approved use cases and the tools and agents
declared in the inventory become proposed register rows, one per vendor and product however many account types or use
cases mention it. Running it again adds only what is new.
"""
import csv
import io
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.errors import Invalid
from app.documents.csvsafe import to_csv
from app.inventory.models import AITool, UseCase
from app.register import service as svc
from app.register.models import RegisterSystem
from app.tenancy.models import Department, Organization, User

IMPORT_HEADER = ["name", "type", "sourcing", "department", "stage", "purpose", "vendor", "ai_provider", "model_name", "decision_impact", "owner_email"]  # before 11-03; still read
EXPORT_HEADER = ["reference", "name", "type", "sourcing", "department", "stage", "purpose", "vendor", "ai_provider", "model_name", "model_version", "decision_impact",
                 "risk_tier", "laws", "owner", "last_bias_test", "bias_status", "consent", "required_roles_filled", "go_live_gate"]
MAX_ROWS = 2000
DATA_MAP = {"pii": "personal", "phi": "health", "client": "confidential", "confidential": "confidential"}
SHADOW_ACCOUNTS = {"personal_free", "personal_paid"}


def dedupe_key(vendor: str | None, product: str) -> str:
    return f"{' '.join((vendor or '').split()).casefold()}|{' '.join(product.split()).casefold()}"[:260]


def _match(value: str, labels: dict) -> str | None:
    v = " ".join(value.split()).casefold()
    for code, label in labels.items():
        if v in (code.casefold(), label.casefold(), code.replace("_", " ").casefold()):
            return code
    return None


# ---- CSV
def export_rows(db: Session, systems: list[RegisterSystem]) -> list[list]:
    from app.register.serialize import system_out

    out = []
    for s in systems:
        o = system_out(db, s, None)
        out.append([o["reference"], o["name"], o["type_label"], o["sourcing_label"], (o["department"] or {}).get("name") or ("Company-wide" if o["company_wide"] else ""),
                    o["stage_label"], o["purpose"], (o["vendor"] or {}).get("name"), o["ai_provider_label"], o["model_name"], o["model_version"],
                    svc.DECISION_LABELS.get(o["decision_impact"] or "", ""), f"Tier {o['risk_tier']}" if o["risk_tier"] else "", "; ".join(l["short_name"] for l in o["laws"]),
                    (o["owner"] or {}).get("name"), o["bias"]["last_tested_on"], o["bias"]["label"], o["consent"]["label"],
                    f"{o['roles']['filled']} / {o['roles']['required']}", o["gate"]["label"]])
    return out


# ---- the import template (11-03 C7): the form's fields in the form's order
@dataclass(frozen=True)
class Column:
    key: str  # payload field, or a pseudo-field handled below
    header: str
    required: bool = False
    labels: dict | None = None  # allowed values, code -> label
    many: bool = False  # several values separated by semicolons
    note: str = ""
    legacy: str | None = None  # the column's name in the template used before 11-03


def columns(db: Session | None = None) -> list[Column]:
    providers = dict(svc.AI_PROVIDERS)
    if db is not None:
        from app.register.catalogue import FIXED, vendors

        providers = {v.code: v.name for v in vendors(db)} | FIXED
    stages = {k: v for k, v in svc.STAGE_LABELS.items() if k != "live"}
    return [
        Column("name", "Name *", True, note="The name your staff use for the system.", legacy="name"),
        Column("type", "Type *", True, svc.TYPE_LABELS, legacy="type"),
        Column("sourcing", "Built or bought *", True, svc.SOURCING_LABELS, legacy="sourcing"),
        Column("department", "Department *", True, note="A department as it is named under People, or Company-wide (needs company-wide rights).", legacy="department"),
        Column("department_ids", "Used by departments", many=True, note="When several departments (not all) use it: their names, separated by semicolons."),
        Column("stage", "Stage", labels=stages, note="Blank is Proposed. Live is not accepted: import as Ready for go-live and submit for approval.", legacy="stage"),
        Column("purpose", "Purpose", note="What it does and for whom.", legacy="purpose"),
        Column("users_scope", "Who uses it", labels=svc.USERS_SCOPE),
        Column("users_description", "Users", note="For example Recruiting team."),
        Column("user_count", "Number of users", note="A whole number."),
        Column("owner_email", "System owner email", note="The work email of a user of the company.", legacy="owner_email"),
        Column("vendor", "Vendor", note="Added to the company vendor register if it is new.", legacy="vendor"),
        Column("ai_provider", "Underlying AI provider", labels=providers, legacy="ai_provider"),
        Column("model_name", "Model or algorithm", note="A model from the AI model list for the provider, or your own name for it.", legacy="model_name"),
        Column("model_version", "Model version"),
        Column("algorithm_type", "Algorithm type", labels=svc.ALGORITHM_TYPES),
        Column("hosting", "Hosting", labels=svc.HOSTING),
        Column("vendor_trains_on_data", "Vendor trains on our data", labels=svc.TRAINS_LABELS),
        Column("vendor_documents", "Vendor documents received", labels=svc.VENDOR_DOCS, many=True),
        Column("actions", "Agent actions and tools", labels={k: v for k, v in svc.ACTION_CODES.items() if k != "other"}, many=True, note="AI agents only."),
        Column("other_action", "Other action or tool", note="AI agents only. An action not in the list."),
        Column("autonomy", "How much it acts on its own", labels=svc.AUTONOMY_LABELS, note="AI agents only."),
        Column("guardrail_policy_ref", "Runtime controls", note="For example a Futran GuardRail policy name."),
        Column("agentassure_status", "Pre-release testing", labels=svc.AGENTASSURE),
        Column("data_categories", "Data used", labels=svc.DATA_CATEGORIES, many=True),
        Column("data_subjects", "Whose data", labels=svc.DATA_SUBJECTS, many=True),
        Column("consent_basis", "Was consent obtained?", labels=svc.CONSENT_LABELS),
        Column("consent_ref", "Consent date or version"),
        Column("retention_period", "Retention period", note="For example 4 years."),
        Column("cross_border", "Data leaves the country?", labels=svc.CROSS_BORDER),
        Column("run_country", "Where it runs: country", note="A two-letter country code (US, DE, IN) or the country's name."),
        Column("run_region", "Where it runs: state or region", note="A state or region of that country: its code (NY or US-NY) or its name."),
        Column("run_city", "Where it runs: city"),
        Column("data_locations", "Where the people whose data it uses are", many=True,
               note="Places separated by semicolons. Each is a country code (DE), a state or region code (US-IL), or a city then a comma and its state code (New York, US-NY)."),
        Column("laws", "Laws that apply", many=True, note="Law names exactly as in the law library, separated by semicolons. Adding laws needs the right to add laws."),
        Column("decision_impact", "Effect on decisions about people", labels=svc.DECISION_LABELS, legacy="decision_impact"),
        Column("bias_next_due", "Next bias test due", note="A date, YYYY-MM-DD."),
    ]


EXAMPLE = {"Name *": "Résumé screening", "Type *": "Vendor app with AI", "Built or bought *": "Bought from vendor", "Department *": "Human Resources",
           "Stage": "In development / procurement", "Purpose": "Ranks applicants for recruiters", "Who uses it": "Role level", "Users": "Recruiting team",
           "System owner email": "owner@example.com", "Vendor": "TalentRank Inc.", "Underlying AI provider": "Unknown, vendor did not disclose", "Algorithm type": "Ranking or scoring model",
           "Data used": "Personal information", "Whose data": "Job candidates", "Where it runs: country": "US", "Where it runs: state or region": "NY",
           "Where it runs: city": "New York", "Where the people whose data it uses are": "US-NY; US-NJ", "Effect on decisions about people": "Supports a decision a person makes"}
HEADER = [c.header for c in columns()]


def template_csv() -> str:
    return to_csv(HEADER, [[EXAMPLE.get(h, "") for h in HEADER]])


def _text_cells(cells) -> None:
    """Every value is text: a name from the AI model list that starts with = + - or @ is never read as a formula."""
    for cell in cells:
        if isinstance(cell.value, str):
            cell.data_type = "s"


def template_xlsx(db: Session) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    cols = columns(db)
    wb = Workbook()
    ws = wb.active
    ws.title = "AI systems"
    ws.append([c.header for c in cols])
    for i, c in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=i)
        cell.font = Font(bold=True, color="FFFFFF" if c.required else "1F2A44")
        cell.fill = PatternFill("solid", fgColor="1F2A44" if c.required else "E8ECF3")
        ws.column_dimensions[get_column_letter(i)].width = max(14, min(40, len(c.header) + 4))
    ws.freeze_panes = "B2"
    ins = wb.create_sheet("Instructions")
    ins.append(["Column", "Required", "What to enter", "Allowed values"])
    for c in cols:
        what = c.note or ""
        if c.many:
            what = (what + " " if what else "") + "Several values may be given, separated by semicolons."
        ins.append([c.header, "Required" if c.required else "Optional", what.strip(), "; ".join(c.labels.values()) if c.labels else ""])
    for cell in ins[1]:
        cell.font = Font(bold=True)
    for letter, w in (("A", 36), ("B", 11), ("C", 70), ("D", 90)):
        ins.column_dimensions[letter].width = w
    for row in ins.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ins.append([])
    ins.append(["Fill one row per AI system on the AI systems sheet, from row 2. Columns marked * are required. Each row is checked as the form checks it, "
                "and nothing is imported until every row is correct. Example row:"])
    ins.append([f"{h}: {v}" for h, v in EXAMPLE.items()][:1] + ["; ".join(f"{h} = {v}" for h, v in EXAMPLE.items())])
    lists = wb.create_sheet("Lists")
    n = 0
    for i, c in enumerate(cols, start=1):
        if not c.labels or c.many:
            continue
        n += 1
        letter = get_column_letter(n)
        for r, label in enumerate(c.labels.values(), start=1):
            lists.cell(row=r, column=n, value=label)
        dv = DataValidation(type="list", formula1=f"=Lists!${letter}$1:${letter}${len(c.labels)}", allow_blank=True, showErrorMessage=False)
        dv.add(f"{get_column_letter(i)}2:{get_column_letter(i)}2000")
        ws.add_data_validation(dv)
    lists.sheet_state = "hidden"
    for sheet in (ws, ins, lists):
        for row in sheet.iter_rows():
            _text_cells(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def rows_from_upload(raw: bytes) -> list[list[str]]:
    """The rows of an uploaded CSV, or of the "AI systems" sheet (else the first sheet) of a workbook."""
    if raw[:2] == b"PK":
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - any unreadable workbook gets the same message
            raise Invalid(errors=[{"field": "file", "message": "The workbook could not be read. Save it again as .xlsx from the template."}]) from exc
        ws = wb["AI systems"] if "AI systems" in wb.sheetnames else wb.worksheets[0]
        out = []
        for row in ws.iter_rows(values_only=True):
            out.append(["" if v is None else (v.date().isoformat() if hasattr(v, "date") and hasattr(v, "hour") else str(v)) for v in row])
        return out
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    return list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))


def _key(h: str) -> str:
    return " ".join(str(h or "").replace("*", " ").split()).casefold()


def parse_import(db: Session, org: Organization, text_or_rows, editable_depts: set[str] | None, *, can_add_law: bool = True,
                 warnings: list[dict] | None = None) -> tuple[list[tuple[int, dict]], list[dict]]:
    """Rows as create payloads, and every error with its row number. Rows are checked with the same validation as the form.
    Columns are found by their header (the 11-03 template's, or the template's before it), in any order. A column that is
    not in the template (a note column added to an old file) is ignored, with a warning added to `warnings`."""
    errors: list[dict] = []
    try:
        rows = list(csv.reader(io.StringIO(text_or_rows.lstrip("\ufeff")))) if isinstance(text_or_rows, str) else text_or_rows
    except csv.Error:
        return [], [{"row": 0, "field": "file", "message": "The file could not be read. Save it as CSV (comma delimited) from the template and try again."}]
    if not rows:
        return [], [{"row": 1, "field": "file", "message": "The file is empty or could not be read. Save it as CSV from the template."}]
    cols = columns(db)
    by_key = {_key(c.header): c for c in cols} | {c.legacy: c for c in cols if c.legacy}
    header = [str(h or "").strip() for h in rows[0]]
    found: dict[int, Column] = {}
    for i, h in enumerate(header):
        if not h:
            continue
        c = by_key.get(_key(h)) or by_key.get(h.strip().lower())
        if c is None:
            if warnings is not None:
                warnings.append({"row": 1, "field": h, "message": f"The column '{h}' is not in the template and was ignored."})
            continue
        found[i] = c
    missing = [c.header.rstrip(" *") for c in cols if c.required and c not in found.values()]
    if missing:
        return [], [{"row": 1, "field": "header", "message": f"These required columns are missing: {', '.join(missing)}. Download the template and copy your rows into it."}]
    depts = {" ".join(d.name.split()).casefold(): d for d in db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None)))}
    out: list[tuple[int, dict]] = []
    for n, raw in enumerate(rows[1:], start=2):
        if not any(str(c).strip() for c in raw):
            continue
        if len(out) >= MAX_ROWS:
            errors.append({"row": n, "field": "file", "message": f"Only the first {MAX_ROWS} rows can be imported at once."})
            break
        r = {c.key: (str(raw[i]).strip() if i < len(raw) else "") for i, c in found.items()}
        heads = {c.key: c.header.rstrip(" *") if c.legacy is None else (c.legacy if c.legacy in [h.lower() for h in header] else c.header.rstrip(" *")) for c in found.values()}
        payload, row_errs = _row_payload(db, org, r, {c.key: c for c in cols}, heads, depts, editable_depts, can_add_law)
        if not row_errs:
            try:
                svc.clean(db, org, {k: v for k, v in payload.items() if k not in ("regulation_ids",)})
            except Invalid as e:
                row_errs += [{"field": _field_head(x["field"], heads), "message": x["message"]} for x in e.errors]
        seen = {x["field"] for x in row_errs}
        for k in ("name", "type"):
            if not r.get(k) and heads.get(k, k) not in seen:
                row_errs.append({"field": heads.get(k, k), "message": "Enter the AI system's name." if k == "name" else "Enter the type."})
        errors += [{"row": n, **e} for e in row_errs]
        out.append((n, payload))
    return out, errors


def _field_head(field: str, heads: dict) -> str:
    f = field.replace("data.", "").replace("_id", "") if field != "department_ids" else field
    return heads.get(field) or heads.get(f) or heads.get(field.replace("data.", "")) or f


def _split(v: str) -> list[str]:
    return [x.strip() for x in v.split(";") if x.strip()]


def _row_payload(db: Session, org: Organization, r: dict, cols: dict, heads: dict, depts: dict, editable_depts: set[str] | None, can_add_law: bool) -> tuple[dict, list[dict]]:
    errs: list[dict] = []
    h = lambda k: heads.get(k, cols[k].header.rstrip(" *"))  # noqa: E731
    p: dict = {"name": r.get("name", ""), "purpose": r.get("purpose") or None}
    for k in ("users_description", "model_name", "model_version", "guardrail_policy_ref"):
        if r.get(k):
            p[k] = r[k]
    for k in ("type", "sourcing", "ai_provider", "decision_impact", "users_scope", "algorithm_type", "hosting", "vendor_trains_on_data", "autonomy", "agentassure_status"):
        if r.get(k):
            code = _match(r[k], cols[k].labels)
            if code is None:
                errs.append({"field": h(k), "message": f"'{r[k]}' is not one of: {', '.join(cols[k].labels.values())}."})
            p[k] = code
        elif k in ("type", "sourcing"):
            p[k] = None
    stage = _match(r["stage"], svc.STAGE_LABELS) if r.get("stage") else "proposed"
    if stage == "live":
        errs.append({"field": h("stage"), "message": "Live needs go-live approval for each system. Import it as Ready for go-live, then submit it."})
    elif stage is None:
        errs.append({"field": h("stage"), "message": "Use Proposed, In development, Ready for go-live or Retired."})
    p["stage"] = stage if stage != "live" else "ready_for_go_live"
    dept_text = r.get("department", "")
    if dept_text.casefold() in ("company-wide", "company wide"):
        if editable_depts is not None:
            errs.append({"field": h("department"), "message": "Only the Chief AI Compliance Officer or Client Admin can add company-wide tools."})
        p["company_wide"] = True
    else:
        dept = depts.get(" ".join(dept_text.split()).casefold()) if dept_text else None
        if dept is None:
            errs.append({"field": h("department"), "message": f"'{dept_text}' is not a department. Add it under People first." if dept_text else "Enter the department."})
        elif editable_depts is not None and dept.id not in editable_depts:
            errs.append({"field": h("department"), "message": f"You can add systems only to your own department, not {dept.name}."})
        p["department_id"] = dept.id if dept else None
    if r.get("department_ids"):
        ids = []
        for name in _split(r["department_ids"]):
            d = depts.get(" ".join(name.split()).casefold())
            if d is None:
                errs.append({"field": h("department_ids"), "message": f"'{name}' is not a department."})
            else:
                ids.append(d.id)
        p["department_ids"] = ids
    if r.get("user_count"):
        p["user_count"] = r["user_count"]
    if r.get("vendor"):
        p["vendor_name"] = r["vendor"]
    if r.get("owner_email"):
        u = db.scalar(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None), func.lower(User.email) == r["owner_email"].lower()))
        if u is None:
            errs.append({"field": h("owner_email"), "message": f"No user with the email {r['owner_email']}."})
        else:
            p["owner_user_id"] = u.id
    for k in ("vendor_documents",):
        if r.get(k):
            p[k] = _codes(r[k], cols[k], h(k), errs)
    if r.get("actions") or r.get("other_action"):
        acts = [{"action_code": c} for c in _codes(r.get("actions", ""), cols["actions"], h("actions"), errs)]
        if r.get("other_action"):
            acts.append({"action_code": "other", "description": r["other_action"]})
        p["actions"] = acts
    data: dict = {}
    for k in ("data_categories", "data_subjects"):
        if r.get(k):
            data[k] = _codes(r[k], cols[k], h(k), errs)
    for k in ("consent_basis", "cross_border"):
        if r.get(k):
            code = _match(r[k], cols[k].labels)
            if code is None:
                errs.append({"field": h(k), "message": f"'{r[k]}' is not one of: {', '.join(cols[k].labels.values())}."})
            data[k] = code
    for k in ("consent_ref", "retention_period"):
        if r.get(k):
            data[k] = r[k]
    if data:
        p["data"] = data
    if r.get("bias_next_due"):
        p["bias_next_due"] = r["bias_next_due"][:10]
    if r.get("run_country"):
        place = _place(db, r["run_country"], r.get("run_region"), r.get("run_city"))
        if place is None:
            errs.append({"field": h("run_country"), "message": "Give the country as a two-letter code or its name, and the state or region of that country."})
        else:
            p["run_location"] = place
    elif r.get("run_region") or r.get("run_city"):
        errs.append({"field": h("run_country"), "message": "Give the country where it runs."})
    if r.get("data_locations"):
        places = []
        for x in _split(r["data_locations"]):
            city, _, code = x.rpartition(",") if "," in x else ("", "", x)
            code = code.strip().upper()
            place = _place(db, code.split("-")[0], code if "-" in code else None, city.strip() or None)
            if place is None:
                errs.append({"field": h("data_locations"), "message": f"'{x}' is not a place. Use a country code (DE), a state code (US-IL), or a city and its state code (New York, US-NY)."})
            else:
                places.append(place)
        p["data_locations"] = places
    if r.get("laws"):
        if not can_add_law:
            errs.append({"field": h("laws"), "message": "You do not have the right to add laws to a system. Leave this column blank."})
        else:
            p["regulation_ids"] = [x for x in (_law(db, name, h("laws"), errs) for name in _split(r["laws"])) if x]
    return p, errs


def _codes(v: str, col: Column, head: str, errs: list) -> list[str]:
    out = []
    for x in _split(v):
        code = _match(x, col.labels)
        if code is None:
            errs.append({"field": head, "message": f"'{x}' is not one of: {', '.join(col.labels.values())}."})
        else:
            out.append(code)
    return list(dict.fromkeys(out))


def _place(db: Session, country: str, region: str | None, city: str | None) -> dict | None:
    from app.reference.jurisdictions import _find_subdivision, by_code, norm
    from app.reference.models import Jurisdiction

    c = by_code(db, country.strip().upper()) if country else None
    if c is None or c.level != "country":
        target = norm(country)
        c = next((j for j in db.scalars(select(Jurisdiction).where(Jurisdiction.level == "country")) if norm(j.name) == target or target in {norm(a) for a in (j.aliases or [])}), None)
    if c is None:
        return None
    out = {"country": c.code}
    if region:
        st = _find_subdivision(db, c, region)
        if st is None:
            return None
        out["region"] = st.code
    if city:
        out["city"] = " ".join(city.split())[:120]
    return out


def _law(db: Session, name: str, head: str, errs: list) -> str | None:
    from app.laws.models import Regulation

    target = " ".join(name.split()).casefold()
    hits = [r for r in db.scalars(select(Regulation).where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None)))
            if " ".join(r.short_name.split()).casefold() == target or (r.label and " ".join(r.label.split()).casefold() == target)]
    if not hits:
        errs.append({"field": head, "message": f"'{name}' is not a law in the law library. Use the name exactly as the law library shows it."})
        return None
    if len(hits) > 1:
        errs.append({"field": head, "message": f"'{name}' matches {len(hits)} laws. Use the law's full name as the law library shows it."})
        return None
    return hits[0].id


def import_csv(db: Session, actor: User, org: Organization, text_or_rows, editable_depts: set[str] | None, *, can_add_law: bool = True) -> dict:
    warnings: list[dict] = []
    rows, errors = parse_import(db, org, text_or_rows, editable_depts, can_add_law=can_add_law, warnings=warnings)
    if errors:
        return {"created": 0, "errors": errors} | ({"warnings": warnings} if warnings else {})
    for _, payload in rows:
        laws = payload.pop("regulation_ids", [])
        s = svc.create_system(db, actor, org, payload, origin="csv", reason="Imported from CSV")
        for rid in laws:
            svc.add_law(db, actor, s, rid, reason="Imported from CSV")
    if rows:
        audit.record(db, actor_id=actor.id, action="register.csv_import", organization_id=org.id, object_type="RegisterSystem", summary=f"Imported {len(rows)} AI systems from CSV")
    return {"created": len(rows), "errors": []} | ({"warnings": warnings} if warnings else {})


# ---- import from inventory
def import_inventory(db: Session, actor: User, org: Organization) -> dict:
    existing = {s.dedupe_key or svc_key(s, db): s for s in db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org.id, RegisterSystem.deleted_at.is_(None)))}
    tools = list(db.scalars(select(AITool).where(AITool.organization_id == org.id, AITool.deleted_at.is_(None)).order_by(AITool.vendor, AITool.product)))
    approved = list(db.scalars(select(UseCase).where(UseCase.organization_id == org.id, UseCase.deleted_at.is_(None), UseCase.status == "dept_approved").order_by(UseCase.name)))
    groups: dict[str, dict] = {}
    for t in tools:
        if t.approval_status == "not_approved" and t.source != "attestation":
            continue
        k = dedupe_key(t.vendor, t.product)
        g = groups.setdefault(k, {"vendor": t.vendor, "product": t.product, "tools": [], "use_cases": []})
        g["tools"].append(t)
    by_tool = {t.id: dedupe_key(t.vendor, t.product) for t in tools}
    loose: list[UseCase] = []
    for uc in approved:
        keys = {by_tool[i] for i in uc.tool_ids or [] if i in by_tool and by_tool[i] in groups}
        if not keys:
            loose.append(uc)
        for k in keys:
            groups[k]["use_cases"].append(uc)
    created = skipped = 0
    for k, g in groups.items():
        if k in existing:
            skipped += 1
            continue
        s = _create_from_group(db, actor, org, k, g)
        existing[k] = s
        created += 1
    for uc in loose:
        k = dedupe_key(None, uc.name)
        if k in existing or any(f"use_case:{uc.id}" in (s.source_refs or []) for s in existing.values()):
            skipped += 1
            continue
        s = _create_from_group(db, actor, org, k, {"vendor": None, "product": uc.name, "tools": [], "use_cases": [uc]})
        existing[k] = s
        created += 1
    audit.record(db, actor_id=actor.id, action="register.import_inventory", organization_id=org.id, object_type="RegisterSystem",
                 after={"created": created, "already_in_register": skipped}, summary=f"Imported {created} AI systems from the inventory ({skipped} already in the register)")
    return {"created": created, "already_in_register": skipped}


def svc_key(s: RegisterSystem, db: Session) -> str:
    from app.systems.models import Vendor

    v = db.get(Vendor, s.vendor_id) if s.vendor_id else None
    return dedupe_key(v.legal_name if v else None, s.name)


def _create_from_group(db: Session, actor: User, org: Organization, key: str, g: dict) -> RegisterSystem:
    tools: list[AITool] = g["tools"]
    ucs: list[UseCase] = g["use_cases"]
    is_agent = any(t.kind == "agent" for t in tools)
    only_personal = bool(tools) and all(t.account_type in SHADOW_ACCOUNTS for t in tools)
    own = {" ".join((n or "").split()).casefold() for n in (org.name, org.legal_name, org.trading_name) if n}
    if g["vendor"] and " ".join(g["vendor"].split()).casefold() in own:
        g = g | {"vendor": None}  # the company's own model: built in-house, not a vendor
    first = ucs[0] if ucs else None
    depts = {u.department_id for u in ucs}
    cats = sorted({DATA_MAP[c] for u in ucs for c in (u.data_categories or []) if c in DATA_MAP})
    impact_rank = {"none": 0, "informs": 1, "consequential": 2}
    impact = max((u.decision_impact for u in ucs if u.decision_impact in impact_rank), key=lambda x: impact_rank[x], default=None)
    purpose_parts = [u.purpose or u.name for u in ucs]
    if len(depts) > 1:
        names = [d.name for d in (db.get(Department, i) for i in depts) if d]
        purpose_parts.append(f"Used by {', '.join(sorted(names))}.")
    payload: dict = {
        "name": g["product"][:160],
        # tools staff declared in the attestation with no approved use case are usually chat tools; the user corrects the type
        "type": "agent" if is_agent else ("genai_chat_tool" if only_personal or (not ucs and all(t.source == "attestation" for t in tools)) else ("vendor_app" if g["vendor"] else "in_house_model")),
        "sourcing": "shadow" if only_personal else ("vendor" if g["vendor"] else "in_house"),
        "stage": "proposed",
        "purpose": " ".join(purpose_parts) or None,
        "department_id": first.department_id if first and len(depts) == 1 else None,
        "department_ids": sorted(depts) if len(depts) > 1 else None,  # 11-03 C9: the departments that use it
        "decision_impact": impact,
        "data": {"data_categories": cats} if cats else None,
    }
    if g["vendor"]:
        payload["vendor_name"] = g["vendor"]
    # a tool used in several departments stays unassigned, for the AI Compliance Officer to place or mark company-wide
    v = svc.clean(db, org, {k: val for k, val in payload.items() if val is not None}, require_department=False)
    s = svc.create_system(db, actor, org, payload, origin="inventory", reason="Imported from the inventory", cleaned=v)
    s.dedupe_key = key
    s.source_refs = [f"tool:{t.id}" for t in tools] + [f"use_case:{u.id}" for u in ucs]
    return s
