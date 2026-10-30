"""Seeding the register: CSV import and "Import from inventory" (spec §24.4; v0.6 plan, WS-B integration).

Import from inventory is an action the user runs, never a background job. Approved use cases and the tools and agents
declared in the inventory become proposed register rows, one per vendor and product however many account types or use
cases mention it. Running it again adds only what is new.
"""
import csv
import io

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.errors import Invalid
from app.inventory.models import AITool, UseCase
from app.register import service as svc
from app.register.models import RegisterSystem
from app.tenancy.models import Department, Organization, User

IMPORT_HEADER = ["name", "type", "sourcing", "department", "stage", "purpose", "vendor", "ai_provider", "model_name", "decision_impact", "owner_email"]
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


def parse_import(db: Session, org: Organization, text: str, editable_depts: set[str] | None) -> tuple[list[tuple[int, dict]], list[dict]]:
    """Rows as create payloads, and every error with its row number. Rows are checked with the same validation as the form."""
    errors: list[dict] = []
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except (StopIteration, csv.Error):
        return [], [{"row": 1, "field": "file", "message": "The file is empty or could not be read. Save it as CSV from the template."}]
    if header[: len(IMPORT_HEADER)] != IMPORT_HEADER:
        return [], [{"row": 1, "field": "header", "message": f"The first row must be: {','.join(IMPORT_HEADER)}. Download the template and copy your rows into it."}]
    depts = {" ".join(d.name.split()).casefold(): d for d in db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None)))}
    rows: list[tuple[int, dict]] = []
    try:
        for n, raw in enumerate(reader, start=2):
            if not any(c.strip() for c in raw):
                continue
            if len(rows) >= MAX_ROWS:
                errors.append({"row": n, "field": "file", "message": f"Only the first {MAX_ROWS} rows can be imported at once."})
                break
            r = {h: (raw[i].strip() if i < len(raw) else "") for i, h in enumerate(IMPORT_HEADER)}
            row_errs: list[dict] = []
            payload: dict = {"name": r["name"], "purpose": r["purpose"] or None, "model_name": r["model_name"] or None}
            for f, labels in (("type", svc.TYPE_LABELS), ("sourcing", svc.SOURCING_LABELS), ("ai_provider", svc.AI_PROVIDERS), ("decision_impact", svc.DECISION_LABELS)):
                if r[f]:
                    code = _match(r[f], labels)
                    if code is None:
                        row_errs.append({"field": f, "message": f"'{r[f]}' is not one of: {', '.join(labels.values())}."})
                    payload[f] = code
                elif f in ("type", "sourcing"):
                    payload[f] = None
            stage = _match(r["stage"], svc.STAGE_LABELS) if r["stage"] else "proposed"
            if stage == "live":
                row_errs.append({"field": "stage", "message": "Live needs go-live approval for each system. Import it as Ready for go-live, then submit it."})
            elif stage is None:
                row_errs.append({"field": "stage", "message": "Use Proposed, In development, Ready for go-live or Retired."})
            payload["stage"] = stage if stage != "live" else "ready_for_go_live"
            dept = depts.get(" ".join(r["department"].split()).casefold()) if r["department"] else None
            if dept is None:
                row_errs.append({"field": "department", "message": f"'{r['department']}' is not a department. Add it under People first." if r["department"] else "Enter the department."})
            elif editable_depts is not None and dept.id not in editable_depts:
                row_errs.append({"field": "department", "message": f"You can add systems only to your own department, not {dept.name}."})
            payload["department_id"] = dept.id if dept else None
            if r["vendor"]:
                payload["vendor_name"] = r["vendor"]
            if r["owner_email"]:
                u = db.scalar(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None), func.lower(User.email) == r["owner_email"].lower()))
                if u is None:
                    row_errs.append({"field": "owner_email", "message": f"No user with the email {r['owner_email']}."})
                else:
                    payload["owner_user_id"] = u.id
            if not row_errs:
                try:
                    svc.clean(db, org, payload)
                except Invalid as e:
                    row_errs += [{"field": x["field"].replace("_id", "").replace("department", "department"), "message": x["message"]} for x in e.errors]
            seen = {x["field"] for x in row_errs}
            if not r["name"] and "name" not in seen:
                row_errs.append({"field": "name", "message": "Enter the AI system's name."})
            if not r["type"] and "type" not in seen:
                row_errs.append({"field": "type", "message": "Enter the type."})
            errors += [{"row": n, **e} for e in row_errs]
            rows.append((n, payload))
    except csv.Error:
        return [], [{"row": 0, "field": "file", "message": "The file could not be read. Save it as CSV (comma delimited) from the template and try again."}]
    return rows, errors


def import_csv(db: Session, actor: User, org: Organization, text: str, editable_depts: set[str] | None) -> dict:
    rows, errors = parse_import(db, org, text, editable_depts)
    if errors:
        return {"created": 0, "errors": errors}
    for _, payload in rows:
        svc.create_system(db, actor, org, payload, origin="csv", reason="Imported from CSV")
    if rows:
        audit.record(db, actor_id=actor.id, action="register.csv_import", organization_id=org.id, object_type="RegisterSystem", summary=f"Imported {len(rows)} AI systems from CSV")
    return {"created": len(rows), "errors": []}


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
