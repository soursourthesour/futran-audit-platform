"""Reassessment triggers (spec §21 F8): one entry point, `raise_trigger`, for every source.

Callers: register edits (`app.impact.detect`), published regulatory updates (`app.regupdates.service`), the 12-month
schedule (`app.impact.schedule`), the "Reassessment overdue" check, and failed monitoring checks (WS-J calls
`raise_trigger(db, register_system_id, type="failed_monitor_check", source="monitor")`).

A trigger reopens the affected sections of the system's assessment while the system is in a current engagement: the
auditor's verification of the answers in those sections is cleared, and a scored system goes back to "in review" so its
score is not taken as final. A locked (signed) assessment is never touched: monitoring never changes a signed report.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.impact.models import OPEN_TRIGGER, TRIGGER_SOURCES, TRIGGER_TYPES, ReassessmentTrigger

TYPE_LABELS = {
    "version_change": "System version changed", "new_data_category": "New type of data", "new_jurisdiction": "New jurisdiction",
    "new_population": "New group of people affected", "vendor_change": "Vendor or provider changed", "failed_monitor_check": "Failed monitoring check",
    "regulatory_update": "Regulatory update affects it", "twelve_months": "12 months since the last assessment",
}
SOURCE_LABELS = {"manual": "Raised by hand", "monitor": "Continuous monitoring", "regulatory_update": "Regulatory update", "schedule": "Schedule",
                 "register_edit": "Register edit"}
# Template sub-sections each trigger makes out of date (question bank §3–§9). None = every section of the system.
SECTIONS: dict[str, list[str] | None] = {
    "version_change": ["3.1", "3.2", "6.1", "6.3", "8.1"],
    "new_data_category": ["5.1", "5.1a", "5.2", "5.3"],
    "new_jurisdiction": ["5.2", "7.2"],
    "new_population": ["3.3", "5.1a", "6.2", "7.2"],
    "vendor_change": ["3.2", "V", "9.2"],
    "failed_monitor_check": ["8.2"],
    "regulatory_update": ["5.2", "6.2", "7.1", "7.2"],
    "twelve_months": None,
}
CURRENT_ENGAGEMENT = ("pending_approval", "initiated", "in_progress")


def open_trigger_for(db: Session, register_system_id: str, type: str, source: str, source_ref: str | None) -> ReassessmentTrigger | None:
    stmt = select(ReassessmentTrigger).where(ReassessmentTrigger.register_system_id == register_system_id, ReassessmentTrigger.type == type,
                                             ReassessmentTrigger.status.in_(OPEN_TRIGGER), ReassessmentTrigger.deleted_at.is_(None))
    stmt = stmt.where(ReassessmentTrigger.source_ref == source_ref) if source_ref else stmt.where(ReassessmentTrigger.source == source)
    return db.scalar(stmt.limit(1))


def raise_trigger(db: Session, register_system_id: str, type: str, source: str, detail: str | None = None, source_ref: str | None = None,
                  actor_id: str | None = None) -> ReassessmentTrigger | None:
    """Open a reassessment trigger on a register system, once: an open trigger of the same type for the same reference
    (or, without a reference, from the same source) is returned instead. Returns None for an unknown, removed or retired system."""
    from app.register.models import RegisterSystem

    if type not in TRIGGER_TYPES:
        raise ValueError(f"Unknown trigger type {type!r}")
    if source not in TRIGGER_SOURCES:
        raise ValueError(f"Unknown trigger source {source!r}")
    s = db.get(RegisterSystem, register_system_id)
    if s is None or s.deleted_at is not None or s.stage == "retired":
        return None
    with db.no_autoflush:
        existing = open_trigger_for(db, s.id, type, source, source_ref)
    if existing is not None:
        return existing
    t = ReassessmentTrigger(organization_id=s.organization_id, register_system_id=s.id, type=type, source=source, source_ref=(source_ref or None) and source_ref[:120],
                            detail=(detail or None) and detail[:4000], detected_at=utcnow(), status="open", reopened=[], created_by=actor_id)
    db.add(t)
    db.flush()
    t.reopened = reopen_sections(db, s, type)
    audit.record(db, actor_id=actor_id, action="reassessment.trigger", obj=t, organization_id=s.organization_id,
                 after={"type": type, "source": source, "detail": t.detail, "reopened": t.reopened},
                 summary=f"Reassessment trigger on {s.reference} {s.name}: {TYPE_LABELS[type]}")
    _notify(db, s, t)
    return t


def reopen_sections(db: Session, s, type: str) -> list[dict]:
    """Clear the auditor's verification of the answers in the affected sections, in each current engagement that audits
    this register system. Returns what was reopened."""
    from app.engagements.models import Engagement
    from app.questionnaire.models import Question, Response
    from app.systems.models import AISystem

    wanted = SECTIONS.get(type)
    out = []
    rows = db.execute(select(AISystem, Engagement).join(Engagement, Engagement.id == AISystem.engagement_id)
                      .where(AISystem.register_system_id == s.id, AISystem.deleted_at.is_(None), Engagement.deleted_at.is_(None),
                             Engagement.status.in_(CURRENT_ENGAGEMENT)).order_by(AISystem.reference_id)).all()
    for system, e in rows:
        if system.status == "locked":
            continue
        q = select(Response, Question.sub_section).join(Question, Question.id == Response.question_id).where(Response.ai_system_id == system.id)
        if wanted is not None:
            q = q.where(Question.sub_section.in_(wanted))
        n = 0
        sections = set(wanted or [])
        for r, sub in db.execute(q).all():
            sections.add(sub)
            if r.verified_at is not None:
                r.verified_by = r.verified_at = None
                n += 1
        if system.status == "scored":
            system.status = "in_review"
        out.append({"engagement_id": e.id, "ai_system_id": system.id, "reference": system.reference_id, "sections": wanted or sorted(sections), "answers_reopened": n})
    db.flush()
    return out


def _notify(db: Session, s, t: ReassessmentTrigger) -> None:
    from app.engagements.models import Engagement
    from app.notifications.service import futran_team, notify
    from app.register.service import compliance_officers
    from app.tenancy.models import User

    people = compliance_officers(db, s.organization_id)
    owner = db.get(User, s.owner_user_id) if s.owner_user_id else None
    if owner is not None and owner.deleted_at is None:
        people.append(owner)
    title = f"Reassessment needed: {s.name}"
    notify(db, people, "reassessment_trigger", title, f"{TYPE_LABELS[t.type]}. {t.detail or ''}".strip(), f"/register/{s.id}")
    for r in t.reopened or []:
        e = db.get(Engagement, r["engagement_id"])
        notify(db, futran_team(db, e), "reassessment_trigger", f"Sections reopened on {r['reference']}: {TYPE_LABELS[t.type]}",
               f"{s.name}. Verify sections {', '.join(r['sections'])} again.", f"/systems/{r['ai_system_id']}/assess", engagement=e)
