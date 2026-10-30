"""The AI system register: validation, create and edit with a field-level change log, laws, risk tier (spec §24.4–§24.6)."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.core.ids import new_id
from app.register.models import (
    AUTONOMY, CONSENT_BASIS, DECISION_IMPACT, SOURCING, STAGES, TRAINS_ON_DATA, TYPES, BiasTest, ChangeLog, RegisterSystem, RegisterSystemAction,
    RegisterSystemData, RegisterSystemLaw,
)
from app.systems.models import Vendor
from app.tenancy.models import Department, Organization, User

TYPE_LABELS = {"agent": "AI agent", "vendor_app": "Vendor app with AI", "embedded_feature": "Embedded AI feature", "foundation_model_api": "Foundation model / API",
               "in_house_model": "In-house model", "genai_chat_tool": "Generative AI chat tool"}
SOURCING_LABELS = {"vendor": "Bought from vendor", "in_house": "Built in-house", "contractor": "Built by contractor", "shadow": "Free or personal tool (shadow AI)"}
STAGE_LABELS = {"proposed": "Proposed", "in_development": "In development / procurement", "ready_for_go_live": "Ready for go-live", "live": "Live", "retired": "Retired"}
AI_PROVIDERS = {"openai": "OpenAI", "anthropic": "Anthropic", "azure_openai": "Microsoft Azure OpenAI", "google": "Google", "amazon_bedrock": "Amazon Bedrock",
                "meta_open": "Meta (open model)", "in_house": "In-house model", "unknown": "Unknown, vendor did not disclose"}
ALGORITHM_TYPES = {"llm_agent": "Large language model (LLM) agent", "llm": "Large language model (LLM)", "ranking": "Ranking or scoring model", "classifier": "Classifier",
                   "regression": "Regression", "computer_vision": "Computer vision", "speech": "Speech analysis", "rules_ml": "Rules plus machine learning", "other": "Other"}
HOSTING = {"vendor_cloud_us": "Vendor cloud (US)", "vendor_cloud_eu": "Vendor cloud (EU)", "vendor_cloud_other": "Vendor cloud (other region)", "our_cloud": "Our cloud tenant", "on_premises": "On premises"}
TRAINS_LABELS = {"no": "No, contractually excluded", "yes": "Yes", "unknown": "Unknown"}
VENDOR_DOCS = {"contract_ai_terms": "Contract with AI terms", "dpa": "Data processing agreement", "model_card": "Model card or system documentation",
               "vendor_bias_audit": "Vendor's own bias audit", "security_report": "Security report (SOC 2 or ISO 27001)", "incident_clause": "Incident notice clause"}
AUTONOMY_LABELS = {"suggest_only": "Suggests only; a person acts", "acts_with_approval": "Acts, but a person approves first-time or unusual actions", "autonomous": "Acts on its own"}
AGENTASSURE = {"planned": "Futran AgentAssure: planned", "passed": "Futran AgentAssure: passed", "vendor_only": "Vendor testing only", "none": "None"}
ACTION_CODES = {"read_records": "Read records", "send_email": "Send email", "write_calendar": "Write to calendars", "change_records": "Change records in a system of record",
                "decide_people": "Reject or advance people", "make_payments": "Make payments", "search_knowledge": "Search internal knowledge", "other": "Other"}
DECISION_LABELS = {"none": "No effect on decisions about people", "informs": "Supports a decision a person makes", "consequential": "Makes or substantially makes the decision"}
DATA_CATEGORIES = {"personal": "Personal information", "health": "Health information", "biometric": "Biometric data (face, voice)", "sensitive": "Sensitive categories (race, sex, age)",
                   "children": "Children's data", "confidential": "Company confidential"}
DATA_SUBJECTS = {"candidates": "Job candidates", "employees": "Employees", "customers": "Customers", "public": "Members of the public", "none": "No personal data"}
CONSENT_LABELS = {"consent": "Consent obtained", "notice_only": "Notice given", "other_lawful_basis": "Lawful basis recorded", "not_obtained": "Consent not obtained", "na": "Not applicable"}
CROSS_BORDER = {"no": "No", "eu": "Yes, to the EU", "india": "Yes, to India", "other": "Yes, other"}
USERS_SCOPE = {"role": "Role level", "named": "Named users"}
PERSONAL = {"personal", "health", "biometric", "sensitive", "children"}

FIELD_LABELS = {
    "name": "Name", "type": "Type", "sourcing": "Built or bought", "department_id": "Department", "stage": "Stage", "purpose": "Purpose", "users_scope": "Who uses it",
    "users_description": "Users", "user_count": "Number of users", "owner_user_id": "System owner", "vendor_id": "Vendor", "ai_provider": "Underlying AI provider",
    "model_name": "Model name", "model_version": "Model version", "algorithm_type": "Algorithm type", "hosting": "Hosting", "vendor_trains_on_data": "Vendor trains on our data",
    "vendor_documents": "Vendor documents received", "autonomy": "How much it acts on its own", "guardrail_policy_ref": "Runtime controls", "agentassure_status": "Pre-release testing",
    "decision_impact": "Effect on decisions about people", "risk_tier": "Risk tier", "company_wide": "Company-wide", "bias_next_due": "Next bias test due",
    "data_categories": "Data used", "data_subjects": "Whose data", "consent_basis": "Consent or lawful basis", "consent_ref": "Consent date or version",
    "consent_evidence_id": "Consent evidence", "retention_period": "Retention period", "cross_border": "Data leaves the country", "actions": "Actions and tools", "laws": "Laws that apply",
    "created": "Added to the register", "evidence": "Evidence", "history": "History log", "retired_reason": "Retirement reason", "go_live": "Go-live", "history_answers": "History questions",
}
SYSTEM_FIELDS = ("name", "type", "sourcing", "department_id", "stage", "purpose", "users_scope", "users_description", "user_count", "owner_user_id", "vendor_id", "ai_provider",
                 "model_name", "model_version", "algorithm_type", "hosting", "vendor_trains_on_data", "vendor_documents", "autonomy", "guardrail_policy_ref", "agentassure_status",
                 "decision_impact", "company_wide", "bias_next_due")
DATA_FIELDS = ("data_categories", "data_subjects", "consent_basis", "consent_ref", "consent_evidence_id", "retention_period", "cross_border")
CODE_LABELS = {"type": TYPE_LABELS, "sourcing": SOURCING_LABELS, "stage": STAGE_LABELS, "ai_provider": AI_PROVIDERS, "algorithm_type": ALGORITHM_TYPES, "hosting": HOSTING,
               "vendor_trains_on_data": TRAINS_LABELS, "vendor_documents": VENDOR_DOCS, "autonomy": AUTONOMY_LABELS, "agentassure_status": AGENTASSURE,
               "decision_impact": DECISION_LABELS, "data_categories": DATA_CATEGORIES, "data_subjects": DATA_SUBJECTS, "consent_basis": CONSENT_LABELS,
               "cross_border": CROSS_BORDER, "users_scope": USERS_SCOPE}


# ---- small helpers
def _text(v, limit: int) -> str | None:
    s = " ".join(str(v or "").split()) if not isinstance(v, str) or "\n" not in v else str(v).strip()
    return s[:limit] or None


def _date(v, field: str, errs: list) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        errs.append({"field": field, "message": "Enter a date."})
        return None


def _choice(v, allowed, field: str, message: str, errs: list, *, required: bool = False) -> str | None:
    if v in (None, ""):
        if required:
            errs.append({"field": field, "message": message})
        return None
    if v not in allowed:
        errs.append({"field": field, "message": message})
        return None
    return v


def _codes(v, allowed: dict, field: str, errs: list) -> list[str]:
    if v in (None, ""):
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x in allowed for x in v):
        errs.append({"field": field, "message": "Choose from the list."})
        return []
    return list(dict.fromkeys(v))


def _user(db: Session, org_id: str, v, field: str, errs: list) -> str | None:
    if not v:
        return None
    u = db.get(User, v) if isinstance(v, str) else None
    if u is None or u.deleted_at is not None or u.organization_id != org_id:
        errs.append({"field": field, "message": "Choose a person from the company's users."})
        return None
    return u.id


def next_reference(db: Session, org_id: str) -> str:
    """AIS-001, AIS-002 … per client. Removed systems keep their number."""
    refs = db.scalars(select(RegisterSystem.reference).where(RegisterSystem.organization_id == org_id))
    n = max((int(r[4:]) for r in refs if r and r[4:].isdigit()), default=0)
    return f"AIS-{n + 1:03d}"


def data_row(db: Session, s: RegisterSystem) -> RegisterSystemData | None:
    return db.scalar(select(RegisterSystemData).where(RegisterSystemData.register_system_id == s.id, RegisterSystemData.deleted_at.is_(None)))


def actions_of(db: Session, s: RegisterSystem) -> list[RegisterSystemAction]:
    return list(db.scalars(select(RegisterSystemAction).where(RegisterSystemAction.register_system_id == s.id, RegisterSystemAction.deleted_at.is_(None)).order_by(RegisterSystemAction.created_at, RegisterSystemAction.id)))


def law_links(db: Session, s: RegisterSystem, *, include_removed: bool = False) -> list[RegisterSystemLaw]:
    stmt = select(RegisterSystemLaw).where(RegisterSystemLaw.register_system_id == s.id, RegisterSystemLaw.deleted_at.is_(None))
    if not include_removed:
        stmt = stmt.where(RegisterSystemLaw.status != "removed")
    return list(db.scalars(stmt.order_by(RegisterSystemLaw.created_at)))


def latest_bias_test(db: Session, s: RegisterSystem) -> BiasTest | None:
    return db.scalar(select(BiasTest).where(BiasTest.register_system_id == s.id, BiasTest.deleted_at.is_(None)).order_by(BiasTest.tested_on.desc(), BiasTest.created_at.desc()).limit(1))


# ---- risk tier (§11 applied to the register: first match wins)
def calc_tier(s: RegisterSystem, d: RegisterSystemData | None) -> tuple[int, str]:
    cats = set(d.data_categories or []) if d else set()
    subjects = [DATA_SUBJECTS[x].lower() for x in (d.data_subjects or []) if x in DATA_SUBJECTS and x != "none"] if d else []
    if s.decision_impact == "consequential":
        return 3, "makes or substantially makes decisions about people" + (f" ({', '.join(subjects)})" if subjects else "")
    reasons = [DATA_CATEGORIES[c].split(" (")[0].lower().replace("information", "data") for c in DATA_CATEGORIES if c in cats]
    if s.sourcing == "shadow":
        reasons.append("free or personal account")
    if s.type == "agent" and s.autonomy in ("acts_with_approval", "autonomous"):
        reasons.append("acts on its own" + (" with approval" if s.autonomy == "acts_with_approval" else ""))
    if reasons:
        return 2, ", ".join(reasons[:1] + subjects + reasons[1:])
    return 1, "no personal or confidential data and no decisions about people"


def apply_tier(db: Session, s: RegisterSystem) -> None:
    s.risk_tier, s.risk_tier_reason = calc_tier(s, data_row(db, s))


# ---- change log
def display(db: Session, field: str, value) -> str | None:
    if value is None or value == "" or value == []:
        return None
    if field == "department_id":
        d = db.get(Department, value)
        return d.name if d else value
    if field in ("owner_user_id",):
        u = db.get(User, value)
        return u.name if u else value
    if field == "vendor_id":
        v = db.get(Vendor, value)
        return v.legal_name if v else value
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, date):
        return value.isoformat()
    labels = CODE_LABELS.get(field)
    if isinstance(value, list):
        return ", ".join(labels.get(x, x) if labels else str(x) for x in value)
    if labels:
        return labels.get(value, value)
    return str(value)


def log_change(db: Session, actor: User | None, s: RegisterSystem, field: str, old, new, reason: str | None, *, entity: str = "RegisterSystem", entity_id: str | None = None, batch_id: str | None = None, raw: bool = False) -> ChangeLog:
    row = ChangeLog(organization_id=s.organization_id, entity=entity, entity_id=entity_id or s.id, register_system_id=s.id, field=field,
                    old_value=old if raw else display(db, field, old), new_value=new if raw else display(db, field, new), reason=reason, batch_id=batch_id,
                    user_id=actor.id if actor else None, at=utcnow())
    db.add(row)
    return row


# ---- validation
def clean(db: Session, org: Organization, data: dict, current: RegisterSystem | None = None, *, require_department: bool = True) -> dict:
    """Validate a create or edit payload. Returns {system fields present} plus "_data", "_actions" and "_vendor_name" when given."""
    errs: list[dict] = []
    out: dict = {}
    creating = current is None

    def has(k):
        return k in data or creating

    if has("name"):
        name = _text(data.get("name"), 1000) or ""
        if not name:
            errs.append({"field": "name", "message": "Enter the AI system's name."})
        elif len(name) > 160:
            errs.append({"field": "name", "message": "The name must be 160 characters or fewer."})
        out["name"] = name
    if has("type"):
        out["type"] = _choice(data.get("type"), TYPES, "type", "Choose the type of AI system.", errs, required=True)
    if has("sourcing"):
        out["sourcing"] = _choice(data.get("sourcing"), SOURCING, "sourcing", "Say whether it was built or bought.", errs, required=True)
    if has("stage"):
        out["stage"] = _choice(data.get("stage") or "proposed", STAGES, "stage", "Choose a stage.", errs)
    if "purpose" in data:
        out["purpose"] = str(data.get("purpose") or "").strip()[:4000] or None
    if "users_scope" in data:
        out["users_scope"] = _choice(data.get("users_scope"), USERS_SCOPE, "users_scope", "Choose role level or named users.", errs)
    if "users_description" in data:
        out["users_description"] = _text(data.get("users_description"), 300)
    if "user_count" in data:
        v = data.get("user_count")
        if v in (None, ""):
            out["user_count"] = None
        else:
            try:
                n = int(v)
                if n < 0:
                    raise ValueError
                out["user_count"] = n
            except (TypeError, ValueError):
                errs.append({"field": "user_count", "message": "Enter a whole number."})
    if "department_id" in data:
        d = data.get("department_id")
        if d:
            dept = db.get(Department, d) if isinstance(d, str) else None
            if dept is None or dept.deleted_at is not None or dept.organization_id != org.id:
                errs.append({"field": "department_id", "message": "Choose a department."})
        out["department_id"] = d or None
    if "company_wide" in data:
        out["company_wide"] = bool(data.get("company_wide"))
    if "owner_user_id" in data:
        out["owner_user_id"] = _user(db, org.id, data.get("owner_user_id"), "owner_user_id", errs)
    if "vendor_id" in data:
        v = data.get("vendor_id")
        if v:
            vendor = db.get(Vendor, v) if isinstance(v, str) else None
            if vendor is None or vendor.deleted_at is not None or vendor.organization_id != org.id:
                errs.append({"field": "vendor_id", "message": "Choose a vendor from the company vendor register."})
        out["vendor_id"] = v or None
    if data.get("vendor_name"):
        out["_vendor_name"] = _text(data.get("vendor_name"), 200)
    for f, allowed, msg in (("ai_provider", AI_PROVIDERS, "Choose the underlying AI provider."), ("algorithm_type", ALGORITHM_TYPES, "Choose the algorithm type."),
                            ("hosting", HOSTING, "Choose where it is hosted."), ("vendor_trains_on_data", TRAINS_ON_DATA, "Answer yes, no or unknown."),
                            ("agentassure_status", AGENTASSURE, "Choose the pre-release testing."), ("decision_impact", DECISION_IMPACT, "Choose the effect on decisions about people."),
                            ("autonomy", AUTONOMY, "Choose how much it acts on its own.")):
        if f in data:
            out[f] = _choice(data.get(f), allowed, f, msg, errs)
    for f, limit in (("model_name", 160), ("model_version", 80), ("guardrail_policy_ref", 120)):
        if f in data:
            out[f] = _text(data.get(f), limit)
    if "vendor_documents" in data:
        out["vendor_documents"] = _codes(data.get("vendor_documents"), VENDOR_DOCS, "vendor_documents", errs)
    if "bias_next_due" in data:
        out["bias_next_due"] = _date(data.get("bias_next_due"), "bias_next_due", errs)
    if "data" in data and data["data"] is not None:
        dd = data["data"] if isinstance(data["data"], dict) else {}
        dv: dict = {}
        if "data_categories" in dd:
            dv["data_categories"] = _codes(dd.get("data_categories"), DATA_CATEGORIES, "data.data_categories", errs)
        if "data_subjects" in dd:
            dv["data_subjects"] = _codes(dd.get("data_subjects"), DATA_SUBJECTS, "data.data_subjects", errs)
        if "consent_basis" in dd:
            dv["consent_basis"] = _choice(dd.get("consent_basis"), CONSENT_BASIS, "data.consent_basis", "Say whether consent was obtained.", errs)
        if "consent_ref" in dd:
            dv["consent_ref"] = _text(dd.get("consent_ref"), 300)
        if "retention_period" in dd:
            dv["retention_period"] = _text(dd.get("retention_period"), 80)
        if "cross_border" in dd:
            dv["cross_border"] = _choice(dd.get("cross_border"), CROSS_BORDER, "data.cross_border", "Say whether the data leaves the country.", errs)
        if "consent_evidence_id" in dd:
            dv["consent_evidence_id"] = _file(db, org.id, dd.get("consent_evidence_id"), "data.consent_evidence_id", errs)
        out["_data"] = dv
    if "actions" in data and data["actions"] is not None:
        acts = data["actions"]
        if not isinstance(acts, list) or not all(isinstance(a, dict) and a.get("action_code") in ACTION_CODES for a in acts):
            errs.append({"field": "actions", "message": "Choose actions from the list."})
        else:
            out["_actions"] = [{"action_code": a["action_code"], "description": _text(a.get("description"), 300)} for a in acts]
            if any(a["action_code"] == "other" and not a["description"] for a in out["_actions"]):
                errs.append({"field": "actions", "message": "Describe the other action."})
    # cross-field rules
    final_type = out.get("type", current.type if current else None)
    final_dept = out.get("department_id", current.department_id if current else None)
    final_cw = out.get("company_wide", current.company_wide if current else False)
    if final_type and final_type != "agent":
        if out.get("autonomy") or (out.get("_actions")):
            errs.append({"field": "autonomy", "message": "Autonomy and actions apply to AI agents only."})
    if require_department and not final_dept and not final_cw and (creating or "department_id" in data):
        errs.append({"field": "department_id", "message": "Choose the department that owns it, or mark it company-wide."})
    if errs:
        raise Invalid(errors=errs)
    if out.get("stage") == "live" and (current is None or current.stage != "live"):
        raise Conflict("Live needs the AI Compliance Officer's approval. Use Submit for go-live approval.")
    return out


def _file(db: Session, org_id: str, v, field: str, errs: list) -> str | None:
    if not v:
        return None
    from app.files.models import FileObject

    f = db.get(FileObject, v) if isinstance(v, str) else None
    if f is None or f.deleted_at is not None or f.organization_id != org_id:
        errs.append({"field": field, "message": "Upload the file again."})
        return None
    return f.id


def _vendor_by_name(db: Session, actor: User, org: Organization, name: str) -> Vendor:
    v = db.scalar(select(Vendor).where(Vendor.organization_id == org.id, Vendor.deleted_at.is_(None), func.lower(Vendor.legal_name) == name.lower()))
    if v is None:
        from app.systems.service import save_vendor

        v = save_vendor(db, actor, org, {"legal_name": name})
    return v


# ---- create and edit
def _snapshot(db: Session, s: RegisterSystem) -> dict:
    d = data_row(db, s)
    out = {f: getattr(s, f) for f in SYSTEM_FIELDS}
    out.update({f: (getattr(d, f) if d else ([] if f in ("data_categories", "data_subjects") else None)) for f in DATA_FIELDS})
    out["actions"] = [a.action_code if a.action_code != "other" else f"other: {a.description}" for a in actions_of(db, s)]
    return out


def _write(db: Session, actor: User, org: Organization, s: RegisterSystem, v: dict) -> None:
    vendor_name = v.pop("_vendor_name", None)
    if vendor_name and not v.get("vendor_id"):
        v["vendor_id"] = _vendor_by_name(db, actor, org, vendor_name).id
    dv = v.pop("_data", None)
    acts = v.pop("_actions", None)
    for k, val in v.items():
        setattr(s, k, val)
    if s.type != "agent":
        s.autonomy = None
    db.flush()
    if dv is not None:
        d = data_row(db, s)
        if d is None:
            d = RegisterSystemData(organization_id=s.organization_id, register_system_id=s.id, data_categories=[], data_subjects=[], created_by=actor.id)
            db.add(d)
        for k, val in dv.items():
            setattr(d, k, val)
        d.updated_by = actor.id
    if acts is not None or s.type != "agent":
        for a in actions_of(db, s):
            a.deleted_at = utcnow()
        for a in (acts or []) if s.type == "agent" else []:
            db.add(RegisterSystemAction(organization_id=s.organization_id, register_system_id=s.id, created_by=actor.id, **a))
    db.flush()
    apply_tier(db, s)


def create_system(db: Session, actor: User, org: Organization, data: dict, *, origin: str = "manual", reason: str | None = None, cleaned: dict | None = None) -> RegisterSystem:
    v = dict(cleaned) if cleaned is not None else clean(db, org, data)
    vendor_name = v.pop("_vendor_name", None)
    if vendor_name and not v.get("vendor_id"):
        v["vendor_id"] = _vendor_by_name(db, actor, org, vendor_name).id
    s = RegisterSystem(organization_id=org.id, reference=next_reference(db, org.id), origin=origin, created_by=actor.id, updated_by=actor.id,
                       vendor_documents=[], source_refs=[], history_answers={}, company_wide=False, name=v.get("name"), type=v.get("type"), sourcing=v.get("sourcing"))
    db.add(s)
    _write(db, actor, org, s, v)
    log_change(db, actor, s, "created", None, f"{s.reference} {s.name}", reason, raw=True)
    _engine_facts_changed(db, s)
    audit.record(db, actor_id=actor.id, action="register.create", obj=s, after={"name": s.name, "reference": s.reference, "stage": s.stage, "origin": origin},
                 summary=f"Added {s.reference} {s.name} to the AI system register")
    return s


def update_system(db: Session, actor: User, s: RegisterSystem, data: dict, *, reason: str | None = None, batch_id: str | None = None, cleaned: dict | None = None) -> dict:
    """Apply an edit and log each changed field. Returns {field: (old, new)} of what changed."""
    org = db.get(Organization, s.organization_id)
    v = cleaned if cleaned is not None else clean(db, org, data, current=s)
    if "name" in v and not v["name"]:
        v.pop("name")
    before = _snapshot(db, s)
    tier_before = s.risk_tier
    _write(db, actor, org, s, v)
    s.updated_by = actor.id
    after = _snapshot(db, s)
    changed = {k: (before[k], after[k]) for k in after if before.get(k) != after[k]}
    for k, (old, new) in changed.items():
        log_change(db, actor, s, k, old, new, reason, batch_id=batch_id)
    if set(changed) & ENGINE_FACTS or ("stage" in changed and "retired" in changed["stage"]):
        _engine_facts_changed(db, s)
    if s.risk_tier != tier_before:
        log_change(db, actor, s, "risk_tier", f"Tier {tier_before}" if tier_before else None, f"Tier {s.risk_tier}", "Recalculated from the system's data and decisions.", batch_id=batch_id, raw=True)
    if changed:
        audit.record(db, actor_id=actor.id, action="register.edit", obj=s, before={k: display(db, k, o) for k, (o, _) in changed.items()},
                     after={k: display(db, k, n) for k, (_, n) in changed.items()} | ({"reason": reason} if reason else {}), summary=f"Edited {s.reference} {s.name}")
    return changed


def retire(db: Session, actor: User, s: RegisterSystem, reason: str) -> RegisterSystem:
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why the system is being retired."}])
    if s.stage == "retired":
        raise Conflict("This system is already retired.")
    old = s.stage
    s.stage, s.retired_reason, s.updated_by = "retired", reason[:2000], actor.id
    _engine_facts_changed(db, s)
    log_change(db, actor, s, "stage", old, "retired", reason)
    audit.record(db, actor_id=actor.id, action="register.retire", obj=s, before={"stage": old}, after={"stage": "retired", "reason": reason}, summary=f"Retired {s.reference} {s.name}")
    return s


def duplicate(db: Session, actor: User, s: RegisterSystem) -> RegisterSystem:
    org = db.get(Organization, s.organization_id)
    d = data_row(db, s)
    payload = {f: getattr(s, f) for f in SYSTEM_FIELDS if f not in ("stage", "bias_next_due")} | {"name": f"{s.name} (copy)"[:160], "stage": "proposed"}
    if d:
        payload["data"] = {f: getattr(d, f) for f in DATA_FIELDS}
    if s.type == "agent":
        payload["actions"] = [{"action_code": a.action_code, "description": a.description} for a in actions_of(db, s)]
    copy = create_system(db, actor, org, payload, origin="duplicate", reason=f"Copied from {s.reference} {s.name}")
    for link in law_links(db, s):
        if link.status == "active":
            db.add(RegisterSystemLaw(organization_id=copy.organization_id, register_system_id=copy.id, regulation_id=link.regulation_id, source=link.source, status="active", added_by=actor.id, created_by=actor.id))
    db.flush()
    return copy


def get_system(db: Session, system_id: str) -> RegisterSystem:
    s = db.get(RegisterSystem, system_id)
    if s is None or s.deleted_at is not None:
        raise NotFound()
    return s


def systems_for(db: Session, org_id: str, department_ids: set[str] | None) -> list[RegisterSystem]:
    stmt = select(RegisterSystem).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None))
    rows = list(db.scalars(stmt.order_by(RegisterSystem.reference)))
    if department_ids is None:
        return rows
    return [s for s in rows if s.company_wide or s.department_id in department_ids]


# ---- laws
def current_regulation(db: Session, regulation_id: str):
    """Follow edits to the newest version of a law (Regulation rows are replaced on edit)."""
    from app.laws.models import Regulation

    r = db.get(Regulation, regulation_id)
    seen = set()
    while r is not None and r.superseded_by_id and r.id not in seen:
        seen.add(r.id)
        r = db.get(Regulation, r.superseded_by_id)
    return r


def add_law(db: Session, actor: User, s: RegisterSystem, regulation_id: str, *, source: str = "manual", reason: str | None = None, batch_id: str | None = None) -> RegisterSystemLaw | None:
    from app.laws.models import Regulation

    reg = db.get(Regulation, regulation_id) if isinstance(regulation_id, str) else None
    if reg is None:
        raise Invalid(errors=[{"field": "regulation_id", "message": "Choose a law from the law library."}])
    reg = current_regulation(db, reg.id)
    for link in law_links(db, s):
        cur = current_regulation(db, link.regulation_id)
        if cur is not None and cur.id == reg.id:
            return None  # already there
    link = RegisterSystemLaw(organization_id=s.organization_id, register_system_id=s.id, regulation_id=reg.id, source=source if source in ("suggested", "manual") else "manual",
                             status="active", added_by=actor.id, created_by=actor.id)
    db.add(link)
    db.flush()
    log_change(db, actor, s, "laws", None, f"Added {reg.short_name}", reason, entity="RegisterSystemLaw", entity_id=link.id, batch_id=batch_id, raw=True)
    audit.record(db, actor_id=actor.id, action="register.law_add", obj=s, after={"regulation": reg.short_name}, summary=f"Added {reg.short_name} to {s.reference} {s.name}")
    after_laws_change(db, s)
    return link


def remove_law(db: Session, actor: User, s: RegisterSystem, link: RegisterSystemLaw, *, reason: str | None, direct: bool, batch_id: str | None = None) -> RegisterSystemLaw:
    """The AI Compliance Officer removes directly; anyone else asks, and the law stays until the officer approves (§24.3)."""
    reason = " ".join(str(reason or "").split()) or None
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why this law no longer applies."}])
    reg = current_regulation(db, link.regulation_id)
    name = reg.short_name if reg else "law"
    if direct:
        link.status, link.approved_by, link.removal_reason = "removed", actor.id, reason
        log_change(db, actor, s, "laws", f"{name}", f"Removed {name}", reason, entity="RegisterSystemLaw", entity_id=link.id, batch_id=batch_id, raw=True)
        audit.record(db, actor_id=actor.id, action="register.law_remove", obj=s, before={"regulation": name}, after={"reason": reason}, summary=f"Removed {name} from {s.reference} {s.name}")
        after_laws_change(db, s)
    else:
        if link.status == "removal_pending":
            raise Conflict("Removing this law is already waiting for the AI Compliance Officer.")
        link.status, link.removal_requested_by, link.removal_reason = "removal_pending", actor.id, reason
        log_change(db, actor, s, "laws", f"{name}", f"Asked to remove {name}", reason, entity="RegisterSystemLaw", entity_id=link.id, batch_id=batch_id, raw=True)
        audit.record(db, actor_id=actor.id, action="register.law_remove_request", obj=s, after={"regulation": name, "reason": reason}, summary=f"Asked to remove {name} from {s.reference} {s.name}")
        from app.notifications.service import notify

        notify(db, compliance_officers(db, s.organization_id, exclude=actor.id), "register_law_removal", f"Approve removing {name} from {s.name}", f"Asked by {actor.name}. Reason: {reason}", f"/register/{s.id}")
    return link


def decide_law_removal(db: Session, actor: User, s: RegisterSystem, link: RegisterSystemLaw, approve: bool, comment: str | None) -> RegisterSystemLaw:
    from app.policy.sod import assert_not_self_approval

    if link.status != "removal_pending":
        raise Conflict("Nobody has asked to remove this law.")
    assert_not_self_approval(actor.id, link.removal_requested_by)
    reg = current_regulation(db, link.regulation_id)
    name = reg.short_name if reg else "law"
    if approve:
        link.status, link.approved_by = "removed", actor.id
        log_change(db, actor, s, "laws", name, f"Removed {name}", link.removal_reason, entity="RegisterSystemLaw", entity_id=link.id, raw=True)
        after_laws_change(db, s)
    else:
        link.status = "active"
        log_change(db, actor, s, "laws", f"Asked to remove {name}", f"Kept {name}", comment, entity="RegisterSystemLaw", entity_id=link.id, raw=True)
    audit.record(db, actor_id=actor.id, action="register.law_removal_decided", obj=s, after={"regulation": name, "approved": approve, "comment": comment},
                 summary=f"{'Approved' if approve else 'Declined'} removing {name} from {s.reference} {s.name}")
    return link


def after_laws_change(db: Session, s: RegisterSystem) -> None:
    """Required roles are computed from the laws on read, so a change takes effect at once (§24.3). The client's
    applicability is re-run when the request commits (§25.4)."""
    db.flush()
    _engine_facts_changed(db, s)


# fields the applicability engine reads from a register system (regmaster.engine._facts)
ENGINE_FACTS = {"decision_impact", "type", "department_id", "name", "purpose"}


def _engine_facts_changed(db: Session, s: RegisterSystem) -> None:
    from app.regmaster.engine import rerun_later

    rerun_later(db, s.organization_id)


def compliance_officers(db: Session, org_id: str, exclude: str | None = None) -> list[User]:
    from app.tenancy.models import RoleAssignment

    ids = set(db.scalars(select(RoleAssignment.user_id).where(RoleAssignment.organization_id == org_id, RoleAssignment.role == "caico", RoleAssignment.deleted_at.is_(None))))
    return [u for u in (db.get(User, i) for i in ids) if u is not None and u.deleted_at is None and u.id != exclude]


# ---- statuses shown on the grid
def bias_status(db: Session, s: RegisterSystem, today: date | None = None) -> dict:
    today = today or utcnow().date()
    last = latest_bias_test(db, s)
    affects_people = s.decision_impact in ("informs", "consequential")
    if last is not None:
        due = last.next_due or (last.tested_on + timedelta(days=365))
        overdue = due < today or (today - last.tested_on).days > 365
        return {"last_tested_on": last.tested_on.isoformat(), "next_due": due.isoformat(), "overdue": overdue, "result": last.result,
                "label": "Overdue: over 12 months" if overdue else f"Next due {due.isoformat()}", "null_compliance": (last.unknown_share or 0) > 50}
    if not affects_people:
        return {"last_tested_on": None, "next_due": None, "overdue": False, "result": None, "label": "Not required", "null_compliance": False}
    if s.stage == "live":
        return {"last_tested_on": None, "next_due": s.bias_next_due.isoformat() if s.bias_next_due else None, "overdue": True, "result": None, "label": "Not done", "null_compliance": False}
    return {"last_tested_on": None, "next_due": s.bias_next_due.isoformat() if s.bias_next_due else None, "overdue": False, "result": None, "label": "Due before go-live", "null_compliance": False}


def consent_status(d: RegisterSystemData | None) -> tuple[str, bool]:
    """(label, missing). Missing = not obtained, or personal data with nothing recorded."""
    basis = d.consent_basis if d else None
    personal = bool(PERSONAL & set(d.data_categories or [])) if d else False
    if basis:
        return CONSENT_LABELS[basis], basis == "not_obtained"
    return ("Not recorded", personal) if personal else ("Not recorded", False)


def new_batch_id() -> str:
    return new_id()


def suggested_laws(db: Session, s: RegisterSystem) -> list[dict]:
    """Laws the applicability engine found in scope for the company (§25.4) that are not yet on this system.

    Uses the engine's result (`regmaster.engine.in_scope_versions`). Before the engine has run for a client, the laws
    in scope on its engagement (ClientRequirement) are suggested instead."""
    from app.engagements.models import ClientRequirement
    from app.regmaster.engine import in_scope_versions
    from app.regmaster.models import ClientLawApplicability

    have = set()
    for link in law_links(db, s):
        cur = current_regulation(db, link.regulation_id)
        if cur is not None:
            have.add(cur.id)
    ran = db.scalar(select(ClientLawApplicability.id).where(ClientLawApplicability.organization_id == s.organization_id, ClientLawApplicability.deleted_at.is_(None)).limit(1)) is not None
    if ran:
        reasons = {r.regulation_id: r.reason_text for r in db.scalars(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == s.organization_id, ClientLawApplicability.deleted_at.is_(None)))}
        pairs = [(reg.id, reasons.get(reg.id)) for reg, _v in in_scope_versions(db, s.organization_id)]
    else:
        pairs = [(r.regulation_id, r.reason_text) for r in db.scalars(select(ClientRequirement).where(ClientRequirement.organization_id == s.organization_id, ClientRequirement.deleted_at.is_(None),
                                                                                                      ClientRequirement.in_scope.is_(True), ClientRequirement.regulation_id.is_not(None)))]
    out, seen = [], set()
    for rid, reason in pairs:
        reg = current_regulation(db, rid)
        if reg is None or reg.id in have or reg.id in seen:
            continue
        seen.add(reg.id)
        out.append({"regulation_id": reg.id, "short_name": reg.short_name, "reason": reason})
    return sorted(out, key=lambda x: x["short_name"])
