"""Agent Assure records and AgentWarden licence sync (Release 2 B9, screen G-09).

- A Futran auditor records each release of an agent: gold evaluation set (version, size, owner), the 15-point pre-deploy
  check (items from Futran's editable list, blank until FATF supplies them), red-team scenarios, the outcome and the
  signed assurance letter.
- The register field `agentassure_status` is computed from the latest record (v0.6.1 §24.5): passed, conditional,
  failed, or recertification_due once a reassessment trigger (model or version change, vendor change, failed monitor
  check: v0.6.1 F8) is raised on the agent after that record. A new record clears it. Once an agent has a record, the
  field is no longer set by hand.
- AgentWarden licence sync: a CSV from AgentWarden (until its API exists) of protected agents, autonomy, monthly
  actions, approver seats and deployment. Each sync is a set of `WardenLicenceSnapshot`s and, when the commercial
  package (Release 2 R5, G-01) is installed, today's usage records for AW-02, AW-03 and AW-05.
- Independence rule I-2 (Futran also audits the agent) is enforced by the proposals workstream; this screen notes it.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assurance.models import CHECK_POSITIONS, CHECK_RESULTS, DEPLOYMENTS, OUTCOMES, SEVERITIES, AssuranceCheckItem, AssuranceRun, WardenLicenceSnapshot
from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.core.ids import new_id
from app.register.models import RegisterSystem
from app.tenancy.models import User

STATUS_FOR = {"pass": "passed", "conditional": "conditional", "fail": "failed"}
STATUS_LABELS = {"passed": "Agent Assure: passed", "conditional": "Agent Assure: conditional pass", "failed": "Agent Assure: failed",
                 "recertification_due": "Agent Assure: re-certification due"}
OUTCOME_LABELS = {"pass": "Pass", "conditional": "Conditional pass", "fail": "Fail"}
RECERT_TRIGGERS = ("version_change", "vendor_change", "failed_monitor_check")
CHECKLIST_NOTE = ("The 15 points come from the Agent Assure methodology. FATF supplies them; until then each point is blank and results are "
                  "recorded against its number.")
I2_NOTE = "Futran also audits this client. Agent Assure must be delivered by a separate team (rule I-2)."


# ---------------------------------------------------------------- the 15-point list
def checklist(db: Session) -> list[dict]:
    rows = {r.position: r for r in db.scalars(select(AssuranceCheckItem))}
    return [{"position": p, "text": rows[p].text if p in rows else None} for p in range(1, CHECK_POSITIONS + 1)]


def save_checklist(db: Session, user: User, items: list[dict]) -> list[dict]:
    errors = []
    for i, it in enumerate(items or []):
        p = it.get("position") if isinstance(it, dict) else None
        if not isinstance(p, int) or not 1 <= p <= CHECK_POSITIONS:
            errors.append({"field": f"items.{i}.position", "message": f"Positions run from 1 to {CHECK_POSITIONS}."})
    if errors:
        raise Invalid(errors=errors)
    before = {i["position"]: i["text"] for i in checklist(db)}
    for it in items:
        text = " ".join(str(it.get("text") or "").split())[:400] or None
        row = db.scalar(select(AssuranceCheckItem).where(AssuranceCheckItem.position == it["position"]))
        if row is None:
            row = AssuranceCheckItem(position=it["position"])
            db.add(row)
        row.text, row.updated_by = text, user.id
    db.flush()
    after = checklist(db)
    changed = {i["position"]: i["text"] for i in after if before.get(i["position"]) != i["text"]}
    if changed:
        audit.record(db, actor_id=user.id, action="assurance.checklist_edited", object_type="AssuranceCheckItem", object_id=None, organization_id=user.organization_id,
                     before={str(k): before[k] for k in changed}, after={str(k): v for k, v in changed.items()},
                     summary=f"Edited {len(changed)} point{'s' if len(changed) != 1 else ''} of the Agent Assure 15-point pre-deploy check")
    return after


# ---------------------------------------------------------------- runs and status
def runs(db: Session, system_id: str) -> list[AssuranceRun]:
    return list(db.scalars(select(AssuranceRun).where(AssuranceRun.register_system_id == system_id, AssuranceRun.deleted_at.is_(None))
                           .order_by(AssuranceRun.recorded_at.desc(), AssuranceRun.created_at.desc())))


def latest_run(db: Session, system_id: str) -> AssuranceRun | None:
    r = runs(db, system_id)
    return r[0] if r else None


def has_runs(db: Session, system_id: str) -> bool:
    return db.scalar(select(func.count(AssuranceRun.id)).where(AssuranceRun.register_system_id == system_id, AssuranceRun.deleted_at.is_(None))) > 0


def computed_status(db: Session, system_id: str) -> str | None:
    """The register's `agentassure_status` from the latest Agent Assure record; None when the agent has none."""
    r = latest_run(db, system_id)
    if r is None:
        return None
    return "recertification_due" if r.next_due_trigger else STATUS_FOR[r.outcome]


def refresh_status(db: Session, s: RegisterSystem, actor: User | None, reason: str) -> str | None:
    st = computed_status(db, s.id)
    if st is not None and st != s.agentassure_status:
        from app.register.service import log_change

        log_change(db, actor, s, "agentassure_status", s.agentassure_status, st, reason)
        s.agentassure_status = st
        db.flush()
    return st


def _text(v, n: int) -> str | None:
    return " ".join(str(v).split())[:n] or None if v is not None else None


def clean_run(db: Session, data: dict) -> dict:
    errs: list[dict] = []
    out: dict = {}
    out["release_ref"] = _text(data.get("release_ref"), 60)
    if not out["release_ref"]:
        errs.append({"field": "release_ref", "message": "Enter the release, for example v1.2."})
    out["model_ref"] = _text(data.get("model_ref"), 200)
    out["eval_set_version"] = _text(data.get("eval_set_version"), 40)
    out["eval_set_owner"] = _text(data.get("eval_set_owner"), 160)
    size = data.get("eval_set_size")
    if size in (None, ""):
        out["eval_set_size"] = None
    elif isinstance(size, int) and not isinstance(size, bool) and size >= 0:
        out["eval_set_size"] = size
    else:
        errs.append({"field": "eval_set_size", "message": "Enter the number of cases in the gold evaluation set."})
    if data.get("outcome") not in OUTCOMES:
        errs.append({"field": "outcome", "message": "Choose pass, conditional pass or fail."})
    out["outcome"] = data.get("outcome")
    items = {i["position"]: i["text"] for i in checklist(db)}
    given: dict[int, dict] = {}
    for c in data.get("checks") or []:
        p = c.get("position") if isinstance(c, dict) else None
        if not isinstance(p, int) or not 1 <= p <= CHECK_POSITIONS or c.get("result", "not_run") not in CHECK_RESULTS:
            errs.append({"field": "checks", "message": f"Each check needs a point from 1 to {CHECK_POSITIONS} and a result: pass, conditional, fail or not run."})
            break
        given[p] = {"position": p, "item": items.get(p), "result": c.get("result", "not_run"), "note": _text(c.get("note"), 500), "due": _text(c.get("due"), 60)}
    out["checks"] = [given.get(p, {"position": p, "item": items.get(p), "result": "not_run", "note": None, "due": None}) for p in range(1, CHECK_POSITIONS + 1)]
    red = []
    for r in data.get("redteam") or []:
        if not isinstance(r, dict) or not _text(r.get("scenario"), 300) or (r.get("severity") and r.get("severity") not in SEVERITIES):
            errs.append({"field": "redteam", "message": "Each red-team result needs a scenario and, if given, a severity of low, medium, high or critical."})
            break
        red.append({"scenario": _text(r.get("scenario"), 300), "outcome": _text(r.get("outcome"), 500), "severity": r.get("severity") or None})
    out["redteam"] = red
    if errs:
        raise Invalid(errors=errs)
    return out


def record_run(db: Session, user: User, s: RegisterSystem, data: dict) -> AssuranceRun:
    if s.type != "agent":
        raise Conflict("Agent Assure records are kept for agents. Change the system's type to Agent first.")
    v = clean_run(db, data)
    if not v["model_ref"]:
        v["model_ref"] = " ".join(x for x in (s.model_name, s.model_version) if x) or None
    r = AssuranceRun(organization_id=s.organization_id, register_system_id=s.id, recorded_by=user.id, recorded_at=utcnow(), created_by=user.id, **v)
    db.add(r)
    db.flush()
    audit.record(db, actor_id=user.id, action="assurance.recorded", obj=r, organization_id=s.organization_id,
                 summary=f"Agent Assure record for {s.reference} {s.name} release {r.release_ref}: {OUTCOME_LABELS[r.outcome]}")
    refresh_status(db, s, user, f"Agent Assure record for release {r.release_ref}")
    return r


def attach_letter(db: Session, settings, user: User, s: RegisterSystem, run_id: str, *, filename: str, data: bytes, signed_by: str | None, signed_on: str | None) -> AssuranceRun:
    from app.files.service import upload

    r = db.get(AssuranceRun, run_id)
    if r is None or r.register_system_id != s.id or r.deleted_at is not None:
        raise NotFound()
    errs = []
    by = _text(signed_by, 160)
    if not by:
        errs.append({"field": "signed_by", "message": "Enter who signed the assurance letter."})
    try:
        on = date.fromisoformat(signed_on or "")
    except ValueError:
        on = None
        errs.append({"field": "signed_on", "message": "Enter the date the letter was signed."})
    if errs:
        raise Invalid(errors=errs)
    f = upload(db, settings, user, data=data, filename=filename or "assurance-letter.pdf", content_type=None, organization_id=s.organization_id,
               linked_type="assurance_letter", linked_id=r.id)
    r.letter_file_id, r.signed_by, r.signed_on = f.id, by, on
    audit.record(db, actor_id=user.id, action="assurance.letter", obj=r, organization_id=s.organization_id,
                 summary=f"Assurance letter for {s.reference} release {r.release_ref} signed by {by} on {on:%d %b %Y}")
    db.flush()
    return r


def on_reassessment_trigger(db: Session, s: RegisterSystem, trigger, detail: str | None = None) -> None:
    """Called by `app.impact.triggers.raise_trigger` for every model, version or vendor change and failed monitor check,
    also when an open trigger of that type is reused: the agent's latest Agent Assure record then asks for a new run
    (re-certification). Idempotent: a record already waiting for re-certification is left as it is."""
    if s.type != "agent" or trigger.type not in RECERT_TRIGGERS:
        return
    r = latest_run(db, s.id)
    if r is None or r.next_due_trigger:
        return
    from app.impact.triggers import TYPE_LABELS

    r.next_due_trigger = trigger.id
    why = detail or trigger.detail
    r.next_due_reason = f"{TYPE_LABELS.get(trigger.type, trigger.type)}{f': {why}' if why else ''}"[:2000]
    db.flush()
    refresh_status(db, s, None, f"Re-certification due: {r.next_due_reason}")


# ---------------------------------------------------------------- AgentWarden licence sync
WARDEN_COLUMNS = {
    "agent": ("agent", "agent name", "agent id", "reference", "system", "ai system"),
    "autonomy": ("autonomy", "autonomy level"),
    "actions_month": ("actions this month", "monthly actions", "actions month", "actions_month", "actions"),
    "actions_included": ("actions included", "included actions", "actions_included"),
    "approvers": ("approver seats", "approvers", "approver_seats"),
    "deployment": ("deployment", "deployment option"),
}


def sync_warden(db: Session, user: User, org_id: str, filename: str | None, data: bytes) -> dict:
    """Read an AgentWarden licence CSV for one client. Agents are matched by register reference (AIS-001) or name."""
    from app.connectors.manual_import import read_table

    headers, rows = read_table(data, filename or "agentwarden.csv")
    norm = {" ".join(h.replace("_", " ").split()).lower(): i for i, h in enumerate(headers)}
    idx = {k: next((norm[a.replace("_", " ")] for a in names if a.replace("_", " ") in norm), None) for k, names in WARDEN_COLUMNS.items()}
    if idx["agent"] is None:
        raise Invalid(errors=[{"field": "file", "message": "The file needs an Agent column with the register reference (AIS-001) or the agent's name."}])
    agents = list(db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None), RegisterSystem.type == "agent")))
    by_ref = {a.reference.lower(): a for a in agents}
    by_name = {a.name.casefold(): a for a in agents}
    sync_id, now, sha = new_id(), utcnow(), hashlib.sha256(data).hexdigest()

    def cell(row, k):
        i = idx[k]
        return row[i].strip() if i is not None and i < len(row) else ""

    def num(v):
        try:
            return int(float(v.replace(",", ""))) if v else None
        except ValueError:
            return None

    matched, unmatched = [], []
    for row in rows:
        label = cell(row, "agent")
        if not label:
            continue
        a = by_ref.get(label.lower()) or by_name.get(label.casefold())
        if a is None:
            unmatched.append(label)
            continue
        dep = cell(row, "deployment").lower()
        snap = WardenLicenceSnapshot(organization_id=org_id, register_system_id=a.id, sync_id=sync_id, agent_label=label[:160], autonomy=cell(row, "autonomy")[:30] or None,
                                     actions_month=num(cell(row, "actions_month")) or 0, actions_included=num(cell(row, "actions_included")),
                                     approvers=num(cell(row, "approvers")) or 0, deployment=dep if dep in DEPLOYMENTS else None, synced_at=now, source_sha256=sha,
                                     created_by=user.id)
        db.add(snap)
        matched.append(snap)
    db.flush()
    usage = _feed_usage(db, org_id, matched)
    audit.record(db, actor_id=user.id, action="agentwarden.synced", object_type="WardenLicenceSnapshot", object_id=sync_id, organization_id=org_id,
                 summary=f"AgentWarden licence sync from {filename or 'CSV'}: {len(matched)} agent{'s' if len(matched) != 1 else ''} matched"
                         f"{f', not in the register: {', '.join(unmatched[:10])}' if unmatched else ''}")
    return {"sync_id": sync_id, "matched": len(matched), "unmatched": unmatched, "usage": usage, "synced_at": now.isoformat()}


def latest_snapshots(db: Session, org_id: str) -> list[WardenLicenceSnapshot]:
    """The newest snapshot of each of the client's agents: a sync replaces the agents in its file and leaves the others."""
    rows = db.scalars(select(WardenLicenceSnapshot).where(WardenLicenceSnapshot.organization_id == org_id, WardenLicenceSnapshot.deleted_at.is_(None))
                      .order_by(WardenLicenceSnapshot.synced_at.desc(), WardenLicenceSnapshot.created_at.desc()))
    out: dict[str, WardenLicenceSnapshot] = {}
    for r in rows:
        s = db.get(RegisterSystem, r.register_system_id)
        if s is not None and s.deleted_at is None and r.register_system_id not in out:
            out[r.register_system_id] = r
    return list(out.values())


def _feed_usage(db: Session, org_id: str, _snaps: list[WardenLicenceSnapshot]) -> dict | None:
    """G-01 usage for AW-02 (agents protected), AW-03 (agent actions a month) and AW-05 (approver seats), when the
    commercial package is installed, from the latest snapshot of every agent (not only those in this file). Approver
    seats are summed across agents (AgentWarden reports them per agent)."""
    try:
        from app.commercial.models import UsageRecord
    except ImportError:
        return None
    snaps = latest_snapshots(db, org_id)
    on = today()
    values = {"agents_protected": float(len({s.register_system_id for s in snaps})), "agent_actions_month": float(sum(s.actions_month for s in snaps)),
              "approver_seats": float(sum(s.approvers for s in snaps))}
    for key, value in values.items():
        rec = db.scalar(select(UsageRecord).where(UsageRecord.organization_id == org_id, UsageRecord.key == key, UsageRecord.measured_on == on))
        if rec is None:
            db.add(UsageRecord(organization_id=org_id, key=key, measured_on=on, value=value))
        else:
            rec.value = value
    db.flush()
    return values


def latest_warden(db: Session, system_id: str) -> WardenLicenceSnapshot | None:
    return db.scalar(select(WardenLicenceSnapshot).where(WardenLicenceSnapshot.register_system_id == system_id, WardenLicenceSnapshot.deleted_at.is_(None))
                     .order_by(WardenLicenceSnapshot.synced_at.desc()).limit(1))


# ---------------------------------------------------------------- read model
def _summary(checks: list[dict]) -> dict:
    out = {k: 0 for k in CHECK_RESULTS}
    for c in checks or []:
        out[c.get("result", "not_run")] = out.get(c.get("result", "not_run"), 0) + 1
    return out


def run_out(db: Session, r: AssuranceRun) -> dict:
    from app.files.models import FileObject

    f = db.get(FileObject, r.letter_file_id) if r.letter_file_id else None
    by = db.get(User, r.recorded_by) if r.recorded_by else None
    return {"id": r.id, "release_ref": r.release_ref, "model_ref": r.model_ref, "eval_set_version": r.eval_set_version, "eval_set_size": r.eval_set_size,
            "eval_set_owner": r.eval_set_owner, "checks": r.checks or [], "checks_summary": _summary(r.checks), "redteam": r.redteam or [], "outcome": r.outcome,
            "outcome_label": OUTCOME_LABELS[r.outcome], "letter": {"id": f.id, "filename": f.filename} if f else None, "signed_by": r.signed_by,
            "signed_on": r.signed_on.isoformat() if r.signed_on else None, "recertification_due": bool(r.next_due_trigger), "recertification_reason": r.next_due_reason,
            "recorded_by": by.name if by else None, "recorded_at": r.recorded_at.isoformat()}


def page(db: Session, s: RegisterSystem, *, can_record: bool, can_sync: bool, can_edit_checklist: bool) -> dict:
    from app.sales.service import is_current_audit_client

    rs = runs(db, s.id)
    latest = rs[0] if rs else None
    status = computed_status(db, s.id)
    open_conditions = []
    if latest is not None:
        open_conditions = [{"item": c.get("item") or f"Check point {c['position']}", "position": c["position"], "result": c["result"], "condition": c.get("note"), "due": c.get("due")}
                           for c in latest.checks or [] if c.get("result") in ("conditional", "fail")]
        open_conditions += [{"item": f"Red team · {r['scenario']}", "position": None, "result": r.get("severity") or "finding", "condition": r.get("outcome"), "due": None}
                            for r in latest.redteam or [] if r.get("severity") in ("medium", "high", "critical")]
    w = latest_warden(db, s.id)
    return {
        "system": {"id": s.id, "reference": s.reference, "name": s.name, "type": s.type, "stage": s.stage, "autonomy": s.autonomy, "guardrail_policy_ref": s.guardrail_policy_ref,
                   "model": " ".join(x for x in (s.model_name, s.model_version) if x) or None, "organization_id": s.organization_id},
        "is_agent": s.type == "agent", "status": status, "status_label": STATUS_LABELS.get(status or "", "No Agent Assure record yet"),
        "runs": [run_out(db, r) for r in rs], "open_conditions": open_conditions,
        "recertification": {"due": bool(latest and latest.next_due_trigger), "reason": latest.next_due_reason if latest else None,
                            "rule": "A new Agent Assure run is needed when the model or version changes, the vendor or provider changes, or a monitoring check fails."},
        "checklist": checklist(db), "checklist_note": CHECKLIST_NOTE,
        "warden": {"agent_label": w.agent_label, "autonomy": w.autonomy, "actions_month": w.actions_month, "actions_included": w.actions_included, "approvers": w.approvers,
                   "deployment": w.deployment, "synced_at": w.synced_at.isoformat()} if w else None,
        "independence_note": I2_NOTE if is_current_audit_client(db, s.organization_id) else None,
        "can_record": can_record, "can_sync": can_sync, "can_edit_checklist": can_edit_checklist,
    }
