"""Monitoring check "Reassessment overdue" (spec §21 F3 registry; F8 data). Read-only.

Per register system with an open reassessment trigger: attention while it is under 30 days old, failed after. A live
system last assessed more than 12 months ago with no trigger yet (the daily schedule has not run) is failed too.
"""
from datetime import timedelta

from sqlalchemy import select

from app.core.clock import utcnow
from app.monitoring.registry import CheckOutcome, register_check

OVERDUE_DAYS = 30


def _reassessment_overdue(db, org) -> list[CheckOutcome]:
    from app.impact.models import OPEN_TRIGGER, ReassessmentTrigger
    from app.impact.schedule import due_systems
    from app.impact.triggers import TYPE_LABELS
    from app.register.models import RegisterSystem

    now = utcnow()
    oldest: dict[str, ReassessmentTrigger] = {}
    for t in db.scalars(select(ReassessmentTrigger).where(ReassessmentTrigger.organization_id == org.id, ReassessmentTrigger.status.in_(OPEN_TRIGGER),
                                                          ReassessmentTrigger.deleted_at.is_(None)).order_by(ReassessmentTrigger.detected_at)):
        oldest.setdefault(t.register_system_id, t)
    out = []
    for sid, t in oldest.items():
        s = db.get(RegisterSystem, sid)
        if s is None or s.deleted_at is not None or s.stage == "retired":
            continue
        days = (now - t.detected_at).days
        status = "failed" if days >= OVERDUE_DAYS else "attention"
        out.append(CheckOutcome(s.id, f"{s.reference} {s.name}", status, f"{TYPE_LABELS[t.type]}, open {days} {'day' if days == 1 else 'days'}",
                                f"/register/{s.id}", action="open", register_system_id=s.id))
    for s, last in due_systems(db, now.date(), org.id):
        if s.id not in oldest:
            out.append(CheckOutcome(s.id, f"{s.reference} {s.name}", "failed", f"Last assessed {last.day} {last:%B %Y}", f"/register/{s.id}",
                                    action="start_reassessment", register_system_id=s.id))
    return out


register_check("reassessment_overdue", "Reassessment overdue", "high", "monthly", "system", _reassessment_overdue)
