"""Regulatory master API (spec §25.6): M1 law library, M1a bulk edit, M1b add or edit a law, M2 law record,
M4 role and committee catalogue, M5 client applicability and intro letter. Permissions per §25.7."""
from datetime import date, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.clock import today, utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.laws.models import Regulation
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.reference.models import Jurisdiction
from app.regmaster import changes, engine, letter as letters
from app.regmaster.models import (
    STAGES, ClientGeography, ClientLawApplicability, CommitteeRule, IntroLetter, LawRoleMap, LawVersion, ProposedChange, Requirement, RoleCatalog, ScopeTest, Source,
)
from app.regmaster.seed import ensure_versions
from app.tenancy.models import Organization, User

router = APIRouter(tags=["regmaster"])

REGIONS = [("us_federal", "United States, federal"), ("us_states", "United States, states and cities"), ("eu", "European Union"), ("india", "India"),
           ("uk", "United Kingdom"), ("canada", "Canada"), ("other", "Other geographies"), ("framework", "Frameworks (voluntary, used as the baseline)")]
REGION_LABELS = dict(REGIONS)
TOPICS = {"hiring": "Hiring and employment", "consumer_decisions": "Consumer decisions", "genai": "Generative AI disclosure", "frontier": "Frontier models",
          "personal_data": "Personal data", "health": "Health care", "security": "Security and incidents", "framework": "Framework"}
COMMITTEE_LABELS = {"ai_governance_committee": "AI governance committee", "risk_program": "Risk assessment program", "quality_management_system": "Quality management system",
                    "sdf_setup": "Significant data fiduciary set-up", "consequential_decision_rights": "Consequential-decision rights"}
OPEN = ("pending", "held", "legal_review")


# ------------------------------------------------------------------ helpers

def _region(db: Session, reg: Regulation, j: Jurisdiction | None) -> str:
    if reg.region:
        return reg.region
    if reg.type in ("voluntary", "framework"):
        return "framework"
    code = j.code if j else ""
    if code == "US":
        return "us_federal"
    if code.startswith("US-"):
        return "us_states"
    if code == "EU":
        return "eu"
    return {"IN": "india", "GB": "uk", "CA": "canada"}.get(code, "other")


def _version(db: Session, reg: Regulation) -> LawVersion | None:
    return db.get(LawVersion, reg.current_version_id) if reg.current_version_id else None


def _iso(d):
    return d.isoformat() if d else None


def _effective_label(v: LawVersion | None) -> str:
    if v is None:
        return ""
    d = v.compliance_on or v.effective_on
    return d.strftime("%-d %b %Y") if d and not v.effective_text else (v.effective_text or "")


def _counts(db: Session, version_ids: list[str]) -> tuple[dict, dict, dict]:
    if not version_ids:
        return {}, {}, {}
    reqs = dict(db.execute(select(Requirement.law_version_id, func.count()).where(Requirement.law_version_id.in_(version_ids)).group_by(Requirement.law_version_id)).all())
    roles = dict(db.execute(select(LawRoleMap.law_version_id, func.count()).where(LawRoleMap.law_version_id.in_(version_ids), LawRoleMap.level == "required").group_by(LawRoleMap.law_version_id)).all())
    comm: dict[str, list[str]] = {}
    for c in db.scalars(select(CommitteeRule).where(CommitteeRule.law_version_id.in_(version_ids))):
        comm.setdefault(c.law_version_id, []).append(f"{c.title or COMMITTEE_LABELS.get(c.committee_type, c.committee_type)}{'' if c.level == 'required' else ' (recommended)'}")
    return reqs, roles, comm


def _law_row(db: Session, reg: Regulation, j: Jurisdiction | None, v: LawVersion | None, reqs, roles, comm, pending: dict) -> dict:
    p = pending.get(reg.id, 0)
    if p:
        last = "Change proposed"
    elif v and v.version_no > 1:
        last = (v.change_summary or "Updated")[:80]
    else:
        last = "No change"
    return {
        "id": reg.id, "geography": j.name if j else "", "jurisdiction_code": j.code if j else None, "short_name": reg.short_name, "label": engine.law_label(reg),
        "citation": reg.citation if reg.citation and len(reg.citation) < 120 else None, "type": reg.type, "binding": reg.binding,
        "status": v.status if v else None, "status_label": letters.STATUS_LABELS.get(v.status, v.status) if v else "", "effective": _effective_label(v),
        "effective_on": _iso(v.compliance_on or v.effective_on) if v else None, "scope": (v.scope_text if v else None) or reg.trigger_text or "",
        "applies_to": (v.applies_to if v else None) or [], "topics": reg.topics or [], "requirement_count": reqs.get(v.id, 0) if v else 0,
        "role_count": roles.get(v.id, 0) if v else 0, "committee": "; ".join(comm.get(v.id, [])) if v else "", "penalty": (v.penalty_text if v else None) or "",
        "last_change": last, "pending_count": p, "verify": bool(v.verify_flag if v else reg.verify_flag), "version_no": v.version_no if v else None,
        "region": _region(db, reg, j), "review_due_on": _iso(reg.review_due_on), "reviewer_id": reg.reviewer_id, "refresh_every_days": reg.refresh_every_days, "watch": bool(reg.watch),
    }


def _pending_by_reg(db: Session) -> dict:
    return dict(db.execute(select(ProposedChange.regulation_id, func.count()).where(ProposedChange.status.in_(OPEN), ProposedChange.regulation_id.is_not(None)).group_by(ProposedChange.regulation_id)).all())


def _reg_or_404(db: Session, law_id: str) -> Regulation:
    reg = db.get(Regulation, law_id)
    if reg is None:
        raise NotFound()
    if reg.current_version_id is None:
        ensure_versions(db)
    return reg


def _origin(actor: Actor) -> str:
    return "admin_edit" if actor.role_names & {"chief_auditor", "admin"} else "auditor_suggestion"


def _authorize_propose(db: Session, actor: Actor) -> None:
    try:
        authorize(db, actor, Action.PROPOSE_REG_CHANGE)
    except Forbidden:
        authorize(db, actor, Action.SUGGEST_REG_CHANGE)


def _claude_available(request: Request) -> bool:
    return bool(request.app.state.settings.anthropic_api_key)


# ------------------------------------------------------------------ M1 law library

@router.get("/reg/laws")
def law_library(request: Request, region: str | None = None, status: str | None = None, applies_to: str | None = None, topic: str | None = None, q: str | None = None,
                show: str = "library", actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_REG_MASTER)
    ensure_versions(db)
    rows = db.execute(select(Regulation, Jurisdiction).join(Jurisdiction, Jurisdiction.id == Regulation.jurisdiction_id)
                      .where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None)).order_by(Jurisdiction.name, Regulation.short_name)).all()
    versions = {r.current_version_id: db.get(LawVersion, r.current_version_id) for r, _ in rows if r.current_version_id}
    reqs, roles, comm = _counts(db, list(versions))
    pending = _pending_by_reg(db)
    all_rows = [_law_row(db, r, j, versions.get(r.current_version_id), reqs, roles, comm, pending) for r, j in rows]
    library = [x for x in all_rows if x["requirement_count"] or x["pending_count"]]
    shown = all_rows if show == "all" else library
    if region:
        shown = [x for x in shown if x["region"] == region]
    if status:
        shown = [x for x in shown if x["status"] == status or (status == "in_force" and x["status"] == "in_force_phased")]
    if applies_to:
        shown = [x for x in shown if applies_to in x["applies_to"]]
    if topic:
        shown = [x for x in shown if topic in x["topics"]]
    if q:
        words = q.lower().split()
        req_hits = set()
        for vid, in db.execute(select(Requirement.law_version_id).where(func.lower(Requirement.text).contains(q.lower()))):
            req_hits.add(vid)
        shown = [x for x in shown if all(w in f"{x['short_name']} {x['citation'] or ''} {x['geography']} {x['label']}".lower() for w in words) or
                 any(versions.get(r.current_version_id) and versions[r.current_version_id].id in req_hits for r, _ in rows if r.id == x["id"])]
    groups = [{"region": k, "label": label, "laws": [x for x in shown if x["region"] == k]} for k, label in REGIONS]
    soon = today() + timedelta(days=90)
    upcoming = sum(1 for v in versions.values() if v and any(d and today() <= d <= soon for d in (v.effective_on, v.compliance_on)))
    last_refresh = None
    try:
        from app.refresh.service import last_run_summary

        last_refresh = last_run_summary(db, "law")
    except Exception:  # the refresh pipeline (M3) is optional in this build
        last_refresh = None
    return {
        "kpis": {"geographies": len({x["jurisdiction_code"] for x in library}), "laws": len(library), "requirements": sum(x["requirement_count"] for x in library),
                 "pending": db.scalar(select(func.count()).select_from(ProposedChange).where(ProposedChange.status.in_(OPEN))) or 0, "upcoming": upcoming,
                 "shown": len(shown), "library": len(library), "all": len(all_rows)},
        "groups": [g for g in groups if g["laws"]],
        "regions": [{"value": k, "label": v} for k, v in REGIONS],
        "topics": [{"value": k, "label": v} for k, v in TOPICS.items()],
        "claude_available": _claude_available(request),
        "can_approve": "chief_auditor" in actor.role_names,
        "can_edit": bool(actor.role_names & {"chief_auditor", "admin"}),
        "last_refresh": last_refresh,
    }


# ------------------------------------------------------------------ M2 law record

def _req_out(db, r: Requirement) -> dict:
    return changes.requirement_out(db, r)


@router.get("/reg/laws/{law_id}")
def law_record(law_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_REG_MASTER)
    reg = _reg_or_404(db, law_id)
    v = _version(db, reg)
    j = db.get(Jurisdiction, reg.jurisdiction_id)
    parent = db.get(Jurisdiction, j.parent_id) if j and j.parent_id else None
    reqs = list(db.scalars(select(Requirement).where(Requirement.law_version_id == v.id).order_by(Requirement.order)))
    maps = list(db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == v.id)))
    req_codes = {r.id: r.code for r in reqs}
    role_rows = []
    for m in sorted(maps, key=lambda m: (m.level != "required", db.get(RoleCatalog, m.role_id).number)):
        role = db.get(RoleCatalog, m.role_id)
        role_rows.append({"role": role.code, "name": role.name, "level": m.level, "needed_by_stage": m.needed_by_stage, "basis": m.basis_text, "applies_to": m.applies_to or [],
                          "requirements": [req_codes[i] for i in (m.requirement_ids or []) if i in req_codes], "verify": m.verify_flag})
    # roles a previous version mapped that this one no longer does
    prev = db.scalar(select(LawVersion).where(LawVersion.regulation_id == reg.id, LawVersion.version_no < v.version_no).order_by(LawVersion.version_no.desc()).limit(1))
    if prev is not None:
        now_ids = {m.role_id for m in maps}
        for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == prev.id)):
            if m.role_id not in now_ids:
                role = db.get(RoleCatalog, m.role_id)
                role_rows.append({"role": role.code, "name": role.name, "level": "no_longer_required", "needed_by_stage": None, "basis": None, "applies_to": [], "requirements": [], "verify": False})
    history = []
    for h in db.scalars(select(LawVersion).where(LawVersion.regulation_id == reg.id).order_by(LawVersion.version_no.desc())):
        by = db.get(User, h.approved_by) if h.approved_by else None
        history.append({"id": h.id, "version_no": h.version_no, "change": h.change_summary or "", "by": f"Approved by {by.name}" if by else "Futran (seed or matrix import)", "date": _iso(h.approved_at or h.created_at)})
    pending = [_change_out(db, pc) for pc in db.scalars(select(ProposedChange).where(ProposedChange.regulation_id == reg.id, ProposedChange.status.in_(OPEN)).order_by(ProposedChange.created_at.desc()))]
    used_by = db.scalar(select(func.count()).select_from(ClientLawApplicability).where(ClientLawApplicability.regulation_id == reg.id, ClientLawApplicability.in_scope.is_(True), ClientLawApplicability.deleted_at.is_(None))) or 0
    systems = 0
    try:
        from app.register.models import RegisterSystemLaw

        systems = db.scalar(select(func.count()).select_from(RegisterSystemLaw).where(RegisterSystemLaw.regulation_id == reg.id, RegisterSystemLaw.deleted_at.is_(None))) or 0
    except Exception:
        systems = 0
    sources = [{"id": s.id, "name": s.name, "url": s.url, "kind": s.kind, "last_read_at": _iso(s.last_read_at)} for s in db.scalars(select(Source).where(Source.regulation_id == reg.id).order_by(Source.kind, Source.name))]
    return {
        "id": reg.id, "short_name": reg.short_name, "label": engine.law_label(reg), "citation": reg.citation, "type": reg.type, "binding": reg.binding, "topics": reg.topics or [],
        "region": _region(db, reg, j), "geography": j.name if j else "", "jurisdiction_code": j.code if j else None, "parent_geography": parent.name if parent else None,
        "version": {
            "id": v.id, "version_no": v.version_no, "status": v.status, "status_label": letters.STATUS_LABELS.get(v.status, v.status), "signed_on": _iso(v.signed_on),
            "effective_on": _iso(v.effective_on), "compliance_on": _iso(v.compliance_on), "effective_text": v.effective_text, "scope_text": v.scope_text,
            "applies_to": v.applies_to or [], "enforcer": v.enforcer, "private_right_of_action": v.private_right_of_action, "penalty_text": v.penalty_text,
            "cure_period": v.cure_period, "exemptions_text": v.exemptions_text, "removed_text": v.removed_text, "litigation_text": v.litigation_text,
            "main_duty": v.main_duty, "verify": v.verify_flag, "approved_at": _iso(v.approved_at), "approved_by": (db.get(User, v.approved_by).name if v.approved_by and db.get(User, v.approved_by) else None),
        },
        "scope_tests": [{"order": t.order, "question_text": t.question_text, "answer_type": t.answer_type, "in_scope_rule": t.in_scope_rule, "decisive": t.decisive, "prefill_from": t.prefill_from, "note": t.note}
                        for t in db.scalars(select(ScopeTest).where(ScopeTest.law_version_id == v.id).order_by(ScopeTest.order))],
        "requirements": [_req_out(db, r) for r in reqs],
        "role_maps": role_rows,
        "committees": [{"committee_type": c.committee_type, "title": c.title, "level": c.level, "basis": c.basis_text, "condition": c.condition_text, "items": c.items or []}
                       for c in db.scalars(select(CommitteeRule).where(CommitteeRule.law_version_id == v.id))],
        "history": history, "pending": pending, "sources": sources, "used_by_clients": used_by, "used_by_systems": systems,
        "can_edit": bool(actor.role_names & {"chief_auditor", "admin"}), "can_suggest": True, "can_approve": "chief_auditor" in actor.role_names,
        "roles": [{"code": r.code, "name": r.name} for r in db.scalars(select(RoleCatalog).order_by(RoleCatalog.number))],
    }


def _change_out(db: Session, pc: ProposedChange) -> dict:
    by = db.get(User, pc.proposed_by) if pc.proposed_by else None
    return {"id": pc.id, "field_path": pc.field_path, "change_type": pc.change_type, "summary": pc.summary, "old_value": pc.old_value, "new_value": pc.new_value,
            "status": pc.status, "origin": pc.origin, "confidence": pc.confidence, "source_url": pc.source_url, "source_quote": pc.source_quote,
            "proposed_by": by.name if by else ("Claude" if pc.origin.startswith("claude") else None), "created_at": _iso(pc.created_at), "batch_id": pc.batch_id}


class ChangeIn(BaseModel):
    field_path: str
    new_value: object | None = None
    summary: str | None = None
    change_type: str | None = None


class ProposalsIn(BaseModel):
    changes: list[ChangeIn]
    summary: str
    reason: str | None = None
    source_url: str | None = None
    source_quote: str | None = None


def _change_type(field_path: str, given: str | None) -> str:
    if given:
        return given
    if field_path.startswith("role_map."):
        return "role_mapping"
    if field_path.startswith("requirement."):
        return "new_rule"
    if field_path in ("law.effective_on", "law.compliance_on", "law.signed_on", "law.effective_text"):
        return "effective_date"
    if field_path == "repeal":
        return "repeal"
    return "amendment"


@router.post("/reg/laws/{law_id}/proposals")
def propose_changes(law_id: str, body: ProposalsIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Save edits to a law as proposed changes (M1b edit, M2 requirement editor, M4 role levels). Nothing goes live."""
    _authorize_propose(db, actor)
    reg = _reg_or_404(db, law_id)
    if not body.changes:
        raise Invalid(errors=[{"field": "changes", "message": "Nothing has changed."}])
    batch = str(uuid4())
    out = []
    for c in body.changes[:200]:
        pc = changes.propose(db, actor_id=actor.id, regulation_id=reg.id, field_path=c.field_path, new_value=c.new_value, summary=(c.summary or body.summary),
                             origin=_origin(actor), change_type=_change_type(c.field_path, c.change_type), reason=body.reason, source_url=body.source_url,
                             source_quote=body.source_quote, batch_id=batch)
        out.append(pc)
    audit.record(db, actor_id=actor.id, action="regmaster.propose", object_type="Regulation", object_id=reg.id, organization_id=actor.organization.id,
                 after={"changes": [pc.field_path for pc in out], "reason": body.reason}, summary=f"Proposed {len(out)} change(s) to {engine.law_label(reg)}: {body.summary[:120]}")
    return {"proposals": [_change_out(db, pc) for pc in out]}


class RequirementBulkIn(BaseModel):
    codes: list[str]
    role: str | None = None
    needed_by_stage: str | None = None
    applies_to: list[str] | None = None
    reason: str


@router.post("/reg/laws/{law_id}/requirements/bulk")
def bulk_requirements(law_id: str, body: RequirementBulkIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """M2 bulk bar: set role, needed-by or applies-to on the selected requirements (as proposed changes)."""
    authorize(db, actor, Action.PROPOSE_REG_CHANGE)
    reg = _reg_or_404(db, law_id)
    if not body.reason.strip():
        raise Invalid(errors=[{"field": "reason", "message": "Give the reason for this change."}])
    v = _version(db, reg)
    batch = str(uuid4())
    out = []
    for r in db.scalars(select(Requirement).where(Requirement.law_version_id == v.id, Requirement.code.in_(body.codes))):
        cur = changes.requirement_out(db, r)
        new = {k: cur[k] for k in ("text", "applies_to", "needed_by_stage", "evidence_text", "role", "ai_types", "citation", "source_quote", "source_url", "verify_flag")}
        if body.role is not None:
            new["role"] = body.role or None
        if body.needed_by_stage:
            new["needed_by_stage"] = body.needed_by_stage
        if body.applies_to is not None:
            new["applies_to"] = body.applies_to
        if new == {k: cur[k] for k in new}:
            continue
        out.append(changes.propose(db, actor_id=actor.id, regulation_id=reg.id, field_path=f"requirement.{r.code}", new_value=new, summary=f"Update {r.code}",
                                   origin="admin_edit", change_type="amendment", reason=body.reason, batch_id=batch))
    return {"proposals": [_change_out(db, pc) for pc in out]}


# ------------------------------------------------------------------ M1a bulk edit

class RoleLevelIn(BaseModel):
    role: str
    level: str  # required | recommended | not_required | keep
    needed_by_stage: str | None = None
    skip: list[str] = []


class TrackingIn(BaseModel):
    reviewer_id: str | None = None
    review_due_on: date | None = None
    refresh_every_days: int | None = None
    watch: bool | None = None


class BulkIn(BaseModel):
    ids: list[str]
    tracking: TrackingIn | None = None
    topics_add: list[str] = []
    applies_to_add: list[str] = []
    role_levels: list[RoleLevelIn] = []
    reason: str | None = None


def _bulk_regs(db: Session, ids: list[str]) -> list[Regulation]:
    if not ids:
        raise Invalid(errors=[{"field": "ids", "message": "Select at least one law."}])
    regs = [db.get(Regulation, i) for i in ids[:200]]
    if any(r is None for r in regs):
        raise NotFound()
    ensure_versions(db)
    return regs


def _role_level_on(db: Session, reg: Regulation, role: RoleCatalog) -> LawRoleMap | None:
    return db.scalar(select(LawRoleMap).where(LawRoleMap.law_version_id == reg.current_version_id, LawRoleMap.role_id == role.id))


@router.post("/reg/laws/bulk/preview")
def bulk_preview(body: BulkIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Step 4 of M1a: what each role change would do, before saving."""
    authorize(db, actor, Action.PROPOSE_REG_CHANGE)
    regs = _bulk_regs(db, body.ids)
    out = []
    for rl in body.role_levels:
        role = db.scalar(select(RoleCatalog).where(RoleCatalog.code == rl.role))
        if role is None:
            raise Invalid(errors=[{"field": "role", "message": "Unknown role."}])
        current = {}
        not_set = []
        for reg in regs:
            m = _role_level_on(db, reg, role)
            current[engine.law_label(reg)] = m.level if m else None
            if m is None:
                not_set.append(engine.law_label(reg))
        added = [reg for reg in regs if _role_level_on(db, reg, role) is None and rl.level in ("required", "recommended")]
        clients = set()
        for reg in added:
            clients |= set(db.scalars(select(ClientLawApplicability.organization_id).where(ClientLawApplicability.regulation_id == reg.id, ClientLawApplicability.in_scope.is_(True), ClientLawApplicability.deleted_at.is_(None))))
        systems = 0
        try:
            from app.register.models import RegisterSystemLaw

            systems = db.scalar(select(func.count(func.distinct(RegisterSystemLaw.register_system_id))).where(RegisterSystemLaw.regulation_id.in_([r.id for r in added]), RegisterSystemLaw.deleted_at.is_(None))) or 0 if added else 0
        except Exception:
            systems = 0
        req_on = sum(1 for lv in current.values() if lv == "required")
        out.append({"role": role.code, "name": role.name, "current": current, "summary": f"Required on {req_on} of {len(regs)}" + (f" · not set on {', '.join(not_set)}" if not_set else ""),
                    "not_set_on": not_set, "adds_to_clients": len(clients), "adds_to_systems": systems})
    return {"roles": out}


@router.post("/reg/laws/bulk")
def bulk_edit(body: BulkIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """M1a: tracking fields apply at once; content changes become proposed changes (one batch)."""
    regs = _bulk_regs(db, body.ids)
    content = bool(body.topics_add or body.applies_to_add or [r for r in body.role_levels if r.level != "keep"])
    if content:
        authorize(db, actor, Action.PROPOSE_REG_CHANGE)
        if not (body.reason or "").strip():
            raise Invalid(errors=[{"field": "reason", "message": "Give the reason for this change. It is saved to each law's version history."}])
    tracked = 0
    if body.tracking is not None:
        authorize(db, actor, Action.MANAGE_REG_TRACKING)
        t = body.tracking.model_dump(exclude_unset=True)
        if t.get("refresh_every_days") is not None and not 1 <= t["refresh_every_days"] <= 365:
            raise Invalid(errors=[{"field": "tracking.refresh_every_days", "message": "Choose between 1 and 365 days."}])
        if t.get("reviewer_id"):
            u = db.get(User, t["reviewer_id"])
            if u is None or u.organization_id != actor.organization.id:
                raise Invalid(errors=[{"field": "tracking.reviewer_id", "message": "Choose a Futran reviewer."}])
        if t:
            for reg in regs:
                before = {k: _iso(getattr(reg, k)) if isinstance(getattr(reg, k), date) else getattr(reg, k) for k in t}
                for k, v in t.items():
                    setattr(reg, k, v)
                tracked += 1
                audit.record(db, actor_id=actor.id, action="regmaster.tracking", object_type="Regulation", object_id=reg.id, organization_id=actor.organization.id,
                             before=before, after={k: _iso(v) if isinstance(v, date) else v for k, v in t.items()}, summary=f"Updated tracking on {engine.law_label(reg)}")
    batch = str(uuid4())
    made = []
    for reg in regs:
        if body.topics_add:
            new = sorted(set(reg.topics or []) | set(body.topics_add))
            if new != sorted(reg.topics or []):
                made.append(changes.propose(db, actor_id=actor.id, regulation_id=reg.id, field_path="law.topics", new_value=new, summary="Add topics", origin="bulk_edit", reason=body.reason, batch_id=batch))
        if body.applies_to_add:
            v = _version(db, reg)
            new = list(dict.fromkeys([*(v.applies_to or []), *body.applies_to_add]))
            if new != (v.applies_to or []):
                made.append(changes.propose(db, actor_id=actor.id, regulation_id=reg.id, field_path="law.applies_to", new_value=new, summary="Add who the law applies to", origin="bulk_edit", reason=body.reason, batch_id=batch))
        for rl in body.role_levels:
            if rl.level == "keep" or reg.id in rl.skip:
                continue
            role = db.scalar(select(RoleCatalog).where(RoleCatalog.code == rl.role))
            if role is None:
                raise Invalid(errors=[{"field": "role", "message": "Unknown role."}])
            m = _role_level_on(db, reg, role)
            if rl.level == "not_required":
                if m is None:
                    continue
                value = None
            else:
                if m is not None and m.level == rl.level and (rl.needed_by_stage in (None, m.needed_by_stage)):
                    continue
                value = {"level": rl.level, "needed_by_stage": rl.needed_by_stage or (m.needed_by_stage if m else role.default_stage)}
            made.append(changes.propose(db, actor_id=actor.id, regulation_id=reg.id, field_path=f"role_map.{role.code}", new_value=value,
                                        summary=f"{role.name}: {rl.level.replace('_', ' ')}", origin="bulk_edit", change_type="role_mapping", reason=body.reason, batch_id=batch))
    return {"tracking_applied": tracked, "proposals": len(made), "batch_id": batch if made else None}


# ------------------------------------------------------------------ M1b add a law, draft with Claude

class DraftIn(BaseModel):
    ref: str


@router.post("/reg/laws/draft")
def draft_with_claude(body: DraftIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.PROPOSE_REG_CHANGE)
    if not _claude_available(request):
        raise Conflict("Drafting with Claude needs an Anthropic API key in settings. Fill the form by hand, or ask an administrator to add the key.")
    ref = body.ref.strip()
    if not ref or len(ref) > 500:
        raise Invalid(errors=[{"field": "ref", "message": "Paste the bill number or the official link."}])
    from app.laws.refresh import default_factory
    from app.regmaster.draft import draft_law

    factory = getattr(request.app.state, "claude_factory", None) or default_factory
    try:
        result = draft_law(db, factory(request.app.state.settings), ref)
    except Exception as exc:  # network or API failure: the form stays usable
        raise Conflict(f"Claude could not draft this law: {str(exc)[:300]}")
    audit.record(db, actor_id=actor.id, action="regmaster.draft_with_claude", object_type="Regulation", object_id=None, organization_id=actor.organization.id,
                 after={"ref": ref, "prompt_version": result["prompt_version"], "warnings": result["warnings"]}, summary=f"Drafted a law record with Claude from {ref[:120]}")
    return result


class NewLawIn(BaseModel):
    law: dict
    drafted_with_claude: bool = False


@router.post("/reg/laws/new")
def propose_new_law(body: NewLawIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """M1b "Send for approval": the whole record as one new-law proposal for the Chief Auditor."""
    authorize(db, actor, Action.PROPOSE_REG_CHANGE)
    law = dict(body.law)
    code = str(law.get("jurisdiction_code") or "").upper()
    errors = []
    for f, msg in (("short_name", "Give the law a short name."), ("jurisdiction_code", "Choose the geography."), ("citation", "Give the citation."), ("status", "Choose the status."), ("scope_text", "Describe who the law covers.")):
        if not str(law.get(f) or "").strip():
            errors.append({"field": f, "message": msg})
    if not law.get("applies_to"):
        errors.append({"field": "applies_to", "message": "Choose who the law applies to."})
    if errors:
        raise Invalid(errors=errors)
    sources = [s for s in law.get("sources") or [] if isinstance(s, dict) and str(s.get("url", "")).startswith("http")]
    version = {k: law.get(k) for k in ("status", "signed_on", "effective_on", "compliance_on", "enforcer", "private_right_of_action", "penalty_text", "cure_period", "scope_text", "exemptions_text", "applies_to") if law.get(k) not in (None, "")}
    version["verify_flag"] = True
    value = {"jurisdiction_code": code, "short_name": law["short_name"], "citation": law.get("citation"), "type": law.get("type") or "statute", "binding": law.get("binding", True),
             "topics": law.get("topics") or [], "label": law.get("label"), "version": version, "sources": sources,
             "scope_tests": [{"question_text": t["question_text"], "prefill_from": t.get("prefill_from"), "in_scope_rule": t.get("in_scope_rule") or {"equals": "yes"}} for t in law.get("scope_tests") or [] if t.get("question_text")],
             "requirements": law.get("requirements") or []}
    origin = "claude_draft" if body.drafted_with_claude else "admin_edit"
    first = sources[0] if sources else {}
    quote = next((r.get("source_quote") for r in value["requirements"] if r.get("source_quote")), None)
    pc = changes.propose(db, actor_id=actor.id, regulation_id=None, field_path="new_law", new_value=value, summary=f"Add {law['short_name'][:200]}", origin=origin,
                         change_type="new_law", source_url=first.get("url"), source_quote=quote or (first.get("name") if origin == "admin_edit" else None))
    audit.record(db, actor_id=actor.id, action="regmaster.propose_new_law", object_type="ProposedChange", object_id=pc.id, organization_id=actor.organization.id, summary=f"Proposed new law {law['short_name'][:120]}")
    return _change_out(db, pc)


# ------------------------------------------------------------------ M4 role and committee catalogue

TOP_LAWS = ["eu_ai_act", "co_sb26_189", "nyc_ll144", "il_hb3773", "ca_ccpa_admt", "ca_ads_rules", "in_dpdp", "in_certin", "gdpr", "nist_ai_rmf"]


@router.get("/reg/roles")
def role_catalogue(laws: str = "top", jurisdiction: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_REG_MASTER)
    ensure_versions(db)
    roles = list(db.scalars(select(RoleCatalog).order_by(RoleCatalog.number)))
    regs = [r for r in db.scalars(select(Regulation).where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None), Regulation.current_version_id.is_not(None)))]
    mapped = set(db.scalars(select(LawRoleMap.law_version_id).distinct()))
    regs = [r for r in regs if r.current_version_id in mapped]
    if jurisdiction:
        j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == jurisdiction.upper()))
        regs = [r for r in regs if j and r.jurisdiction_id == j.id]
    if laws == "top":
        regs = sorted(regs, key=lambda r: (r.region == "framework", r.binding is False, -(db.scalar(select(func.count()).select_from(LawRoleMap).where(LawRoleMap.law_version_id == r.current_version_id)) or 0)))[:10]
    else:
        regs = sorted(regs, key=lambda r: (r.region == "framework", engine.law_label(r)))
    cells: dict[str, dict] = {r.code: {} for r in roles}
    by_id = {r.id: r for r in roles}
    for reg in regs:
        reqs = {q.id: q.code for q in db.scalars(select(Requirement).where(Requirement.law_version_id == reg.current_version_id))}
        for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == reg.current_version_id)):
            cells[by_id[m.role_id].code][reg.id] = {"level": m.level, "needed_by_stage": m.needed_by_stage, "basis": m.basis_text, "requirements": [reqs[i] for i in (m.requirement_ids or []) if i in reqs]}
    comm: dict[str, dict] = {}
    for reg in regs:
        for c in db.scalars(select(CommitteeRule).where(CommitteeRule.law_version_id == reg.current_version_id)):
            g = comm.setdefault(c.committee_type, {"committee_type": c.committee_type, "title": c.title or COMMITTEE_LABELS.get(c.committee_type, c.committee_type), "level": c.level, "items": [], "sources": []})
            if c.level == "required":
                g["level"] = "required"
            for it in c.items or []:
                if it not in g["items"]:
                    g["items"].append(it)
            g["sources"].append({"law": engine.law_label(reg), "level": c.level, "basis": c.basis_text, "condition": c.condition_text})
    return {
        "roles": [{"code": r.code, "number": r.number, "name": r.name, "description": r.description, "level": r.level, "default_stage": r.default_stage, "main_sources": r.main_sources, "extra_checks": r.extra_checks} for r in roles],
        "laws": [{"id": r.id, "label": engine.law_label(r), "short_name": r.short_name} for r in regs],
        "cells": cells,
        "committees": sorted(comm.values(), key=lambda c: (c["level"] != "required", c["title"])),
        "stages": STAGES,
        "can_edit": bool(actor.role_names & {"chief_auditor", "admin"}),
    }


class RoleIn(BaseModel):
    name: str | None = None
    description: str | None = None
    level: str | None = None
    default_stage: str | None = None
    extra_checks: str | None = None


@router.patch("/reg/roles/{code}")
def edit_role(code: str, body: RoleIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Catalogue wording, level and default stage. Which laws require the role is changed through proposals."""
    authorize(db, actor, Action.PROPOSE_REG_CHANGE)
    role = db.scalar(select(RoleCatalog).where(RoleCatalog.code == code))
    if role is None:
        raise NotFound()
    data = body.model_dump(exclude_unset=True)
    errors = []
    if "name" in data and not (data["name"] or "").strip():
        errors.append({"field": "name", "message": "Give the role a name."})
    if "level" in data and data["level"] not in ("company", "system", "agent"):
        errors.append({"field": "level", "message": "Choose company, system or agent."})
    if "default_stage" in data and data["default_stage"] not in STAGES:
        errors.append({"field": "default_stage", "message": "Choose a stage."})
    if "description" in data and not (data["description"] or "").strip():
        errors.append({"field": "description", "message": "Describe the responsibility. It is shown in the intro letter."})
    if errors:
        raise Invalid(errors=errors)
    before = {k: getattr(role, k) for k in data}
    for k, v in data.items():
        setattr(role, k, v.strip() if isinstance(v, str) else v)
    audit.record(db, actor_id=actor.id, action="regmaster.role_edit", object_type="RoleCatalog", object_id=role.id, organization_id=actor.organization.id, before=before, after=data, summary=f"Edited role {role.name}")
    return {"code": role.code, "name": role.name, "description": role.description, "level": role.level, "default_stage": role.default_stage, "extra_checks": role.extra_checks}


# ------------------------------------------------------------------ M5 client applicability and intro letter

def _client(db: Session, actor: Actor, client_id: str, action: Action) -> Organization:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at:
        raise NotFound()
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, action, org_id=org.id)
    return org


def _letter_out(db: Session, x: IntroLetter, html: bool = True) -> dict:
    ap = db.get(User, x.approved_by) if x.approved_by else None
    return {"id": x.id, "version_no": x.version_no, "status": x.status, "file_id": x.file_id, "approved_by": ap.name if ap else None, "approved_at": _iso(x.approved_at),
            "sent_at": _iso(x.sent_at), "created_at": _iso(x.created_at), "edited_text": x.edited_text or {}, "changes": x.changes or [],
            "versions": (x.body or {}).get("versions", []), "html": letters.to_html(x) if html else None}


@router.get("/clients/{client_id}/applicability")
def applicability(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _client(db, actor, client_id, Action.VIEW_APPLICABILITY)
    rows = engine.run(db, org.id, actor.id)
    geos = []
    for g in engine.geographies(db, org.id):
        j = db.get(Jurisdiction, g.jurisdiction_id)
        parent = db.get(Jurisdiction, j.parent_id) if j and j.parent_id else None
        geos.append({"id": g.id, "jurisdiction_code": j.code, "name": j.name, "parent": parent.name if parent else None, "level": j.level, "basis": g.basis, "source": g.source})
    laws_in, laws_out = [], []
    for row in rows:
        reg = db.get(Regulation, row.regulation_id)
        v = db.get(LawVersion, row.law_version_id) if row.law_version_id else None
        j = db.get(Jurisdiction, reg.jurisdiction_id)
        tests = list(db.scalars(select(ScopeTest).where(ScopeTest.law_version_id == v.id).order_by(ScopeTest.order))) if v else []
        used = (row.scope_answers or {}).get("used") or {}
        manual = (row.scope_answers or {}).get("manual") or {}
        item = {"regulation_id": reg.id, "label": engine.law_label(reg), "short_name": reg.short_name, "geography": j.name if j else "", "binding": reg.binding is not False,
                "kind": "Baseline" if reg.region == "framework" else ("Binding" if reg.binding is not False else "Guidance"), "status": letters.STATUS_LABELS.get(v.status, "") if v else "",
                "reason": row.reason_text, "override": row.override, "version_no": v.version_no if v else None, "main_duty": v.main_duty if v else None,
                "questions": [{"order": t.order, "question_text": t.question_text, "answer": manual.get(str(t.order)) or used.get(str(t.order)), "manual": str(t.order) in manual, "decisive": t.decisive} for t in tests]}
        (laws_in if row.in_scope else laws_out).append(item)
    laws_in.sort(key=lambda x: (x["kind"] != "Binding", x["label"]))
    laws_out.sort(key=lambda x: x["label"])
    all_letters = letters.letters(db, org.id)
    current = all_letters[0] if all_letters else None
    from app.engagements.models import Engagement

    e = db.scalar(select(Engagement).where(Engagement.client_id == org.id, Engagement.deleted_at.is_(None)).order_by(Engagement.created_at.desc()).limit(1))
    contact = letters.caico_contact(db, org.id)
    return {
        "client": {"id": org.id, "name": org.trading_name or org.name, "client_ref": org.client_ref, "engagement_status": e.status if e else None},
        "caico": {"name": contact.name, "email": contact.email} if contact else None,
        "geographies": geos, "laws_in": laws_in, "laws_out": laws_out,
        "roles": [{**r, "sources": r["sources"]} for r in engine.required_roles(db, org.id)],
        "committees": engine.committees(db, org.id),
        "changes_since_letter": letters.changes_since(db, org.id),
        "letter": _letter_out(db, current) if current else None,
        "letters": [_letter_out(db, x, html=False) for x in all_letters],
        "bases": list(engine.BASES),
        "can_edit": bool(actor.role_names & {"chief_auditor", "admin"}),
        "can_approve": "chief_auditor" in actor.role_names,
    }


class GeoIn(BaseModel):
    jurisdiction_code: str
    basis: str


@router.post("/clients/{client_id}/geographies")
def add_geo(client_id: str, body: GeoIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _client(db, actor, client_id, Action.EDIT_APPLICABILITY)
    j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == body.jurisdiction_code.strip().upper()))
    if j is None:
        raise Invalid(errors=[{"field": "jurisdiction_code", "message": "Choose a geography from the list."}])
    g = engine.add_geography(db, org.id, j.id, body.basis, actor.id)
    audit.record(db, actor_id=actor.id, action="applicability.geography_add", obj=g, summary=f"Added {j.name} ({body.basis}) to {org.name}'s geographies")
    return {"id": g.id}


@router.delete("/clients/{client_id}/geographies/{geo_id}")
def remove_geo(client_id: str, geo_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _client(db, actor, client_id, Action.EDIT_APPLICABILITY)
    g = db.get(ClientGeography, geo_id)
    if g is None or g.organization_id != org.id or g.deleted_at:
        raise NotFound()
    engine.remove_geography(db, g, actor.id)
    j = db.get(Jurisdiction, g.jurisdiction_id)
    audit.record(db, actor_id=actor.id, action="applicability.geography_remove", obj=g, summary=f"Removed {j.name if j else 'a geography'} ({g.basis}) from {org.name}'s geographies")
    return {"ok": True}


class AnswersIn(BaseModel):
    answers: dict[str, str | None]


@router.put("/clients/{client_id}/applicability/{regulation_id}/answers")
def put_answers(client_id: str, regulation_id: str, body: AnswersIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _client(db, actor, client_id, Action.EDIT_APPLICABILITY)
    row = engine.set_answers(db, org.id, regulation_id, body.answers, actor.id)
    audit.record(db, actor_id=actor.id, action="applicability.answers", obj=row, after=body.answers, summary=f"Answered scope questions for {org.name}")
    return {"in_scope": row.in_scope, "reason": row.reason_text}


class OverrideIn(BaseModel):
    in_scope: bool | None
    reason: str | None = None


@router.put("/clients/{client_id}/applicability/{regulation_id}/override")
def put_override(client_id: str, regulation_id: str, body: OverrideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _client(db, actor, client_id, Action.EDIT_APPLICABILITY)
    row = engine.override(db, org.id, regulation_id, body.in_scope, body.reason, actor.id)
    audit.record(db, actor_id=actor.id, action="applicability.override", obj=row, after={"in_scope": body.in_scope, "reason": body.reason}, summary=f"Set a law {'in' if body.in_scope else 'out of' if body.in_scope is False else 'back to automatic'} scope for {org.name}")
    return {"in_scope": row.in_scope, "reason": row.reason_text, "override": row.override}


def _letter(db: Session, org: Organization, letter_id: str) -> IntroLetter:
    x = db.get(IntroLetter, letter_id)
    if x is None or x.organization_id != org.id or x.deleted_at:
        raise NotFound()
    return x


@router.post("/clients/{client_id}/letters")
def draft_letter(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _client(db, actor, client_id, Action.EDIT_APPLICABILITY)
    return _letter_out(db, letters.draft(db, org, actor.user))


class LetterEditIn(BaseModel):
    opening: str | None = None
    closing: str | None = None


@router.patch("/clients/{client_id}/letters/{letter_id}")
def edit_letter(client_id: str, letter_id: str, body: LetterEditIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _client(db, actor, client_id, Action.EDIT_APPLICABILITY)
    return _letter_out(db, letters.edit(db, _letter(db, org, letter_id), actor.user, body.opening, body.closing))


@router.post("/clients/{client_id}/letters/{letter_id}/approve")
def approve_letter(client_id: str, letter_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _client(db, actor, client_id, Action.APPROVE_INTRO_LETTER)
    return _letter_out(db, letters.approve(db, request.app.state.settings, _letter(db, org, letter_id), actor.user))


@router.post("/clients/{client_id}/letters/{letter_id}/send")
def send_letter(client_id: str, letter_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _client(db, actor, client_id, Action.APPROVE_INTRO_LETTER)
    return _letter_out(db, letters.send(db, request.app.state.settings, _letter(db, org, letter_id), actor.user))


def file_access(db: Session, actor: Actor, f) -> None:
    """Intro letter PDFs: Futran staff who can see the client's applicability; the client once the letter is sent."""
    x = db.get(IntroLetter, f.linked_id) if f.linked_id else None
    if x is None:
        raise NotFound()
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_APPLICABILITY, org_id=x.organization_id)
        return
    if x.organization_id != actor.organization.id or x.status != "sent":
        raise NotFound()
