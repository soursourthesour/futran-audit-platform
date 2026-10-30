"""R7 action trace (spec §27.3, §27.7): manual entry, CSV and JSON import, the GuardRail feed and export.

Traces are evidence: they are only ever added, never edited or deleted. An import is all or nothing: every row is checked
first and nothing is saved while any row has an error. Rows whose event id the system already holds are skipped.
"""
import csv
import io
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid
from app.register.models import RegisterSystem
from app.tracing.models import DECISIONS, ActionTrace, TraceImport

DECISION_LABELS = {"allowed": "Allowed", "blocked": "Blocked", "escalated": "Escalated"}
DECISION_ALIASES = {"allow": "allowed", "allowed": "allowed", "permit": "allowed", "block": "blocked", "blocked": "blocked", "deny": "blocked", "denied": "blocked",
                    "escalate": "escalated", "escalated": "escalated", "handoff": "escalated"}
FIELD_ALIASES = {
    "at": ("time", "at", "timestamp", "when", "date and time"),
    "session_id": ("session", "session id", "session_id"),
    "action": ("action",),
    "tool": ("tool",),
    "data_touched": ("data touched", "data_touched", "data"),
    "decision": ("decision",),
    "policy_ref": ("policy", "policy_ref", "policy ref"),
    "approver": ("approver", "approver or note", "note"),
    "agent_identity": ("agent", "agent identity", "agent_identity"),
    "external_id": ("event id", "event_id", "id"),
}
LIMITS = {"session_id": 80, "action": 300, "tool": 120, "data_touched": 300, "policy_ref": 120, "approver": 200, "agent_identity": 160, "external_id": 120}
PERIODS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "all": None}
EXPORT_COLUMNS = ["Time", "Session", "Action", "Tool", "Data touched", "Decision", "Policy", "Approver or note", "Agent", "Source", "Event id"]


def _norm_key(k: str) -> str:
    return " ".join(str(k).strip().lower().replace("_", " ").split())


def _field_for(key: str) -> str | None:
    k = _norm_key(key)
    for field, names in FIELD_ALIASES.items():
        if k in {_norm_key(n) for n in names}:
            return field
    return None


def _parse_time(v) -> datetime | None:
    if v in (None, ""):
        return None
    try:
        out = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return out.astimezone(timezone.utc).replace(tzinfo=None) if out.tzinfo else out


def clean_event(raw: dict, label: str, errs: list) -> dict:
    """One event from any source, as ActionTrace fields. `label` prefixes error fields ("row 5: ", or "" for a form)."""
    ev: dict = {}
    for k, v in raw.items():
        f = _field_for(k) if k not in FIELD_ALIASES else k
        if f and f not in ev:
            ev[f] = v
    out: dict = {}
    at = _parse_time(ev.get("at"))
    if at is None:
        errs.append({"field": f"{label}time" if label else "at", "message": "Enter the date and time of the action (for example 2026-10-29T14:02:11)."})
    elif at > utcnow() + timedelta(minutes=5):
        errs.append({"field": f"{label}time" if label else "at", "message": "This is in the future."})
    out["at"] = at
    action = str(ev.get("action") or "").strip()
    if not action:
        errs.append({"field": f"{label}action" if label else "action", "message": "Say what the agent did or tried to do."})
    out["action"] = action
    dec = DECISION_ALIASES.get(str(ev.get("decision") or "").strip().lower())
    if dec not in DECISIONS:
        errs.append({"field": f"{label}decision" if label else "decision", "message": "The decision must be allowed, blocked or escalated."})
    out["decision"] = dec
    for k, n in LIMITS.items():
        v = ev.get(k)
        out[k] = (str(v).strip()[:n] or None) if v not in (None, "") else None
    return out


def _add(db: Session, s: RegisterSystem, ev: dict, source: str, actor_id: str | None, import_id: str | None) -> ActionTrace:
    t = ActionTrace(organization_id=s.organization_id, register_system_id=s.id, source=source, import_id=import_id, recorded_by=actor_id, recorded_at=utcnow(), **ev)
    db.add(t)
    return t


def add_manual(db: Session, actor, s: RegisterSystem, data: dict) -> ActionTrace:
    errs: list = []
    ev = clean_event({k: v for k, v in data.items() if k in FIELD_ALIASES}, "", errs)
    if errs:
        raise Invalid(errors=errs)
    ev["external_id"] = None
    t = _add(db, s, ev, "manual", actor.id, None)
    db.flush()
    audit.record(db, actor_id=actor.id, action="trace.added", obj=t, summary=f"Action added by hand on {s.name}: {t.action[:100]}")
    return t


def parse_file(filename: str, data: bytes) -> tuple[str, list[dict]]:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise Invalid(errors=[{"field": "file", "message": "Save the CSV as UTF-8 and try again."}]) from exc
        return "csv", list(csv.DictReader(io.StringIO(text)))
    if name.endswith(".json"):
        try:
            body = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Invalid(errors=[{"field": "file", "message": "The file is not valid JSON."}]) from exc
        rows = body.get("events") if isinstance(body, dict) else body
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise Invalid(errors=[{"field": "file", "message": "Expected a list of events, or an object with an \"events\" list."}])
        return "json", rows
    raise Invalid(errors=[{"field": "file", "message": "Choose a .csv or .json file."}])


def _held(db: Session, s: RegisterSystem, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    return set(db.scalars(select(ActionTrace.external_id).where(ActionTrace.register_system_id == s.id, ActionTrace.external_id.in_(ids))))


def ingest(db: Session, actor_id: str | None, s: RegisterSystem, source: str, rows: list[dict], filename: str | None, *, first_row: int = 2) -> TraceImport:
    errs: list = []
    events = []
    for i, raw in enumerate(rows):
        label = f"row {i + first_row}: " if source == "csv" else f"event {i + 1}: "
        events.append(clean_event(raw, label, errs))
    if not events:
        errs.append({"field": "file", "message": "The file has no actions."})
    if errs:
        raise Invalid("Nothing was imported. Correct these rows and try again.", errors=errs[:50])
    held = _held(db, s, [e["external_id"] for e in events if e["external_id"]])
    imp = TraceImport(organization_id=s.organization_id, register_system_id=s.id, source=source, filename=(filename or None) and filename[:255], imported_by=actor_id, at=utcnow())
    db.add(imp)
    db.flush()
    seen: set[str] = set()
    for ev in events:
        eid = ev["external_id"]
        if eid and (eid in held or eid in seen):
            imp.skipped += 1
            continue
        if eid:
            seen.add(eid)
        _add(db, s, ev, source, actor_id, imp.id)
        imp.added += 1
    db.flush()
    audit.record(db, actor_id=actor_id, actor_name=None if actor_id else "GuardRail feed", action="trace.imported", obj=imp,
                 summary=f"{imp.added} actions added to {s.name} from {filename or source}; {imp.skipped} already held")
    return imp


def import_file(db: Session, actor, s: RegisterSystem, filename: str, data: bytes) -> TraceImport:
    source, rows = parse_file(filename, data)
    return ingest(db, actor.id, s, source, rows, filename)


def guardrail_sync(db: Session, settings, actor, s: RegisterSystem) -> TraceImport:
    from app.tracing.guardrail import adapter

    if not s.guardrail_policy_ref:
        raise Invalid("This system has no GuardRail policy. Add the policy name on the Details tab first.", errors=[{"field": "guardrail_policy_ref", "message": "No GuardRail policy."}])
    feed = adapter(settings)
    if feed is None:
        raise Conflict("GuardRail is not connected for this platform. Import the agent's logs as CSV or JSON instead.")
    last = db.scalar(select(func.max(ActionTrace.at)).where(ActionTrace.register_system_id == s.id, ActionTrace.source == "guardrail"))
    rows = feed.events(s.guardrail_policy_ref, f"{s.reference.lower()}-agent", last, utcnow())
    return ingest(db, actor.id, s, "guardrail", rows, f"GuardRail policy {s.guardrail_policy_ref}")


# ---- reading
def query(db: Session, s: RegisterSystem, *, decision: str | None = None, period: str = "all", limit: int = 500) -> list[ActionTrace]:
    if decision not in (None, "", *DECISIONS):
        raise Invalid(errors=[{"field": "decision", "message": "Choose allowed, blocked or escalated."}])
    if period not in PERIODS:
        raise Invalid(errors=[{"field": "period", "message": "Choose 24h, 7d, 30d or all."}])
    stmt = select(ActionTrace).where(ActionTrace.register_system_id == s.id)
    if decision:
        stmt = stmt.where(ActionTrace.decision == decision)
    if PERIODS[period] is not None:
        stmt = stmt.where(ActionTrace.at >= utcnow() - PERIODS[period])
    return list(db.scalars(stmt.order_by(ActionTrace.at.desc(), ActionTrace.recorded_at.desc()).limit(limit)))


def trace_out(t: ActionTrace) -> dict:
    return {"id": t.id, "at": t.at.isoformat(), "session_id": t.session_id, "action": t.action, "tool": t.tool, "data_touched": t.data_touched, "decision": t.decision,
            "decision_label": DECISION_LABELS[t.decision], "policy_ref": t.policy_ref, "approver": t.approver, "agent_identity": t.agent_identity, "source": t.source,
            "external_id": t.external_id}


def kpis(db: Session, s: RegisterSystem) -> dict:
    since = utcnow() - timedelta(hours=24)
    rows = list(db.execute(select(ActionTrace.decision, func.count()).where(ActionTrace.register_system_id == s.id, ActionTrace.at >= since).group_by(ActionTrace.decision)))
    by = {d: n for d, n in rows}
    return {"actions_24h": sum(by.values()), "blocked_24h": by.get("blocked", 0), "escalated_24h": by.get("escalated", 0),
            "total": db.scalar(select(func.count()).select_from(ActionTrace).where(ActionTrace.register_system_id == s.id)) or 0}


def csv_text(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else ("'" + v if isinstance(v, str) and v[:1] in "=+-@" else v) for v in r])  # no spreadsheet formulas
    return buf.getvalue()


def export_traces(db: Session, s: RegisterSystem) -> str:
    rows = query(db, s, limit=100_000)
    return csv_text(EXPORT_COLUMNS, [[t.at.isoformat(), t.session_id, t.action, t.tool, t.data_touched, DECISION_LABELS[t.decision], t.policy_ref, t.approver, t.agent_identity,
                                      t.source, t.external_id] for t in rows])
