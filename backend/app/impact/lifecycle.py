"""Working a reassessment trigger: start, resolve (with what was reassessed, written to the system's history log) or dismiss."""
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.impact.models import OPEN_TRIGGER
from app.impact.triggers import TYPE_LABELS


def act(db: Session, actor, t, s, action: str, note: str | None):
    from app.register.history import add_entry

    note = (note or "").strip()
    if action not in ("start", "resolve", "dismiss"):
        raise NotFound()
    if t.status not in OPEN_TRIGGER:
        raise Conflict("This trigger is already closed.")
    if action == "start":
        t.status = "in_progress"
    else:
        if not note:
            raise Invalid(errors=[{"field": "note", "message": "Say what was reassessed." if action == "resolve" else "Say why no reassessment is needed."}])
        t.status = "resolved" if action == "resolve" else "dismissed"
        t.resolution_note, t.resolved_by, t.resolved_at = note[:4000], actor.id, utcnow()
        if action == "resolve":
            add_entry(db, actor, s, {"type": "impact_assessment", "occurred_on": utcnow().date().isoformat(),
                                     "summary": f"Reassessed after: {TYPE_LABELS[t.type].lower()}. {note}"[:4000], "details": {"outcome": "Reassessed"}})
    t.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action=f"reassessment.{action}", obj=t, organization_id=t.organization_id, after={"status": t.status, "note": note or None},
                 summary=f"Reassessment trigger on {s.reference} {s.name}: {t.status.replace('_', ' ')}")
    return t
