"""Scheduled jobs for the tracing add-on, in the pattern of app.notifications.jobs (`run_<job>(db, settings, now)`).

- run_incident_deadlines: remind once a quarter of the period before a notice is due (at most 24 hours before) and say once
  when it is missed. Runs in the daily run and every 15 minutes, because the CERT-In period is 6 hours.
The recommended add-on opportunity (§27.5) is WS-D's daily job (app.sales.service.open_recommended_addon_opportunities); it
skips systems the add-on already covers or that wait for approval (app.tracing.addons.covered_ids).
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.notifications.service import notify
from app.register.models import RegisterSystem
from app.tracing.deadlines import reminder_at
from app.tracing.models import Incident, IncidentDeadline


def _left(due: datetime, now: datetime) -> str:
    mins = max(int((due - now).total_seconds() // 60), 0)
    d, rem = divmod(mins, 24 * 60)
    h, m = divmod(rem, 60)
    parts = ([f"{d} d"] if d else []) + ([f"{h} h"] if h else []) + ([f"{m} min"] if m and not d else [])
    return " ".join(parts) or "under a minute"


def run_incident_deadlines(db: Session, settings, now: datetime) -> int:
    from app.tracing.incidents import _fmt, recipients

    now = now if isinstance(now, datetime) else datetime.combine(now, datetime.min.time())
    sent = 0
    rows = db.scalars(select(IncidentDeadline).where(IncidentDeadline.status == "open").order_by(IncidentDeadline.due_at))
    for d in rows:
        inc = db.get(Incident, d.incident_id)
        if inc is None or inc.deleted_at is not None or inc.status == "closed":
            continue
        s = db.get(RegisterSystem, inc.register_system_id)
        note = "" if d.binding else " (good practice until the duty applies)"
        link = f"/register/{s.id}/tracing"
        if now >= d.due_at:
            if d.overdue_notified_at is None:
                notify(db, recipients(db, s, inc), "incident_deadline_missed", f"Missed: {inc.code} notice to {d.recipient} was due {_fmt(d.due_at)}{note}",
                       f"{s.name}: {inc.description[:200]}. {d.citation}: {d.period_text}. Make the notice now and record it, or mark it not applicable with the reason.",
                       link, settings=settings, email_template="notification")
                d.overdue_notified_at = d.reminded_at = now
                sent += 1
        elif now >= reminder_at(d.clock_start_at, d.due_at) and d.reminded_at is None:
            notify(db, recipients(db, s, inc), "incident_deadline_reminder", f"{inc.code}: notice to {d.recipient} due in {_left(d.due_at, now)}{note}",
                   f"{s.name}: {inc.description[:200]}. Due {_fmt(d.due_at)} ({d.citation}: {d.period_text}).", link, settings=settings, email_template="notification")
            d.reminded_at = now
            sent += 1
    db.flush()
    return sent

