"""Employee attestation campaign: launch, public form, tracker (spec §9.5, §15; schematic D13)."""
import secrets
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.attestation.models import Attestation, AttestationCampaign
from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import AppError, Conflict, Invalid, NotFound
from app.engagements.models import Engagement
from app.initiation.models import PackageDocument
from app.initiation.service import current_package
from app.tenancy.models import Department, Organization, User

MIN_AGGREGATE = 3  # spec §15: no department count below 3 is shown (re-identification)
TOOLS = [
    {"value": "chatgpt", "label": "ChatGPT"},
    {"value": "copilot", "label": "Microsoft Copilot"},
    {"value": "claude", "label": "Claude"},
    {"value": "gemini", "label": "Gemini"},
    {"value": "in_app", "label": "AI inside another app (for example an ATS or CRM)"},
    {"value": "other", "label": "Another AI tool"},
]
ACCOUNT_TYPES = [
    {"value": "personal_free", "label": "Personal, free"},
    {"value": "personal_paid", "label": "Personal, paid"},
    {"value": "company", "label": "Company account"},
    {"value": "unknown", "label": "Not sure"},
]
PURPOSES = [
    {"value": "writing", "label": "Writing and editing"},
    {"value": "research", "label": "Research and summaries"},
    {"value": "code", "label": "Writing or reviewing code"},
    {"value": "analysis", "label": "Data analysis and spreadsheets"},
    {"value": "media", "label": "Images, audio or video"},
    {"value": "customer", "label": "Messages to customers or candidates"},
    {"value": "decisions", "label": "Decisions about people (hiring, performance, customers)"},
    {"value": "other", "label": "Something else"},
]
DATA_CATEGORIES = [
    {"value": "pii", "label": "Personal information about people (names, contact details, CVs)"},
    {"value": "phi", "label": "Health information"},
    {"value": "client", "label": "Client or customer data"},
    {"value": "confidential", "label": "Confidential company information"},
    {"value": "none", "label": "None of these"},
]
POLICY_TEXT = (
    "Use only AI tools the company has approved for work. Do not enter personal, health, client or confidential "
    "information into a personal AI account. Check AI output before you rely on it, and tell your manager if an AI "
    "tool produces something harmful or wrong."
)
DATA_SHORT = {"pii": "Personal information", "phi": "Health information", "client": "Client data", "confidential": "Confidential information", "none": "None"}
PURPOSE_LABELS = {p["value"]: p["label"] for p in PURPOSES}
TOOL_LABELS = {t["value"]: t["label"] for t in TOOLS}
ACCOUNT_LABELS = {a["value"]: a["label"] for a in ACCOUNT_TYPES}


class Gone(AppError):
    status_code = 410


def current_campaign(db: Session, e: Engagement) -> AttestationCampaign | None:
    return db.scalar(select(AttestationCampaign).where(AttestationCampaign.engagement_id == e.id, AttestationCampaign.deleted_at.is_(None)).order_by(AttestationCampaign.launched_at.desc()).limit(1))


def is_open(c: AttestationCampaign) -> bool:
    return c.status == "open" and c.closes_at > utcnow()


def notice_acknowledged(db: Session, e: Engagement) -> bool:
    pkg = current_package(db, e)
    doc = db.scalar(select(PackageDocument).where(PackageDocument.package_id == pkg.id, PackageDocument.item == 5)) if pkg else None
    return doc is not None and doc.completed_at is not None


def launch(db: Session, actor: User, e: Engagement, department_ids: list[str], closes_at: datetime, policy_version: str) -> AttestationCampaign:
    if not notice_acknowledged(db, e):
        raise Conflict("The Chief AI Compliance Officer must acknowledge the employee data notice before the campaign starts (New York Civil Rights Law §52-c).")
    current = current_campaign(db, e)
    if current is not None and is_open(current):
        raise Conflict("A campaign is already running. Close it before starting another.")
    depts = {d.id for d in db.scalars(select(Department).where(Department.organization_id == e.client_id, Department.deleted_at.is_(None), Department.in_scope.is_(True)))}
    chosen = [d for d in dict.fromkeys(department_ids) if d in depts]
    if not chosen:
        raise Invalid(errors=[{"field": "department_ids", "message": "Choose at least one department in scope."}])
    closes = closes_at.replace(tzinfo=None) if closes_at.tzinfo else closes_at
    if closes <= utcnow():
        raise Invalid(errors=[{"field": "closes_at", "message": "The closing date must be in the future."}])
    c = AttestationCampaign(organization_id=e.client_id, engagement_id=e.id, policy_version=(policy_version or "1.0").strip()[:40], launched_by=actor.id, launched_at=utcnow(), closes_at=closes, department_ids=chosen, link_token=secrets.token_urlsafe(24), status="open", created_by=actor.id)
    db.add(c)
    db.flush()
    audit.record(db, actor_id=actor.id, action="attestation.launch", obj=c, summary=f"Launched the AI use attestation for {len(chosen)} departments, closing {closes:%B %d, %Y}")
    return c


def close(db: Session, actor: User, c: AttestationCampaign) -> AttestationCampaign:
    if c.status != "closed":
        c.status, c.closed_at = "closed", utcnow()
        audit.record(db, actor_id=actor.id, action="attestation.close", obj=c, summary="Closed the AI use attestation campaign")
    return c


def by_token(db: Session, token: str) -> AttestationCampaign:
    c = db.scalar(select(AttestationCampaign).where(AttestationCampaign.link_token == token, AttestationCampaign.deleted_at.is_(None)))
    if c is None:
        raise NotFound("This link is not valid. Ask your compliance team for the current link.")
    return c


def public_view(db: Session, c: AttestationCampaign) -> dict:
    """Only what an employee needs to answer: no names, counts or other answers."""
    org = db.get(Organization, c.organization_id)
    depts = db.scalars(select(Department).where(Department.id.in_(c.department_ids)).order_by(Department.name))
    return {
        "client_name": org.name, "policy_version": c.policy_version, "policy_text": POLICY_TEXT,
        "departments": [{"id": d.id, "name": d.name} for d in depts], "tools": TOOLS, "account_types": ACCOUNT_TYPES,
        "purposes": PURPOSES, "data_categories": DATA_CATEGORIES, "closes_at": c.closes_at.isoformat(), "open": is_open(c),
    }


def _clean(payload: dict, c: AttestationCampaign) -> dict:
    errs = []
    name = " ".join(str(payload.get("respondent_name") or "").split())[:120]
    if not name:
        errs.append({"field": "respondent_name", "message": "Enter your name."})
    email = str(payload.get("respondent_email") or "").strip().lower()[:254] or None
    if email and ("@" not in email or " " in email):
        errs.append({"field": "respondent_email", "message": "Enter a valid email address, or leave it blank."})
    if payload.get("department_id") not in c.department_ids:
        errs.append({"field": "department_id", "message": "Choose your department."})
    uses = bool(payload.get("uses_ai"))
    tools = []
    for t in payload.get("tools_declared") or [] if uses else []:
        if not isinstance(t, dict) or t.get("tool") not in TOOL_LABELS or t.get("account_type") not in ACCOUNT_LABELS:
            errs.append({"field": "tools_declared", "message": "Choose each tool and the account you use it with."})
            break
        tools.append({"tool": t["tool"], "account_type": t["account_type"], "name": " ".join(str(t.get("name") or "").split())[:80] or None})
    if uses and not tools:
        errs.append({"field": "tools_declared", "message": "Choose the AI tools you use, or say you don't use AI for work."})
    valid_p, valid_d = {p["value"] for p in PURPOSES}, {d["value"] for d in DATA_CATEGORIES}
    purposes = [p for p in payload.get("purposes") or [] if p in valid_p] if uses else []
    data = [d for d in payload.get("data_entered") or [] if d in valid_d] if uses else []
    if not payload.get("policy_acknowledged"):
        errs.append({"field": "policy_acknowledged", "message": "Confirm you have read the AI use policy."})
    if errs:
        raise Invalid(errors=errs)
    return {"respondent_name": name, "respondent_email": email, "department_id": payload["department_id"], "uses_ai": uses, "tools_declared": tools, "purposes": purposes, "data_entered": data, "policy_acknowledged": True}


def submit(db: Session, token: str, payload: dict, request=None) -> Attestation:
    c = by_token(db, token)
    if not is_open(c):
        raise Gone("This check-in has closed. Thank you; no answer is needed now.")
    values = _clean(payload, c)
    a = None
    if values["respondent_email"]:
        a = db.scalar(select(Attestation).where(Attestation.campaign_id == c.id, func.lower(Attestation.respondent_email) == values["respondent_email"]))
    if a is None:
        a = Attestation(organization_id=c.organization_id, campaign_id=c.id, engagement_id=c.engagement_id, **values, submitted_at=utcnow())
        db.add(a)
    else:
        for k, v in values.items():
            setattr(a, k, v)
        a.submitted_at = utcnow()
    db.flush()
    audit.record(db, actor_id=None, actor_name=values["respondent_name"], action="attestation.submit", obj=a, request=request, summary="An employee submitted the AI use check-in")
    try:
        from app.inventory.service import upsert_tools_from_attestation  # wired when the AI inventory lands (Task 21)
    except ImportError:
        return a
    upsert_tools_from_attestation(db, a)
    return a


def _label(t: dict) -> str:
    base = t.get("name") if t["tool"] in ("in_app", "other") and t.get("name") else TOOL_LABELS[t["tool"]]
    return f"{base} · {ACCOUNT_LABELS[t['account_type']].lower()}"


def tracker(db: Session, actor, c: AttestationCampaign, *, dept_scope: set[str] | None, individuals: bool) -> dict:
    """Counts by department (masked below 3) and tools declared; individual answers only when `individuals`."""
    rows = list(db.scalars(select(Attestation).where(Attestation.campaign_id == c.id, Attestation.deleted_at.is_(None))))
    if dept_scope is not None:
        rows = [r for r in rows if r.department_id in dept_scope]
    depts = list(db.scalars(select(Department).where(Department.id.in_(c.department_ids)).order_by(Department.name)))
    if dept_scope is not None:
        depts = [d for d in depts if d.id in dept_scope]
    names = {d.id: d.name for d in depts}
    out_depts = []
    for d in depts:
        n = sum(1 for r in rows if r.department_id == d.id)
        out_depts.append({"id": d.id, "name": d.name, "responses": n if n >= MIN_AGGREGATE or n == 0 else "fewer than 3", "headcount": d.headcount})
    tools: dict[str, int] = {}
    for r in rows:
        for t in r.tools_declared or []:
            tools[_label(t)] = tools.get(_label(t), 0) + 1
    personal = sum(1 for r in rows if any(t["account_type"].startswith("personal") for t in r.tools_declared or []))
    total_mask = len(rows) if len(rows) >= MIN_AGGREGATE or len(rows) == 0 or individuals else "fewer than 3"
    result = {
        "campaign": {"id": c.id, "status": "open" if is_open(c) else "closed", "policy_version": c.policy_version, "launched_at": c.launched_at.isoformat(), "closes_at": c.closes_at.isoformat(), "closed_at": c.closed_at.isoformat() if c.closed_at else None, "link": f"/attest/{c.link_token}" if individuals else None},
        "totals": {"responses": total_mask, "use_ai": sum(r.uses_ai for r in rows) if individuals or len(rows) >= MIN_AGGREGATE else None, "personal_accounts": personal if individuals or len(rows) >= MIN_AGGREGATE else None, "headcount": sum(d.headcount or 0 for d in depts) or None},
        "departments": out_depts,
        "tools": sorted(({"label": k, "count": v} for k, v in tools.items()), key=lambda x: -x["count"]) if individuals or len(rows) >= MIN_AGGREGATE else [],
        "individuals": None,
    }
    if individuals:
        result["individuals"] = [
            {"id": r.id, "name": r.respondent_name, "email": r.respondent_email, "department": names.get(r.department_id), "uses_ai": r.uses_ai, "tools": [_label(t) for t in r.tools_declared or []], "purposes": [PURPOSE_LABELS.get(p, p) for p in r.purposes or []], "data_entered": [DATA_SHORT.get(d, d) for d in r.data_entered or []], "submitted_at": r.submitted_at.isoformat()}
            for r in sorted(rows, key=lambda r: r.submitted_at, reverse=True)
        ]
        audit.record(db, actor_id=actor.id, action="attestation.view_individual", obj=c, summary=f"Viewed {len(rows)} individual attestation answers")
    return result
