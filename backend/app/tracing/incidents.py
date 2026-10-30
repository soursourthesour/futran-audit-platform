"""R7 incident register (spec §27.3, §27.7) and its regulator deadline timers.

Which deadline rules can apply to a system depends on the laws that apply: those the applicability engine found in scope for
the client (WS-A, `in_scope_versions`) and those linked to the system in the register. Over-warning is the safer error, so
the union counts; a notice that does not apply is marked Not applicable with a reason, which stays on record.

Every incident is also an entry in the system's history log (§27.2): a new one is added, or an existing incident entry is
linked, and the main facts are kept in step on the entry.
"""
import re
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.notifications.service import notify
from app.register.models import HistoryEntry, RegisterSystem, RegisterSystemLaw
from app.tenancy.models import RoleAssignment, User
from app.tracing import deadlines as D
from app.tracing.access import incident_leads
from app.tracing.models import SERIOUS_KINDS, SEVERITIES, ActionTrace, Incident, IncidentDeadline

SEVERITY_LABELS = {"low": "Low", "medium": "Medium", "high": "High", "serious": "Serious"}
STATUS_LABELS = {"open": "Open", "contained": "Open · contained", "closed": "Closed"}
DEADLINE_STATUS_LABELS = {"open": "Open", "done": "Done", "not_applicable": "Not applicable", "withdrawn": "No longer needed"}
EDITABLE = ("description", "found_at", "severity", "serious_kind", "risk_to_rights", "cyber_incident", "ag_notice_received_on", "people_affected", "cause", "containment",
            "fix", "owner_id", "contained_on")


# ---- which law families apply
def _family(db: Session, reg) -> str | None:
    from app.reference.models import Jurisdiction

    j = db.get(Jurisdiction, reg.jurisdiction_id)
    codes = []
    while j is not None and len(codes) < 5:
        codes.append(j.code)
        j = db.get(Jurisdiction, j.parent_id) if j.parent_id else None
    name = f"{reg.short_name or ''} {reg.citation or ''}"
    if "EU" in codes and re.search(r"2024/1689|AI Act", name, re.I):
        return "eu_ai_act"
    if "US-CO" in codes:
        return "colorado"
    if "IN" in codes:
        return "india"
    return None


def law_families(db: Session, s: RegisterSystem) -> list[str]:
    from app.laws.models import Regulation
    from app.regmaster.engine import in_scope_versions

    regs = [r for r, _ in in_scope_versions(db, s.organization_id)]
    for link in db.scalars(select(RegisterSystemLaw).where(RegisterSystemLaw.register_system_id == s.id, RegisterSystemLaw.deleted_at.is_(None), RegisterSystemLaw.status != "removed")):
        reg = db.get(Regulation, link.regulation_id)
        if reg is not None:
            regs.append(reg)
    found = {f for f in (_family(db, r) for r in regs) if f}
    return [f for f in D.LAW_FAMILIES if f in found]


# ---- reading
def _iso(v) -> str | None:
    return v.isoformat() if v is not None else None


def deadlines_of(db: Session, inc: Incident) -> list[IncidentDeadline]:
    order = {r.code: i for i, r in enumerate(D.RULES)}
    rows = list(db.scalars(select(IncidentDeadline).where(IncidentDeadline.incident_id == inc.id)))
    return sorted(rows, key=lambda d: (d.status == "withdrawn", order.get(d.rule_code, 99), d.created_at))


def deadline_out(d: IncidentDeadline, now: datetime) -> dict:
    return {"id": d.id, "rule_code": d.rule_code, "recipient": d.recipient, "law": d.law, "citation": d.citation, "quote": d.quote, "source_url": d.source_url,
            "period_text": d.period_text, "statutory": d.statutory, "binding": d.binding, "binding_note": d.binding_note, "clock_start_at": _iso(d.clock_start_at),
            "due_at": _iso(d.due_at), "status": d.status, "status_label": DEADLINE_STATUS_LABELS[d.status], "done_at": _iso(d.done_at), "reference": d.reference,
            "na_reason": d.na_reason, "overdue": d.status == "open" and d.due_at < now}


def _done_at(rows: list[IncidentDeadline], provider: bool) -> datetime | None:
    hits = [d.done_at for d in rows if d.status == "done" and d.done_at and ((d.recipient == "AI provider") == provider)]
    return min(hits) if hits else None


def incident_out(db: Session, inc: Incident, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rows = deadlines_of(db, inc)
    live = [d for d in rows if d.status != "withdrawn"]
    open_ = [d for d in rows if d.status == "open"]
    owner = db.get(User, inc.owner_id) if inc.owner_id else None
    return {
        "id": inc.id, "code": inc.code, "register_system_id": inc.register_system_id, "found_at": _iso(inc.found_at), "description": inc.description,
        "severity": inc.severity, "severity_label": SEVERITY_LABELS[inc.severity], "serious_kind": inc.serious_kind, "serious_label": D.SERIOUS_LABELS[inc.serious_kind],
        "risk_to_rights": inc.risk_to_rights, "cyber_incident": inc.cyber_incident, "ag_notice_received_on": _iso(inc.ag_notice_received_on),
        "people_affected": inc.people_affected, "cause": inc.cause, "containment": inc.containment, "fix": inc.fix, "status": inc.status, "status_label": STATUS_LABELS[inc.status],
        "contained_on": _iso(inc.contained_on), "closed_on": _iso(inc.closed_on), "owner_id": inc.owner_id, "owner": owner.name if owner else None,
        "history_entry_id": inc.history_entry_id, "trace_ids": list(inc.trace_ids or []),
        # spec §27.7 fields, derived from the notices so they cannot drift from them
        "reportable": bool(live), "law": ", ".join(dict.fromkeys(d.law for d in live)) or None,
        "deadline_at": _iso(min((d.due_at for d in open_), default=None)), "reported_at": _iso(_done_at(rows, provider=False)),
        "provider_notified_at": _iso(_done_at(rows, provider=True)),
        "deadlines": [deadline_out(d, now) for d in rows],
        "created_at": _iso(inc.created_at),
    }


def incidents_of(db: Session, s: RegisterSystem) -> list[Incident]:
    return list(db.scalars(select(Incident).where(Incident.register_system_id == s.id, Incident.deleted_at.is_(None)).order_by(Incident.found_at.desc())))


def missed_count(db: Session, s: RegisterSystem, now: datetime) -> int:
    ids = [i.id for i in incidents_of(db, s)]
    if not ids:
        return 0
    rows = db.scalars(select(IncidentDeadline).where(IncidentDeadline.incident_id.in_(ids), IncidentDeadline.binding.is_(True)))
    return sum(1 for d in rows if (d.status == "open" and d.due_at < now) or (d.status == "done" and d.done_at and d.done_at > d.due_at))


# ---- validation
def _dt(v, field: str, errs: list) -> datetime | None:
    if v in (None, ""):
        return None
    try:
        out = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        errs.append({"field": field, "message": "Enter a date and time."})
        return None
    if out.tzinfo is not None:  # stored as naive UTC
        out = out.astimezone(timezone.utc).replace(tzinfo=None)
    return out


def _date(v, field: str, errs: list) -> date | None:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        errs.append({"field": field, "message": "Enter a date."})
        return None


def _clean(db: Session, s: RegisterSystem, data: dict, inc: Incident | None) -> dict:
    errs: list[dict] = []
    out: dict = {}
    now = utcnow()
    full = inc is None
    if full or "description" in data:
        v = (data.get("description") or "").strip()
        if not v:
            errs.append({"field": "description", "message": "Say what happened."})
        out["description"] = v[:4000]
    if full or "found_at" in data:
        v = _dt(data.get("found_at"), "found_at", errs)
        if v is None and not any(e["field"] == "found_at" for e in errs):
            errs.append({"field": "found_at", "message": "Enter when it was found. Regulator clocks start here."})
        elif v is not None and v > now:
            errs.append({"field": "found_at", "message": "This is in the future."})
        out["found_at"] = v
    if full or "severity" in data:
        v = data.get("severity")
        if v not in SEVERITIES:
            errs.append({"field": "severity", "message": "Choose the severity."})
        out["severity"] = v
    if "serious_kind" in data or full:
        v = data.get("serious_kind") or "none"
        if v not in SERIOUS_KINDS:
            errs.append({"field": "serious_kind", "message": "Choose whether it is a serious incident, and of what kind."})
        out["serious_kind"] = v
    for k in ("risk_to_rights", "cyber_incident"):
        if k in data or full:
            out[k] = bool(data.get(k))
    for k in ("ag_notice_received_on", "contained_on"):
        if k in data:
            out[k] = _date(data.get(k), k, errs)
            if out[k] is not None and out[k] > now.date():
                errs.append({"field": k, "message": "This is in the future."})
    if "people_affected" in data:
        v = data.get("people_affected")
        if v in (None, ""):
            out["people_affected"] = None
        else:
            try:
                n = int(v)
                if n < 0:
                    raise ValueError
                out["people_affected"] = n
            except (TypeError, ValueError):
                errs.append({"field": "people_affected", "message": "Enter a whole number, 0 or more."})
    for k in ("cause", "containment", "fix"):
        if k in data:
            out[k] = (data.get(k) or "").strip()[:4000] or None
    if "owner_id" in data:
        uid = data.get("owner_id") or None
        if uid is not None:
            u = db.get(User, uid)
            if u is None or u.organization_id != s.organization_id or u.deleted_at is not None:
                errs.append({"field": "owner_id", "message": "Choose a person in your organization."})
        out["owner_id"] = uid
    if errs:
        raise Invalid(errors=errs)
    return out


# ---- the history log link
def _sync_history(db: Session, inc: Incident, actor_id: str | None) -> None:
    he = db.get(HistoryEntry, inc.history_entry_id) if inc.history_entry_id else None
    if he is None:
        return
    rows = [d for d in deadlines_of(db, inc) if d.status != "withdrawn"]
    open_ = [d for d in rows if d.status == "open"]
    det = dict(he.details or {})
    for k in ("people_affected", "cause", "containment", "fix"):
        v = getattr(inc, k)
        if v is not None:
            det[k] = v
    det["reportable"] = bool(rows)
    if rows:
        det["law"] = ", ".join(dict.fromkeys(d.law for d in rows))
    if open_:
        det["deadline"] = min(d.due_at for d in open_).date().isoformat()
    reported = _done_at(rows, provider=False)
    if reported:
        det["reported_on"] = reported.date().isoformat()
    told = _done_at(rows, provider=True)
    if told:
        det["provider_told"], det["provider_told_on"] = True, told.date().isoformat()
    if inc.closed_on:
        det["closed_on"] = inc.closed_on.isoformat()
    he.details = det
    he.severity = inc.severity
    he.updated_by = actor_id


def _new_history_entry(db: Session, s: RegisterSystem, inc: Incident, actor_id: str | None) -> HistoryEntry:
    he = HistoryEntry(organization_id=s.organization_id, register_system_id=s.id, type="incident", occurred_on=inc.found_at.date(), summary=inc.description,
                      severity=inc.severity, details={}, recorded_by=actor_id, recorded_at=utcnow(), created_by=actor_id)
    db.add(he)
    db.flush()
    return he


# ---- deadlines kept in step
def sync_deadlines(db: Session, s: RegisterSystem, inc: Incident) -> list[IncidentDeadline]:
    """Create the notices the incident now needs; move the clock on open ones; withdraw open ones no longer needed.
    Recorded and not-applicable notices are never changed."""
    wanted = {d.rule.code: d for d in D.applicable(set(law_families(db, s)), found_at=inc.found_at, serious_kind=inc.serious_kind, risk_to_rights=inc.risk_to_rights,
                                                  cyber_incident=inc.cyber_incident, ag_notice_received_on=inc.ag_notice_received_on)}
    have = {d.rule_code: d for d in db.scalars(select(IncidentDeadline).where(IncidentDeadline.incident_id == inc.id))}
    added = []
    for code, due in wanted.items():
        row = have.get(code)
        if row is None:
            r = due.rule
            row = IncidentDeadline(organization_id=inc.organization_id, incident_id=inc.id, rule_code=code, recipient=r.recipient, law=r.law, citation=r.citation, quote=r.quote,
                                   source_url=r.source_url, period_text=r.period_text, statutory=r.statutory, binding=due.binding, binding_note=due.binding_note,
                                   clock_start_at=due.clock_start_at, due_at=due.due_at, status="open")
            db.add(row)
            added.append(row)
        elif row.status in ("open", "withdrawn"):
            if row.status == "withdrawn":
                row.status, row.reminded_at, row.overdue_notified_at = "open", None, None
            if row.due_at != due.due_at:
                row.reminded_at = row.overdue_notified_at = None
            row.clock_start_at, row.due_at, row.binding, row.binding_note = due.clock_start_at, due.due_at, due.binding, due.binding_note
    for code, row in have.items():
        if code not in wanted and row.status == "open":
            row.status = "withdrawn"
    db.flush()
    return added


def _fmt(dt: datetime) -> str:
    return f"{dt.day} {dt:%b %Y %H:%M} UTC"


def recipients(db: Session, s: RegisterSystem, inc: Incident) -> list[User]:
    """The AI Incident Response Lead, the incident owner and the client's AI Compliance Officers."""
    ids = list(incident_leads(db, s.organization_id, s))
    if inc.owner_id:
        ids.append(inc.owner_id)
    ids += list(db.scalars(select(RoleAssignment.user_id).where(RoleAssignment.organization_id == s.organization_id, RoleAssignment.role == "caico", RoleAssignment.deleted_at.is_(None))))
    return [u for u in (db.get(User, i) for i in dict.fromkeys(ids)) if u is not None and u.deleted_at is None]


def _tell_new(db: Session, settings, s: RegisterSystem, inc: Incident, rows: list[IncidentDeadline]) -> None:
    if not rows:
        return
    lines = "; ".join(f"{d.recipient} by {_fmt(d.due_at)} ({d.citation}{'' if d.binding else ', good practice until it applies'})" for d in sorted(rows, key=lambda d: d.due_at))
    notify(db, recipients(db, s, inc), "incident_deadline", f"{inc.code} on {s.name}: {len(rows)} notice{'s' if len(rows) != 1 else ''} to make",
           f"{inc.description[:200]}. Notices: {lines}.", f"/register/{s.id}/tracing", settings=settings, email_template="notification")


# ---- writing
def next_code(db: Session, org_id: str) -> str:
    codes = db.scalars(select(Incident.code).where(Incident.organization_id == org_id))
    n = max((int(c[4:]) for c in codes if c and c[4:].isdigit()), default=0)
    return f"INC-{n + 1:03d}"


def create(db: Session, settings, actor, s: RegisterSystem, data: dict) -> Incident:
    vals = _clean(db, s, data, None)
    errs = []
    he = None
    if data.get("history_entry_id"):
        he = db.get(HistoryEntry, data["history_entry_id"])
        linked = db.scalar(select(Incident.id).where(Incident.history_entry_id == data["history_entry_id"], Incident.deleted_at.is_(None))) if he else None
        if he is None or he.register_system_id != s.id or he.deleted_at is not None or he.type != "incident" or linked:
            errs.append({"field": "history_entry_id", "message": "Choose an incident entry in this system's history log that is not yet linked to an incident."})
    trace_ids = data.get("trace_ids") or []
    if trace_ids:
        found = set(db.scalars(select(ActionTrace.id).where(ActionTrace.id.in_(trace_ids), ActionTrace.register_system_id == s.id)))
        if not isinstance(trace_ids, list) or set(trace_ids) - found:
            errs.append({"field": "trace_ids", "message": "One of the actions is not in this system's trace."})
    if errs:
        raise Invalid(errors=errs)
    inc = Incident(organization_id=s.organization_id, register_system_id=s.id, code=next_code(db, s.organization_id), status="open", created_by=actor.id,
                   trace_ids=list(trace_ids), **vals)
    if inc.containment and not inc.contained_on:
        inc.status = "contained"
    db.add(inc)
    db.flush()
    inc.history_entry_id = (he or _new_history_entry(db, s, inc, actor.id)).id
    added = sync_deadlines(db, s, inc)
    _sync_history(db, inc, actor.id)
    audit.record(db, actor_id=actor.id, action="incident.created", obj=inc, summary=f"{inc.code} on {s.name}: {inc.description[:120]}")
    _tell_new(db, settings, s, inc, added)
    return inc


def update(db: Session, settings, actor, s: RegisterSystem, inc: Incident, data: dict) -> Incident:
    if inc.status == "closed":
        raise Conflict("This incident is closed.")
    vals = _clean(db, s, {k: v for k, v in data.items() if k in EDITABLE}, inc)
    before = {k: _iso(getattr(inc, k)) if isinstance(getattr(inc, k), (date, datetime)) else getattr(inc, k) for k in vals}
    for k, v in vals.items():
        setattr(inc, k, v)
    if inc.status == "open" and (inc.containment or inc.contained_on):
        inc.status = "contained"
    inc.updated_by = actor.id
    db.flush()
    added = sync_deadlines(db, s, inc)
    _sync_history(db, inc, actor.id)
    after = {k: _iso(getattr(inc, k)) if isinstance(getattr(inc, k), (date, datetime)) else getattr(inc, k) for k in vals}
    audit.record(db, actor_id=actor.id, action="incident.updated", obj=inc, before=before, after=after, summary=f"{inc.code} updated")
    _tell_new(db, settings, s, inc, added)
    return inc


def close(db: Session, actor, s: RegisterSystem, inc: Incident, data: dict) -> Incident:
    if inc.status == "closed":
        raise Conflict("This incident is already closed.")
    errs: list = []
    closed_on = _date(data.get("closed_on"), "closed_on", errs) or (None if errs else utcnow().date())
    if closed_on and (closed_on > utcnow().date() or closed_on < inc.found_at.date()):
        errs.append({"field": "closed_on", "message": "Enter a date between when it was found and today."})
    if errs:
        raise Invalid(errors=errs)
    pending = [d for d in deadlines_of(db, inc) if d.status == "open" and d.binding]
    if pending:
        raise Conflict(f"Record each notice as made, or mark it not applicable, before closing: {', '.join(d.recipient for d in pending)}.")
    for k in ("fix", "containment", "cause"):
        if data.get(k):
            setattr(inc, k, str(data[k]).strip()[:4000])
    for d in deadlines_of(db, inc):
        if d.status == "open":  # good-practice notices not made by closing time
            d.status, d.na_reason = "not_applicable", "Incident closed before the duty applied; not made."
    inc.status, inc.closed_on, inc.updated_by = "closed", closed_on, actor.id
    db.flush()
    _sync_history(db, inc, actor.id)
    audit.record(db, actor_id=actor.id, action="incident.closed", obj=inc, summary=f"{inc.code} closed on {closed_on.isoformat()}")
    return inc


def act_on_deadline(db: Session, actor, s: RegisterSystem, d: IncidentDeadline, data: dict) -> Incident:
    inc = db.get(Incident, d.incident_id)
    if inc.status == "closed":
        raise Conflict("This incident is closed.")
    action = data.get("action")
    errs: list = []
    if action == "done":
        when = _dt(data.get("done_at"), "done_at", errs) or (None if errs else utcnow())
        if when and when > utcnow():
            errs.append({"field": "done_at", "message": "This is in the future."})
        if errs:
            raise Invalid(errors=errs)
        d.status, d.done_at, d.done_by, d.reference, d.na_reason = "done", when, actor.id, (data.get("reference") or "").strip()[:200] or None, None
        summary = f"{inc.code}: notice to {d.recipient} recorded as made on {when:%d %b %Y %H:%M}"
    elif action == "not_applicable":
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise Invalid(errors=[{"field": "reason", "message": "Say why this notice does not apply. The reason stays on record for the auditor."}])
        d.status, d.na_reason, d.done_at, d.done_by = "not_applicable", reason[:2000], None, actor.id
        summary = f"{inc.code}: notice to {d.recipient} marked not applicable: {reason[:120]}"
    elif action == "reopen":
        if d.status not in ("done", "not_applicable"):
            raise Conflict("Only a recorded or not-applicable notice can be reopened.")
        d.status, d.done_at, d.reference, d.na_reason = "open", None, None, None
        summary = f"{inc.code}: notice to {d.recipient} reopened"
    else:
        raise Invalid(errors=[{"field": "action", "message": "Choose done, not applicable or reopen."}])
    db.flush()
    _sync_history(db, inc, actor.id)
    audit.record(db, actor_id=actor.id, action=f"incident.notice_{action}", obj=inc, object_type="IncidentDeadline", object_id=d.id, summary=summary)
    return inc


def load(db: Session, s: RegisterSystem, incident_id: str) -> Incident:
    inc = db.get(Incident, incident_id)
    if inc is None or inc.deleted_at is not None or inc.register_system_id != s.id:
        raise NotFound()
    return inc


def load_deadline(db: Session, s: RegisterSystem, deadline_id: str) -> IncidentDeadline:
    d = db.get(IncidentDeadline, deadline_id)
    inc = db.get(Incident, d.incident_id) if d else None
    if d is None or inc is None or inc.register_system_id != s.id:
        raise NotFound()
    return d
