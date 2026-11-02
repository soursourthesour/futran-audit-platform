"""The 12-month reassessment trigger (spec §21 F8), run by the daily job."""
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.impact.triggers import raise_trigger

YEAR = timedelta(days=365)


def last_assessed(db: Session, s) -> date | None:
    """The latest of: go-live, an impact assessment or reassessment in the history log, a resolved trigger, an approved
    pre-deployment assessment."""
    from app.impact.models import ImpactAssessment, ReassessmentTrigger
    from app.register.models import HistoryEntry

    dates = [s.live_since]
    dates.append(db.scalar(select(func.max(HistoryEntry.occurred_on)).where(HistoryEntry.register_system_id == s.id, HistoryEntry.type == "impact_assessment",
                                                                         HistoryEntry.deleted_at.is_(None))))
    for v in (db.scalar(select(func.max(ReassessmentTrigger.resolved_at)).where(ReassessmentTrigger.register_system_id == s.id, ReassessmentTrigger.status == "resolved")),
              db.scalar(select(func.max(ImpactAssessment.decided_at)).where(ImpactAssessment.register_system_id == s.id, ImpactAssessment.decision != "rejected"))):
        dates.append(v.date() if isinstance(v, datetime) else v)
    known = [d for d in dates if d]
    return max(known) if known else None


def due_systems(db: Session, on: date, org_id: str | None = None) -> list[tuple[object, date]]:
    from app.register.models import RegisterSystem

    stmt = select(RegisterSystem).where(RegisterSystem.stage == "live", RegisterSystem.deleted_at.is_(None))
    if org_id:
        stmt = stmt.where(RegisterSystem.organization_id == org_id)
    out = []
    for s in db.scalars(stmt.order_by(RegisterSystem.reference)):
        last = last_assessed(db, s)
        if last is not None and on - last >= YEAR:
            out.append((s, last))
    return out


def run_reassessment_schedule(db: Session, settings, now) -> int:
    """Raise a "12 months elapsed" trigger on each live system last assessed a year or more ago. Returns how many were raised."""
    on = now.date() if isinstance(now, datetime) else now
    n = 0
    for s, last in due_systems(db, on):
        ref = f"12m:{(last + YEAR).isoformat()}"
        from app.impact.triggers import open_trigger_for

        if open_trigger_for(db, s.id, "twelve_months", "schedule", ref) is not None:
            continue
        if raise_trigger(db, s.id, type="twelve_months", source="schedule", source_ref=ref, detail=f"Last assessed {last.day} {last:%B %Y}") is not None:
            n += 1
    return n
