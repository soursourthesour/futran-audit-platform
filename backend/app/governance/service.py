"""AI governance structure request: setup, answers, commitments, coverage and submit (spec §10.5)."""
import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid
from app.engagements.models import Engagement
from app.governance.models import Commitment, GovernanceItem, GovernanceRequest
from app.initiation.context import eu_operations
from app.reference.models import GovernanceCatalogItem
from app.tenancy.models import Organization, User

STATUSES = ("in_place", "planned", "not_applicable")
OECD_KEYS = ["1.2", "1.3", "1.4", "1.5"]
NIST_KEYS = ["GOVERN", "MAP", "MEASURE", "MANAGE"]
EU_CONTACT = "GR-08"

# Template §4.1–4.2 engagement-level facts not covered by the catalog items (spec §18.4 line on §4.1–4.2).
EXTRA_FIELDS = [
    {"key": "board_oversight", "label": "Board-level AI oversight (named person)", "type": "text"},
    {"key": "policy_owner", "label": "AI policy owner", "type": "text"},
    {"key": "policy_last_updated", "label": "AI policy last updated", "type": "date"},
    {"key": "policy_covers_employees", "label": "AI policy covers employee use of AI", "type": "choice", "options": ["yes", "no"]},
    {"key": "policy_covers_client_facing", "label": "AI policy covers client-facing AI", "type": "choice", "options": ["yes", "no"]},
    {"key": "risk_appetite", "label": "AI risk appetite statement", "type": "choice", "options": ["yes", "no", "informal"]},
    {"key": "incident_escalation", "label": "AI incident escalation path", "type": "text"},
    {"key": "model_risk_manager", "label": "Model risk manager (banking and financial services)", "type": "text"},
    {"key": "data_steward", "label": "Data steward or data owner", "type": "text"},
    {"key": "ethics_lead", "label": "AI ethics lead", "type": "text"},
    {"key": "security_owner", "label": "Security owner for AI", "type": "text"},
    {"key": "privacy_officer", "label": "Privacy officer or DPO", "type": "text"},
    {"key": "third_party_owner", "label": "Third-party AI oversight owner", "type": "text"},
    {"key": "raci_exists", "label": "RACI for AI exists", "type": "choice", "options": ["yes", "no", "partial"]},
]
EXTRA_KEYS = {f["key"]: f for f in EXTRA_FIELDS}


def current_request(db: Session, e: Engagement) -> GovernanceRequest | None:
    return db.scalar(select(GovernanceRequest).where(GovernanceRequest.engagement_id == e.id, GovernanceRequest.deleted_at.is_(None)).order_by(GovernanceRequest.created_at.desc()).limit(1))


def items(db: Session, req: GovernanceRequest) -> list[GovernanceItem]:
    return list(db.scalars(select(GovernanceItem).where(GovernanceItem.request_id == req.id, GovernanceItem.deleted_at.is_(None)).order_by(GovernanceItem.order)))


def catalog(db: Session) -> list[GovernanceCatalogItem]:
    return list(db.scalars(select(GovernanceCatalogItem).order_by(GovernanceCatalogItem.order)))


def default_codes(db: Session, org: Organization) -> list[str]:
    eu = eu_operations(db, org)
    return [c.code for c in catalog(db) if not c.optional and (c.conditional != "eu_operations" or eu)]


def _set_items(db: Session, req: GovernanceRequest, codes: list[str]) -> None:
    org = db.get(Organization, req.organization_id)
    cat = {c.code: c for c in catalog(db)}
    unknown = [c for c in codes if c not in cat]
    if unknown:
        raise Invalid(errors=[{"field": "codes", "message": f"Unknown item {unknown[0]}."}])
    if EU_CONTACT in codes and not eu_operations(db, org):
        raise Invalid(errors=[{"field": "codes", "message": "The EU representative contact applies only to clients with operations in the EU."}])
    if not codes:
        raise Invalid(errors=[{"field": "codes", "message": "Choose at least one item."}])
    current = {i.catalog_code: i for i in items(db, req)}
    order = {c.code: n for n, c in enumerate(catalog(db))}
    for code in codes:
        if code not in current:
            c = cat[code]
            db.add(GovernanceItem(organization_id=req.organization_id, request_id=req.id, engagement_id=req.engagement_id, catalog_code=code, kind=c.kind, title=c.title, description=c.description, control_refs=c.control_refs or [], committee=c.committee, optional=c.optional, order=order[code]))
    for code, it in current.items():
        if code not in codes:
            it.deleted_at = utcnow()
    req.items_selected = list(codes)
    db.flush()


def create_request(db: Session, actor: User, e: Engagement, codes: list[str] | None = None, due_date: date | None = None) -> GovernanceRequest:
    org = db.get(Organization, e.client_id)
    req = GovernanceRequest(organization_id=e.client_id, engagement_id=e.id, requested_by=actor.id, due_date=due_date or e.letter_due or (today() + timedelta(days=14)), status="open", created_by=actor.id)
    db.add(req)
    db.flush()
    _set_items(db, req, codes if codes is not None else default_codes(db, org))
    audit.record(db, actor_id=actor.id, action="governance.request", obj=req, summary=f"Requested the AI governance structure ({len(req.items_selected)} items)")
    return req


def update_setup(db: Session, actor: User, req: GovernanceRequest, codes: list[str], due_date: date | None) -> GovernanceRequest:
    if req.status != "open" or any(i.status != "unanswered" for i in items(db, req)):
        raise Conflict("The client has started answering, so the item list can no longer change.")
    _set_items(db, req, list(dict.fromkeys(codes)))
    if due_date:
        req.due_date = due_date
    audit.record(db, actor_id=actor.id, action="governance.setup", obj=req, after={"codes": req.items_selected, "due_date": req.due_date.isoformat() if req.due_date else None}, summary=f"Set the governance request to {len(req.items_selected)} items")
    return req


def _lower_first(title: str) -> str:
    """'AI acceptable use policy' keeps its acronym; 'Bias and fairness …' becomes 'bias and fairness …'."""
    return title if title[1:2].isupper() else title[:1].lower() + title[1:]


def _commitment_text(it: GovernanceItem) -> str:
    if it.kind != "role":
        return f"Create {_lower_first(it.title)}"
    return f"{'Constitute' if it.committee else 'Appoint'} {_lower_first(it.title)}"


def answer_item(db: Session, actor: User, it: GovernanceItem, payload: dict) -> GovernanceItem:
    req = db.get(GovernanceRequest, it.request_id)
    if req.status != "open":
        raise Conflict("The governance request has been submitted. Ask your Futran Chief Auditor if an answer must change.")
    status = payload.get("status")
    errs: list[dict] = []
    payload = {k: (v if k in ("names",) or v is None or isinstance(v, str) else str(v)) for k, v in payload.items()}
    if not isinstance(payload.get("names"), list):
        payload["names"] = []
    if not isinstance(status, str) or status not in STATUSES:
        raise Invalid(errors=[{"field": "status", "message": "Choose an answer."}])
    names = [{"name": " ".join(str(n.get("name", "")).split())[:120], "title": " ".join(str(n.get("title") or "").split())[:120] or None} for n in payload.get("names") or [] if isinstance(n, dict) and str(n.get("name", "")).strip()]
    target = None
    if status == "in_place":
        if it.kind == "role" and not names and not (payload.get("chair") or "").strip():
            errs.append({"field": "names", "message": "Name the people who hold this role."})
        if it.kind != "role" and not it.file_ids:
            errs.append({"field": "file", "message": "Upload the document first."})
    elif status == "planned":
        try:
            target = date.fromisoformat(str(payload.get("target_date") or ""))
            if target <= today():
                errs.append({"field": "target_date", "message": "The target date must be in the future."})
        except ValueError:
            errs.append({"field": "target_date", "message": "Enter a target date."})
        if not (payload.get("interim_owner") or "").strip():
            errs.append({"field": "interim_owner", "message": "Name an interim owner."})
    elif not (payload.get("na_reason") or "").strip():
        errs.append({"field": "na_reason", "message": "Say why this does not apply."})
    if errs:
        raise Invalid(errors=errs)
    before = {"status": it.status}
    it.status = status
    it.names = names if status == "in_place" else []
    it.chair = (payload.get("chair") or "").strip()[:120] or None if status == "in_place" else None
    mc = str(payload.get("member_count") or "").strip()
    it.member_count = int(mc) if status == "in_place" and mc.isascii() and mc.isdecimal() and len(mc) < 6 else None
    it.meeting_frequency = (payload.get("meeting_frequency") or "").strip()[:40] or None if status == "in_place" else None
    it.target_date = target
    it.interim_owner = payload["interim_owner"].strip()[:120] if status == "planned" else None
    it.planned_members = (payload.get("planned_members") or "").strip() or None if status == "planned" else None
    it.na_reason = payload["na_reason"].strip() if status == "not_applicable" else None
    it.answered_by, it.answered_at = actor.id, utcnow()
    c = db.scalar(select(Commitment).where(Commitment.source_id == it.id, Commitment.deleted_at.is_(None)))
    if status == "planned":
        if c is None:
            c = Commitment(organization_id=it.organization_id, engagement_id=it.engagement_id, source="governance_role" if it.kind == "role" else "governance_document", source_id=it.id, description=_commitment_text(it), target_date=target, owner=it.interim_owner, status="open", created_by=actor.id)
            db.add(c)
        else:
            c.target_date, c.owner = target, it.interim_owner
    elif c is not None:
        c.deleted_at = utcnow()  # the answer changed, so the promise no longer stands
    db.flush()
    audit.record(db, actor_id=actor.id, action="governance.answer", obj=it, before=before, after={"status": status, "target_date": target.isoformat() if target else None}, summary=f"Answered '{it.title}': {status.replace('_', ' ')}")
    return it


def attach_file(db: Session, settings, actor: User, it: GovernanceItem, data: bytes, filename: str, content_type: str | None) -> GovernanceItem:
    from app.files.service import upload

    req = db.get(GovernanceRequest, it.request_id)
    if req.status != "open":
        raise Conflict("The governance request has been submitted.")
    f = upload(db, settings, actor, data=data, filename=filename, content_type=content_type, organization_id=it.organization_id, engagement_id=it.engagement_id, linked_type="governance_document", linked_id=it.id)
    it.file_ids = [*(it.file_ids or []), f.id]
    if it.kind != "role":
        c = db.scalar(select(Commitment).where(Commitment.source_id == it.id, Commitment.deleted_at.is_(None)))
        if c is not None:
            c.deleted_at = utcnow()
        it.status, it.target_date, it.interim_owner, it.na_reason = "in_place", None, None, None
        it.answered_by, it.answered_at = actor.id, utcnow()
    elif it.committee:
        it.terms_of_reference_file_id = f.id
    db.flush()
    return it


def save_extra(db: Session, actor: User, req: GovernanceRequest, fields: dict) -> dict:
    if req.status != "open":
        raise Conflict("The governance request has been submitted.")
    clean = dict(req.extra_fields or {})
    for k, v in fields.items():
        spec = EXTRA_KEYS.get(k)
        if spec is None:
            continue
        v = " ".join(str(v or "").split())[:300]
        if spec["type"] == "choice" and v and v not in spec["options"]:
            raise Invalid(errors=[{"field": k, "message": "Choose one of the options."}])
        if spec["type"] == "date" and v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise Invalid(errors=[{"field": k, "message": "Enter a date as YYYY-MM-DD."}])
        if v:
            clean[k] = v
        else:
            clean.pop(k, None)
    req.extra_fields = clean
    return clean


def submit(db: Session, settings, actor: User, req: GovernanceRequest, accuracy_confirmed: bool) -> GovernanceRequest:
    from app.initiation.models import PackageDocument
    from app.initiation.service import current_package
    from app.notifications.service import futran_team, notify

    if req.status != "open":
        raise Conflict("This request has already been submitted.")
    open_items = [i for i in items(db, req) if i.status == "unanswered"]
    if open_items:
        n = len(open_items)
        raise Invalid(f"{n} {'item still needs' if n == 1 else 'items still need'} an answer.", [{"field": i.catalog_code, "message": f"{i.title} still needs an answer."} for i in open_items])
    if not accuracy_confirmed:
        raise Invalid("Confirm the answers are accurate before submitting.", [{"field": "accuracy_confirmed", "message": "Confirm the answers are accurate as of today."}])
    req.status, req.submitted_by, req.submitted_at, req.accuracy_confirmed = "submitted", actor.id, utcnow(), True
    e = db.get(Engagement, req.engagement_id)
    pkg = current_package(db, e)
    doc = db.scalar(select(PackageDocument).where(PackageDocument.package_id == pkg.id, PackageDocument.item == 7)) if pkg else None
    if doc is not None and doc.completed_at is None:
        doc.completed_at, doc.completed_by = utcnow(), actor.id
    org = db.get(Organization, e.client_id)
    planned = sum(1 for i in items(db, req) if i.status == "planned")
    notify(db, futran_team(db, e), "governance_submitted", f"{org.name}: AI governance structure submitted", f"Submitted by {actor.name}, with {planned} commitments to create or constitute items.", f"/clients/{org.id}/governance", engagement=e, settings=settings)
    audit.record(db, actor_id=actor.id, action="governance.submit", obj=req, summary=f"Submitted the AI governance structure ({planned} commitments)")
    from app.engagements.gates import advance_if_ready

    if e.stage == 3:
        advance_if_ready(db, actor, e)
    return req


def _keys(refs: list[str]) -> tuple[set[str], set[str]]:
    oecd, nist = set(), set()
    for r in refs or []:
        m = re.match(r"OECD\s+(\d\.\d)", r)
        if m:
            oecd.add(m.group(1))
        m = re.match(r"NIST_AI_RMF\s+([A-Z]+)", r)
        if m:
            nist.add(m.group(1))
    return oecd, nist


def _grade(statuses: list[str]) -> str | None:
    s = [x for x in statuses if x != "not_applicable"]
    if not s:
        return None
    in_place, planned, missing = s.count("in_place"), s.count("planned"), s.count("unanswered")
    if not missing and not planned:
        return "covered"
    if not missing:
        return "planned"
    if not in_place and not planned:
        return "gap"
    return "partial"


def coverage(its: list[GovernanceItem]) -> dict:
    """Coverage per OECD principle and NIST AI RMF function: covered, planned, partial or gap."""
    by_oecd: dict[str, list[str]] = {}
    by_nist: dict[str, list[str]] = {}
    for it in its:
        oecd, nist = _keys(it.control_refs)
        for k in oecd:
            by_oecd.setdefault(k, []).append(it.status)
        for k in nist:
            by_nist.setdefault(k, []).append(it.status)
    oecd_out = {k: g for k in OECD_KEYS if k in by_oecd and (g := _grade(by_oecd[k]))}
    nist_out = {k: g for k in NIST_KEYS if k in by_nist and (g := _grade(by_nist[k]))}
    return {"oecd": oecd_out, "nist": nist_out}
