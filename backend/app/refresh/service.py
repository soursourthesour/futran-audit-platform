"""Shared Claude refresh pipeline for laws and litigation (spec §25.3, §27.4): summaries used by alerts and screens."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.refresh.models import RefreshRun
from app.regmaster.models import ChangeImpact, ProposedChange

OPEN_STATUSES = ("pending", "held", "legal_review")
GROUPS = {
    "new_law": "new_laws",
    "amendment": "amendments_dates", "effective_date": "amendments_dates", "repeal": "amendments_dates",
    "new_rule": "rules_guidance", "guidance": "rules_guidance", "role_mapping": "rules_guidance",
    "enforcement": "enforcement",
    "new_case": "case_updates", "case_update": "case_updates",
}
GROUP_LABELS = {
    "new_laws": "New laws", "amendments_dates": "Amendments and dates", "rules_guidance": "New rules or guidance",
    "enforcement": "Enforcement actions", "case_updates": "Case updates",
}


def run_changes(db: Session, run_id: str) -> list[ProposedChange]:
    """Changes first proposed in this run, plus duplicates from later runs merged into earlier proposals."""
    from app.refresh.models import RefreshProposalMeta

    rows = {c.id: c for c in db.scalars(select(ProposedChange).where(ProposedChange.refresh_run_id == run_id))}
    for meta in db.scalars(select(RefreshProposalMeta)):
        if run_id in (meta.run_ids or []) and meta.proposed_change_id not in rows:
            c = db.get(ProposedChange, meta.proposed_change_id)
            if c is not None:
                rows[c.id] = c
    return list(rows.values())


def open_items(db: Session, run_id: str) -> int:
    return sum(c.status in OPEN_STATUSES for c in run_changes(db, run_id))


def run_summary(db: Session, run: RefreshRun) -> dict:
    changes = run_changes(db, run.id)
    counts = {k: 0 for k in GROUP_LABELS}
    for c in changes:
        g = GROUPS.get(c.change_type)
        if g:
            counts[g] += 1
    ids = [c.id for c in changes]
    impacts = list(db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id.in_(ids)))) if ids else []
    systems = {s for i in impacts for s in (i.ai_system_ids or [])}
    low = [c for c in changes if c.confidence == "low"]
    return {
        "kind": run.kind, "trigger": run.trigger, "sources_read": run.sources_read, "total": len(changes), "counts": counts,
        "open": sum(c.status in OPEN_STATUSES for c in changes),
        "clients_affected": len({i.organization_id for i in impacts}), "systems_affected": len(systems),
        "low_confidence": len(low), "low_confidence_items": [c.summary for c in low][:10],
        "new_laws": counts["new_laws"],
    }


def last_run_summary(db: Session, kind: str) -> dict | None:
    run = db.scalar(select(RefreshRun).where(RefreshRun.kind == kind).order_by(RefreshRun.started_at.desc()).limit(1))
    if run is None:
        return None
    s = run_summary(db, run)
    return {"id": run.id, "status": run.status, "started_at": run.started_at.isoformat(), "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "open": s["open"], "total": s["total"], "alert_status": run.alert_status}
