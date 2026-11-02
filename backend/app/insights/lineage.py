"""End-to-end lineage (spec §21 F6) over existing links, both directions:

- "Why is this a finding?": Finding → Response (the answers it came from) → control (checklist items and framework
  controls) → Obligation (WS-G's approved obligations, else the law library's Requirement) → Regulation; and Finding →
  Remediation.
- "What proves this control?": checklist item → its result and the answers it rests on → Evidence, and every other control
  and requirement the same evidence satisfies (spec §21 F16 cross-framework reuse).

The crosswalk (crosswalk.yaml) maps each questionnaire sub-section to checklist items, framework controls and requirement
codes. Only laws in the engagement's scope are walked to; a requirement must belong to its law's current version.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engagements.models import ClientRequirement, Engagement
from app.files.models import FileObject
from app.findings.models import Finding
from app.laws.models import Regulation
from app.questionnaire.models import ChecklistItem, ChecklistResult, Question, Response
from app.reference.frameworks import control_label
from app.regmaster.models import Requirement
from app.systems.models import AISystem
from app.tenancy.models import User

CROSSWALK = Path(__file__).with_name("crosswalk.yaml")


@lru_cache(maxsize=1)
def crosswalk() -> dict[str, dict]:
    return yaml.safe_load(CROSSWALK.read_text())["sections"]


def _question(db: Session, code: str) -> Question | None:
    return db.scalar(select(Question).where(Question.code == code).limit(1))


def _sections(db: Session, f: Finding) -> list[str]:
    out = []
    for code in f.source_question_ids or []:
        q = _question(db, code)
        if q is not None and q.sub_section not in out:
            out.append(q.sub_section)
    if f.template_section and f.template_section not in out:
        out.append(f.template_section)
    return [s for s in out if s in crosswalk()]


def _answer_label(q: Question, value) -> str | None:
    if value in (None, "", []):
        return None
    labels = {str(o["value"]): o["label"] for o in q.options or []}
    if isinstance(value, list):
        return ", ".join(labels.get(str(v), str(v)) for v in value)
    return labels.get(str(value), str(value))


def _response(db: Session, e: Engagement, s: AISystem | None, q: Question) -> Response | None:
    stmt = select(Response).where(Response.engagement_id == e.id, Response.question_id == q.id, Response.deleted_at.is_(None))
    r = db.scalar(stmt.where(Response.ai_system_id == s.id)) if s else None
    return r or db.scalar(stmt.where(Response.ai_system_id.is_(None)))


def _response_out(q: Question, r: Response | None) -> dict:
    status = r.status if r else "unanswered"
    answer = _answer_label(q, r.value) if r and status == "answered" else {"na": "Not applicable", "not_yet_in_place": "Not yet in place", "unanswered": "Not answered"}.get(status)
    src = ", ".join(x for x in ((r.source_person_name, r.source_person_title) if r else ()) if x) or None
    return {"code": q.code, "label": q.label, "answer": answer, "status": status, "source": src, "side": r.answered_side if r else None, "evidence_ids": list(r.evidence_ids or []) if r else []}


def _items(db: Session, codes: list[str]) -> list[ChecklistItem]:
    if not codes:
        return []
    rows = {i.code: i for i in db.scalars(select(ChecklistItem).where(ChecklistItem.code.in_(codes)))}
    return [rows[c] for c in codes if c in rows]


def _result(db: Session, e: Engagement, s: AISystem | None, item: ChecklistItem) -> ChecklistResult | None:
    stmt = select(ChecklistResult).where(ChecklistResult.engagement_id == e.id, ChecklistResult.checklist_item_id == item.id, ChecklistResult.deleted_at.is_(None))
    if item.scope == "system" and s is not None:
        return db.scalar(stmt.where(ChecklistResult.ai_system_id == s.id))
    return db.scalar(stmt.where(ChecklistResult.ai_system_id.is_(None)))


def in_scope_regulations(db: Session, e: Engagement) -> list[Regulation]:
    ids = list(db.scalars(select(ClientRequirement.regulation_id).where(ClientRequirement.engagement_id == e.id, ClientRequirement.in_scope.is_(True),
                                                                         ClientRequirement.deleted_at.is_(None), ClientRequirement.regulation_id.is_not(None))))
    return list(db.scalars(select(Regulation).where(Regulation.id.in_(ids)))) if ids else []


def requirements_for(db: Session, codes: list[str], regs: list[Regulation] | None) -> list[tuple[Regulation, Requirement]]:
    """Requirements with these codes in their law's current version; limited to `regs` when given."""
    if not codes:
        return []
    out = []
    pool = regs if regs is not None else list(db.scalars(select(Regulation).where(Regulation.current_version_id.is_not(None))))
    for reg in pool:
        if not reg.current_version_id:
            continue
        for req in db.scalars(select(Requirement).where(Requirement.law_version_id == reg.current_version_id, Requirement.code.in_(codes)).order_by(Requirement.order, Requirement.code)):
            out.append((reg, req))
    return out


def _obligations(db: Session, reg: Regulation, question_codes: list[str], requirement_ids: list[str]) -> list:
    """WS-G's approved obligations for this law that point at these questions or requirements (empty when WS-G is absent)."""
    try:
        from app.ai.models import Obligation
    except ImportError:
        return []
    rows = db.scalars(select(Obligation).where(Obligation.regulation_id == reg.id, Obligation.status == "approved", Obligation.deleted_at.is_(None)))
    return [o for o in rows if set(o.question_ids or []) & set(question_codes) or set(o.requirement_ids or []) & set(requirement_ids)]


def _law_name(reg: Regulation) -> str:
    return reg.short_name


def law_chain(db: Session, e: Engagement, question_codes: list[str], requirement_codes: list[str]) -> list[dict]:
    regs = in_scope_regulations(db, e)
    by_reg: dict[str, dict] = {}
    pairs = requirements_for(db, requirement_codes, regs)
    for reg in regs:
        reqs = [req for r, req in pairs if r.id == reg.id]
        obs = _obligations(db, reg, question_codes, [q.id for q in reqs])
        if obs:
            by_reg[reg.id] = {"regulation": _law_name(reg), "regulation_id": reg.id, "citation": reg.citation, "kind": "obligation",
                              "items": [{"text": o.text, "citation": o.citation, "actor": o.actor} for o in obs]}
        elif reqs:
            by_reg[reg.id] = {"regulation": _law_name(reg), "regulation_id": reg.id, "citation": reg.citation, "kind": "requirement",
                              "items": [{"code": q.code, "text": q.text, "citation": q.citation} for q in reqs]}
    return sorted(by_reg.values(), key=lambda x: x["regulation"])


def _files(db: Session, ids_with_via: list[tuple[str, str]]) -> list[dict]:
    out, seen = [], set()
    for fid, via in ids_with_via:
        if fid in seen:
            continue
        f = db.get(FileObject, fid)
        if f is None or f.deleted_at is not None:
            continue
        seen.add(fid)
        out.append({"id": f.id, "filename": f.filename, "via": via})
    return out


def finding_lineage(db: Session, f: Finding) -> dict:
    from app.docrequests.models import DocumentRequest
    from app.remediation.models import RemediationItem

    e = db.get(Engagement, f.engagement_id)
    s = db.get(AISystem, f.ai_system_id) if f.ai_system_id else None
    cw = crosswalk()
    sections = _sections(db, f)
    responses = []
    for code in f.source_question_ids or []:
        q = _question(db, code)
        if q is not None:
            responses.append(_response_out(q, _response(db, e, s, q)))
    checklist_codes = list(dict.fromkeys(c for sec in sections for c in cw[sec].get("checklist", [])))
    items = _items(db, checklist_codes)
    checklist = []
    evidence: list[tuple[str, str]] = [(fid, f"Answer {r['code']}") for r in responses for fid in r["evidence_ids"]]
    for it in items:
        res = _result(db, e, s, it)
        checklist.append({"code": it.code, "text": it.text, "confirmed": bool(res and res.confirmed)})
        evidence += [(fid, f"Checklist {it.code}") for fid in (res.evidence_ids if res else [])]
    refs = list(dict.fromkeys([*(f.control_refs or []), *(c for sec in sections for c in cw[sec].get("controls", []))]))
    req_codes = list(dict.fromkeys(c for sec in sections for c in cw[sec].get("requirements", [])))
    requests = []
    for dr in db.scalars(select(DocumentRequest).where(DocumentRequest.engagement_id == e.id, DocumentRequest.finding_id == f.id, DocumentRequest.deleted_at.is_(None))):
        from app.docrequests.models import DocumentChase
        from app.reference.models import DocumentCatalogItem

        cat = db.get(DocumentCatalogItem, dr.catalog_item_id)
        chases = len(list(db.scalars(select(DocumentChase.id).where(DocumentChase.document_request_id == dr.id))))
        requests.append({"title": cat.title if cat else "Requested document", "status": dr.status, "chases": chases})
        evidence += [(fid, "Document request") for fid in dr.evidence_ids or []]
    files = _files(db, evidence)
    remediation = []
    for item in db.scalars(select(RemediationItem).where(RemediationItem.finding_id == f.id, RemediationItem.deleted_at.is_(None))):
        owner = db.get(User, item.owner_user_id) if item.owner_user_id else None
        remediation.append({"id": item.id, "action": item.action, "owner": owner.name if owner else item.owner_name, "due_date": item.due_date.isoformat() if item.due_date else None,
                            "status": item.status})
    return {"finding": {"id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "status": f.status, "system": f"{s.reference_id} {s.name}" if s else None,
                        "system_id": s.id if s else None, "proposed_owner": f.proposed_owner},
            "responses": [{k: v for k, v in r.items() if k != "evidence_ids"} for r in responses], "checklist": checklist,
            "controls": [{"ref": r, "label": control_label(db, r)} for r in refs], "obligations": law_chain(db, e, list(f.source_question_ids or []), req_codes),
            "evidence": files, "requests": requests,
            "evidence_note": None if files else ("No evidence is linked to these answers or checklist items." if not requests else "Requested evidence has not been provided."),
            "remediation": remediation}


def control_proof(db: Session, s: AISystem, code: str) -> dict:
    e = db.get(Engagement, s.engagement_id)
    item = db.scalar(select(ChecklistItem).where(ChecklistItem.code == code).limit(1))
    if item is None:
        from app.core.errors import NotFound

        raise NotFound("No checklist item has that code.")
    cw = crosswalk()
    sections = [sec for sec, v in cw.items() if code in v.get("checklist", [])]
    res = _result(db, e, s, item)
    evidence: list[tuple[str, str]] = [(fid, f"Checklist {code}") for fid in (res.evidence_ids if res else [])]
    answers = []
    for q in db.scalars(select(Question).where(Question.sub_section.in_(sections)).order_by(Question.order)) if sections else []:
        r = _response(db, e, s, q)
        if r is not None and r.status != "unanswered":
            answers.append(_response_out(q, r))
            evidence += [(fid, f"Answer {q.code}") for fid in r.evidence_ids or []]
    refs = list(dict.fromkeys(c for sec in sections for c in cw[sec].get("controls", [])))
    req_codes = list(dict.fromkeys(c for sec in sections for c in cw[sec].get("requirements", [])))
    scoped = {r.id for r in in_scope_regulations(db, e)}
    reqs = [{"code": q.code, "text": q.text, "regulation": _law_name(reg), "in_scope": reg.id in scoped} for reg, q in requirements_for(db, req_codes, None)]
    other_items = [{"code": i.code, "text": i.text} for i in _items(db, list(dict.fromkeys(c for sec in sections for c in cw[sec].get("checklist", []) if c != code)))]
    return {"control": {"code": item.code, "text": item.text, "section": item.section_title}, "system": {"id": s.id, "reference_id": s.reference_id, "name": s.name},
            "confirmed": bool(res and res.confirmed), "auditor_note": res.auditor_note if res else None, "evidence": _files(db, evidence),
            "answers": [{k: v for k, v in a.items() if k != "evidence_ids"} for a in answers],
            "also_satisfies": {"controls": [{"ref": r, "label": control_label(db, r)} for r in refs], "requirements": reqs, "checklist": other_items}}


def report_lineage(db: Session, e: Engagement) -> list[dict]:
    """Appendix E: the lineage of each approved finding, as plain rows for the report template."""
    out = []
    for f in db.scalars(select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None), Finding.status == "approved").order_by(Finding.ref)):
        ln = finding_lineage(db, f)
        out.append({"ref": f.ref, "title": f.title,
                    "laws": "; ".join(f"{x['regulation']}: " + ", ".join(i.get("code") or (i.get("citation") or "obligation") for i in x["items"]) for x in ln["obligations"]) or "No law in scope is mapped",
                    "controls": ", ".join(c["label"] for c in ln["controls"]) or "None recorded",
                    "answers": "; ".join(f"{r['code']} {r['answer'] or 'Not answered'}" for r in ln["responses"]) or "Raised from fieldwork",
                    "checklist": ", ".join(c["code"] for c in ln["checklist"]) or "None",
                    "evidence": ", ".join(x["filename"] for x in ln["evidence"]) or (ln["evidence_note"] or ""),
                    "remediation": "; ".join(f"{r['action']} ({r['owner'] or 'owner to be confirmed'}, {r['status'].replace('_', ' ')})" for r in ln["remediation"]) or "No remediation recorded yet"})
    return out
