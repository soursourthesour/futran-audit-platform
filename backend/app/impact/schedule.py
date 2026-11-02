"""The 12-month reassessment trigger (spec §21 F8), run by the daily job."""
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.impact.triggers import raise_trigger

YEAR = timedelta(days=365)


ASSESSED = ("initiated", "in_progress", "completed", "archived")  # an engagement that has started assesses its systems
UNDER_WAY = ("initiated", "in_progress")


def _engagement_rows(db: Session, s, statuses):
    from app.engagements.models import Engagement
    from app.systems.models import AISystem

    return db.execute(select(AISystem, Engagement).join(Engagement, Engagement.id == AISystem.engagement_id)
                      .where(AISystem.register_system_id == s.id, AISystem.deleted_at.is_(None), Engagement.deleted_at.is_(None),
                             Engagement.status.in_(statuses))).all()


def under_assessment(db: Session, s) -> bool:
    """True while a Futran engagement that has started is assessing this system and its assessment is not yet signed:
    that engagement is the reassessment."""
    return any(system.status != "locked" for system, _e in _engagement_rows(db, s, UNDER_WAY))


def _engagement_dates(db: Session, s) -> list:
    """For each Futran engagement that assessed this system: when it started (fieldwork start or approval), when the
    system was last scored, when its score was locked at sign-off and when the engagement completed."""
    from app.scoring.models import SystemRiskScore

    out = []
    for system, e in _engagement_rows(db, s, ASSESSED):
        out += [e.fieldwork_start, e.approved_at, e.completed_at]
        out += list(db.execute(select(func.max(SystemRiskScore.created_at), func.max(SystemRiskScore.locked_at))
                               .where(SystemRiskScore.ai_system_id == system.id, SystemRiskScore.deleted_at.is_(None))).one())
    return out


def last_assessed(db: Session, s) -> date | None:
    """The latest of: go-live, an impact assessment or reassessment in the history log, a resolved trigger, a 12-month
    trigger resolved or dismissed (handled for its cycle: the next one is due 12 months later), an approved
    pre-deployment assessment, and a Futran engagement that assessed the system."""
    from app.impact.models import ImpactAssessment, ReassessmentTrigger
    from app.register.models import HistoryEntry

    dates = [s.live_since]
    dates.append(db.scalar(select(func.max(HistoryEntry.occurred_on)).where(HistoryEntry.register_system_id == s.id, HistoryEntry.type == "impact_assessment",
                                                                         HistoryEntry.deleted_at.is_(None))))
    for v in (db.scalar(select(func.max(ReassessmentTrigger.resolved_at)).where(ReassessmentTrigger.register_system_id == s.id, ReassessmentTrigger.status == "resolved")),
              db.scalar(select(func.max(func.coalesce(ReassessmentTrigger.resolved_at, ReassessmentTrigger.detected_at)))
                        .where(ReassessmentTrigger.register_system_id == s.id, ReassessmentTrigger.type == "twelve_months",
                               ReassessmentTrigger.status.in_(("resolved", "dismissed")), ReassessmentTrigger.deleted_at.is_(None))),
              db.scalar(select(func.max(ImpactAssessment.decided_at)).where(ImpactAssessment.register_system_id == s.id, ImpactAssessment.decision != "rejected")),
              *_engagement_dates(db, s)):
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
        if last is not None and on - last >= YEAR and not under_assessment(db, s):
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
