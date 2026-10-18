"""Findings (spec §9.6, §18.6): drafting by auditors. Review and approval: see `review` below (Task 29)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.errors import Conflict, Invalid
from app.engagements.models import Engagement
from app.findings.models import SEVERITIES, Finding
from app.inventory.models import UseCase
from app.systems.models import AISystem
from app.tenancy.models import User

DEFAULT_DUE_DAYS = {"critical": 30, "high": 90, "medium": 182, "low": 365, "observation": 365}
EDITABLE = ("draft", "returned")


def findings_for(db: Session, e: Engagement) -> list[Finding]:
    return list(db.scalars(select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None)).order_by(Finding.ref)))


def _clean(db: Session, e: Engagement, data: dict, partial: bool) -> dict:
    out: dict = {}
    errs = []

    def text(key: str, limit: int, required: bool = False):
        if key in data or not partial:
            v = " ".join(str(data.get(key) or "").split()) if key == "title" else str(data.get(key) or "").strip()
            if required and not v:
                errs.append({"field": key, "message": "Enter a title." if key == "title" else "This is required."})
            out[key] = v[:limit] or None

    text("title", 300, required=True)
    text("description", 20000)
    text("recommended_remediation", 8000)
    text("proposed_owner", 160)
    text("template_section", 8)
    if "severity" in data or not partial:
        if data.get("severity") not in SEVERITIES:
            errs.append({"field": "severity", "message": "Choose critical, high, medium, low or observation."})
        else:
            out["severity"] = data["severity"]
    if "control_refs" in data:
        refs = data.get("control_refs")
        if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
            errs.append({"field": "control_refs", "message": "Choose the controls this finding relates to."})
        else:
            out["control_refs"] = list(dict.fromkeys(r.strip()[:200] for r in refs if r.strip()))[:20]
    if "use_case_ids" in data:
        ids = data.get("use_case_ids")
        ok = isinstance(ids, list) and all(isinstance(i, str) for i in ids)
        ucs = [db.get(UseCase, i) for i in ids] if ok else []
        if not ok or any(u is None or u.engagement_id != e.id or u.deleted_at is not None for u in ucs):
            errs.append({"field": "use_case_ids", "message": "Choose use cases from this engagement."})
        else:
            out["use_case_ids"] = list(dict.fromkeys(ids))
    if "ai_system_id" in data:
        sid = data.get("ai_system_id")
        s = db.get(AISystem, sid) if isinstance(sid, str) and sid else None
        if sid and (s is None or s.engagement_id != e.id or s.deleted_at is not None):
            errs.append({"field": "ai_system_id", "message": "Choose a system from this engagement."})
        else:
            out["ai_system_id"] = s.id if s else None
    if "null_compliance_flag" in data:
        out["null_compliance_flag"] = data.get("null_compliance_flag") is True
    if errs:
        raise Invalid(errors=errs)
    return out


def create_finding(db: Session, actor: User, e: Engagement, data: dict) -> Finding:
    from app.questionnaire.service import next_finding_ref

    v = _clean(db, e, data, partial=False)
    f = Finding(organization_id=e.client_id, engagement_id=e.id, ref=next_finding_ref(db, e), author_id=actor.id, status="draft", origin="manual",
                source_question_ids=[], control_refs=v.pop("control_refs", []), use_case_ids=v.pop("use_case_ids", []), created_by=actor.id, **v)
    db.add(f)
    db.flush()
    audit.record(db, actor_id=actor.id, action="finding.create", obj=f, after={"ref": f.ref, "severity": f.severity, "title": f.title}, summary=f"Drafted finding {f.ref}: {f.title[:120]}")
    return f


def update_finding(db: Session, actor: User, f: Finding, data: dict) -> Finding:
    if f.status not in EDITABLE:
        raise Conflict("Only a draft or returned finding can be edited.")
    e = db.get(Engagement, f.engagement_id)
    v = _clean(db, e, data, partial=True)
    before = {k: getattr(f, k) for k in v}
    for k, val in v.items():
        setattr(f, k, val)
    if f.author_id is None:  # an auto-drafted finding becomes the editing auditor's
        f.author_id = actor.id
    f.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="finding.edit", obj=f, before=before, after=v, summary=f"Edited finding {f.ref}")
    return f


def finding_out(db: Session, f: Finding, viewer_is_futran: bool = True) -> dict:
    author = db.get(User, f.author_id) if f.author_id else None
    approver = db.get(User, f.approved_by) if f.approved_by else None
    s = db.get(AISystem, f.ai_system_id) if f.ai_system_id else None
    ucs = [u for u in (db.get(UseCase, i) for i in f.use_case_ids or []) if u is not None]
    out = {
        "id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "status": f.status, "description": f.description, "recommended_remediation": f.recommended_remediation,
        "control_refs": f.control_refs or [], "use_case_ids": f.use_case_ids or [], "use_cases": [u.name for u in ucs], "ai_system_id": f.ai_system_id,
        "system": f"{s.reference_id} {s.name}" if s else None, "template_section": f.template_section, "null_compliance_flag": f.null_compliance_flag, "proposed_owner": f.proposed_owner,
        "approved_at": f.approved_at.isoformat() if f.approved_at else None, "approved_by": approver.name if approver else None,
    }
    if viewer_is_futran:
        out |= {"author_id": f.author_id, "author": author.name if author else ("Raised automatically" if f.origin != "manual" else None), "origin": f.origin,
                "review_comment": getattr(f, "review_comment", None), "source_question_ids": f.source_question_ids or [], "not_yet_in_place": f.not_yet_in_place}
    return out
