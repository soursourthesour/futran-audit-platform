"""The requirements checklist for a register system (spec §27.2): every Requirement of the current version of each law on
the system, with its status and the log entries and evidence that prove it. A requirement needed before use or go-live
that is not met counts in the go-live gate (§24.3)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Invalid, NotFound
from app.register import service as svc
from app.register.models import REQUIREMENT_STATUSES, HistoryEntry, RegisterSystem, RequirementStatus
from app.register.roles import BOUGHT, GATE_STAGES, STAGE_LABELS, current_version, developer_only
from app.tenancy.models import User

STATUS_LABELS = {"met": "Met", "partly_met": "Partly met", "not_met": "Not met", "not_applicable": "Not applicable"}


def system_ai_types(s: RegisterSystem) -> set[str]:
    out = {"all"}
    if s.type == "agent":
        out.add("agent")
    if s.decision_impact in ("informs", "consequential"):
        out.add("decision")
    if s.type == "embedded_feature":
        out.add("embedded")
    if s.type in ("genai_chat_tool", "foundation_model_api") or s.algorithm_type in ("llm", "llm_agent"):
        out.add("genai")
    return out


def requirements_for(db: Session, s: RegisterSystem) -> list[tuple]:
    """[(requirement, regulation)] that apply to the system, in law then requirement order."""
    from app.regmaster.models import Requirement

    types = system_ai_types(s)
    signed = signed_supplier_roles(db, s)
    out = []
    for link in svc.law_links(db, s):
        reg, v = current_version(db, link.regulation_id)
        if v is None:
            continue
        for req in db.scalars(select(Requirement).where(Requirement.law_version_id == v.id).order_by(Requirement.order, Requirement.code)):
            if s.sourcing in BOUGHT and developer_only(req.applies_to):
                continue
            if req.ai_types and "all" not in req.ai_types and not (set(req.ai_types) & types):
                continue
            if supplier_only(req.applies_to) and not _supplier_applies(db, s, req, signed):
                continue
            out.append((req, reg))
    return out


# ---- EU AI Act supplier-side duties (R6b, G-08). Provider, importer and distributor rows apply to whoever builds,
# imports or distributes a system. Until the legal reviewer signs off the system's role in the EU AI Act workspace,
# every row shows exactly as before Release 2. A signed-off role hides only the unanswered supplier rows it does not
# carry (a deployer sign-off hides unanswered provider rows); a row with an answer always stays, marked "may not apply".
SUPPLIER_ROLES = {"provider", "importer", "distributor"}
SIGNED_ROLE_DUTIES = {"provider": {"provider"}, "product_manufacturer": {"provider"}, "importer": {"importer"}, "distributor": {"distributor"}, "deployer": set()}


def supplier_only(applies_to: list | None) -> bool:
    a = set(applies_to or [])
    return bool(a & SUPPLIER_ROLES) and a <= SUPPLIER_ROLES | {"developer"}


def signed_supplier_roles(db: Session, s: RegisterSystem) -> set[str] | None:
    """The supplier duties of the role signed off in G-08 for this system, or None when nothing is signed off."""
    try:
        from app.euaiact.models import EuAiActRecord
    except ImportError:  # pragma: no cover
        return None
    rec = db.scalar(select(EuAiActRecord).where(EuAiActRecord.register_system_id == s.id, EuAiActRecord.deleted_at.is_(None), EuAiActRecord.signoff_status == "signed_off"))
    if rec is None or not rec.role:
        return None
    return set(SIGNED_ROLE_DUTIES.get(rec.role, set()))


def _supplier_applies(db: Session, s: RegisterSystem, req, signed: set[str] | None) -> bool:
    if signed is None or set(req.applies_to or []) & signed:  # no signed-off role: unchanged from before Release 2
        return True
    st, _ = _status(db, s, req)
    return st is not None


def may_not_apply(db: Session, s: RegisterSystem, req) -> bool:
    """A supplier-side row kept only because it was answered, on a system whose signed-off role does not carry it."""
    if not supplier_only(req.applies_to):
        return False
    signed = signed_supplier_roles(db, s)
    return signed is not None and not (set(req.applies_to or []) & signed)


def _status(db: Session, s: RegisterSystem, req) -> tuple[RequirementStatus | None, bool]:
    """The status row for this requirement, else one recorded against the same code of an earlier version of the law,
    on any row of the law (a Reference data edit replaces the Regulation row and copies its version under the new row)."""
    from app.laws.publish import chain_ids
    from app.regmaster.models import LawVersion, Requirement

    row = db.scalar(select(RequirementStatus).where(RequirementStatus.register_system_id == s.id, RequirementStatus.requirement_id == req.id, RequirementStatus.deleted_at.is_(None)))
    if row is not None:
        return row, False
    v = db.get(LawVersion, req.law_version_id)
    regs = chain_ids(db, v.regulation_id) or [v.regulation_id]
    older = select(Requirement.id).join(LawVersion, LawVersion.id == Requirement.law_version_id).where(LawVersion.regulation_id.in_(regs), Requirement.code == req.code, Requirement.id != req.id)
    prev = db.scalar(select(RequirementStatus).where(RequirementStatus.register_system_id == s.id, RequirementStatus.requirement_id.in_(older), RequirementStatus.deleted_at.is_(None))
                     .order_by(RequirementStatus.checked_at.desc()).limit(1))
    return prev, prev is not None


def checklist(db: Session, s: RegisterSystem) -> dict:
    rows = []
    for req, reg in requirements_for(db, s):
        st, carried = _status(db, s, req)
        status = st.status if st else "not_met"
        entries = [e for e in (db.get(HistoryEntry, i) for i in (st.history_entry_ids if st else []) or []) if e is not None and e.deleted_at is None]
        from app.files.models import FileObject

        files = [f for f in (db.get(FileObject, i) for i in (st.evidence_ids if st else []) or []) if f is not None and f.deleted_at is None]
        linked = [e for e in db.scalars(select(HistoryEntry).where(HistoryEntry.register_system_id == s.id, HistoryEntry.deleted_at.is_(None))) if req.id in (e.requirement_ids or []) or req.code in (e.requirement_ids or [])]
        checker = db.get(User, st.checked_by) if st and st.checked_by else None
        rows.append({
            "id": req.id, "code": req.code, "text": req.text, "law": reg.short_name, "regulation_id": reg.id, "citation": req.citation, "evidence_text": req.evidence_text,
            "needed_by": req.needed_by_stage, "needed_by_label": STAGE_LABELS.get(req.needed_by_stage or "", "Ongoing"), "gate": (req.needed_by_stage or "") in GATE_STAGES,
            "status": status, "status_label": STATUS_LABELS[status], "note": st.note if st else None,
            "history_entries": [{"id": e.id, "type": e.type, "occurred_on": e.occurred_on.isoformat(), "summary": e.summary} for e in {x.id: x for x in entries + linked}.values()],
            "evidence": [{"id": f.id, "filename": f.filename} for f in files], "checked_by": checker.name if checker else None,
            "checked_at": st.checked_at.isoformat() if st and st.checked_at else None, "carried_from_previous_version": carried,
            "may_not_apply": may_not_apply(db, s, req),
        })
    return {"rows": rows, "total": len(rows), "met": sum(1 for r in rows if r["status"] == "met"), "blocking": sum(1 for r in rows if r["gate"] and r["status"] == "not_met")}


def gate_blockers(db: Session, s: RegisterSystem) -> list[str]:
    """Requirements needed before use or go-live that are not met."""
    out = []
    prohibited = signed_classification(db, s) == "prohibited"
    for req, _reg in requirements_for(db, s):
        if (req.needed_by_stage or "") not in GATE_STAGES and not (prohibited and _is_art5(req)):
            continue
        st, _ = _status(db, s, req)
        if (st.status if st else "not_met") == "not_met":
            out.append(f"{req.code} {req.text} (not met)")
    return out


def set_status(db: Session, actor: User, s: RegisterSystem, requirement_id: str, data: dict) -> RequirementStatus:
    pair = next(((r, reg) for r, reg in requirements_for(db, s) if r.id == requirement_id), None)
    if pair is None:
        raise NotFound("This requirement does not apply to this system.")
    req, reg = pair
    errs: list[dict] = []
    status = data.get("status")
    if status not in REQUIREMENT_STATUSES:
        errs.append({"field": "status", "message": "Choose met, partly met, not met or not applicable."})
    note = str(data.get("note") or "").strip()[:2000] or None
    if status in ("not_applicable", "partly_met") and not note:
        errs.append({"field": "note", "message": "Say why it does not apply." if status == "not_applicable" else "Say what is still missing."})
    entry_ids = data.get("history_entry_ids")
    if entry_ids is not None:
        if not isinstance(entry_ids, list) or any(not isinstance(i, str) or (lambda e: e is None or e.deleted_at is not None or e.register_system_id != s.id)(db.get(HistoryEntry, i)) for i in entry_ids):
            errs.append({"field": "history_entry_ids", "message": "Choose entries from this system's history log."})
    ev = data.get("evidence_ids")
    if ev is not None:
        if not isinstance(ev, list):
            errs.append({"field": "evidence_ids", "message": "Upload the file again."})
        else:
            for i in ev:
                svc._file(db, s.organization_id, i, "evidence_ids", errs)
    if errs:
        raise Invalid(errors=errs)
    row = db.scalar(select(RequirementStatus).where(RequirementStatus.register_system_id == s.id, RequirementStatus.requirement_id == req.id, RequirementStatus.deleted_at.is_(None)))
    prev, _ = _status(db, s, req)
    old = prev.status if prev else "not_met"
    if row is None:
        row = RequirementStatus(organization_id=s.organization_id, register_system_id=s.id, requirement_id=req.id, created_by=actor.id,
                                history_entry_ids=list(prev.history_entry_ids or []) if prev else [], evidence_ids=list(prev.evidence_ids or []) if prev else [])
        db.add(row)
    row.status, row.note, row.checked_by, row.checked_at, row.updated_by = status, note, actor.id, utcnow(), actor.id
    if entry_ids is not None:
        row.history_entry_ids = list(dict.fromkeys(entry_ids))
    if ev is not None:
        row.evidence_ids = list(dict.fromkeys(ev))
    db.flush()
    svc.log_change(db, actor, s, f"requirement:{req.code}", STATUS_LABELS[old], STATUS_LABELS[status], note, entity="RequirementStatus", entity_id=row.id, raw=True)
    audit.record(db, actor_id=actor.id, action="register.requirement_status", obj=s, before={"status": old}, after={"requirement": f"{reg.short_name} {req.code}", "status": status, "note": note},
                 summary=f"{reg.short_name} {req.code} marked {STATUS_LABELS[status].lower()} for {s.reference} {s.name}")
    return row


def signed_classification(db: Session, s: RegisterSystem) -> str | None:
    try:
        from app.euaiact.models import EuAiActRecord
    except ImportError:  # pragma: no cover
        return None
    rec = db.scalar(select(EuAiActRecord).where(EuAiActRecord.register_system_id == s.id, EuAiActRecord.deleted_at.is_(None), EuAiActRecord.signoff_status == "signed_off"))
    return rec.classification if rec else None


def _is_art5(req) -> bool:
    """The EU AI Act prohibited-practice screen: a blocker only on a system signed off as prohibited (R6b, G-08)."""
    from app.euaiact.rules import article_refs

    return "EU AI Act" in (req.citation or "") and any(r == "5" or r.startswith("5(") for r in article_refs(req.citation))
