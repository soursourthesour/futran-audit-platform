"""System history log, first-entry history questions, bias tests and the no-incident statement (spec §24.5, §27.2)."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.register import service as svc
from app.register.models import HISTORY_TYPES, TESTER_TYPES, BiasTest, HistoryEntry, NoIncidentStatement, RegisterSystem
from app.tenancy.models import User

TYPE_LABELS = {"incident": "Incident", "bias_test": "Bias test", "deployment_test": "Deployment test", "impact_assessment": "Impact assessment",
               "notice_consent": "Notice or consent", "model_change": "Model change", "approval": "Approval", "training": "Training", "vendor_audit": "Vendor audit",
               "monitoring_review": "Monitoring review"}
SEVERITIES = {"low": "Low", "medium": "Medium", "high": "High", "serious": "Serious (EU AI Act Art. 73)"}
BIAS_RESULTS = {"passed": "Passed", "flagged": "Flagged", "inconclusive": "Inconclusive"}
DEPLOYMENT_KINDS = {"user_acceptance": "User acceptance", "agentassure": "AgentAssure", "red_team": "Red team", "security": "Security"}
TESTER_LABELS = {"independent": "Independent auditor", "internal": "Internal team", "vendor": "Vendor (their own audit)"}

# per type: field -> kind (text | int | bool | date | percent | choice:<dict name>)
DETAIL_FIELDS: dict[str, dict[str, str]] = {
    "incident": {"people_affected": "int", "cause": "text", "containment": "text", "fix": "text", "closed_on": "date", "reportable": "bool", "law": "text",
                 "deadline": "date", "reported_on": "date", "provider_told": "bool", "provider_told_on": "date"},
    "bias_test": {"tester_type": "tester", "tester_name": "text", "method": "text", "groups_tested": "text", "result": "bias_result", "unknown_share": "percent", "next_due": "date"},
    "deployment_test": {"kind": "deployment_kind", "sample_size": "int", "result": "text"},
    "impact_assessment": {"law": "text", "outcome": "text", "next_due": "date"},
    "notice_consent": {"audience": "text", "channel": "text", "version": "text"},
    "model_change": {"old_version": "text", "new_version": "text", "reassessment_needed": "bool"},
    "approval": {"approver": "text", "scope": "text"},
    "training": {}, "vendor_audit": {}, "monitoring_review": {},
}
QUESTIONS = ("incidents", "bias_tests", "deployment_tests", "approvals", "notices")
ANSWERS = ("yes", "no", "not_applicable")


def _entries(db: Session, s: RegisterSystem) -> list[HistoryEntry]:
    return list(db.scalars(select(HistoryEntry).where(HistoryEntry.register_system_id == s.id, HistoryEntry.deleted_at.is_(None)).order_by(HistoryEntry.occurred_on.desc(), HistoryEntry.recorded_at.desc())))


def _details(kind: str, raw: dict, errs: list) -> dict:
    out: dict = {}
    spec = DETAIL_FIELDS[kind]
    for k, t in spec.items():
        if k not in raw or raw[k] in (None, ""):
            continue
        v = raw[k]
        f = f"details.{k}"
        if t == "text":
            out[k] = str(v).strip()[:2000]
        elif t in ("int", "percent"):
            try:
                n = float(v) if t == "percent" else int(v)
                if n < 0 or (t == "percent" and n > 100):
                    raise ValueError
                out[k] = n
            except (TypeError, ValueError):
                errs.append({"field": f, "message": "Enter a number between 0 and 100." if t == "percent" else "Enter a whole number."})
        elif t == "bool":
            if not isinstance(v, bool):
                errs.append({"field": f, "message": "Answer yes or no."})
            else:
                out[k] = v
        elif t == "date":
            d = svc._date(v, f, errs)
            if d:
                out[k] = d.isoformat()
        elif t == "tester":
            if v not in TESTER_TYPES:
                errs.append({"field": f, "message": "Choose who ran the test."})
            else:
                out[k] = v
        elif t == "bias_result":
            if v not in BIAS_RESULTS:
                errs.append({"field": f, "message": "Choose the result."})
            else:
                out[k] = v
        elif t == "deployment_kind":
            if v not in DEPLOYMENT_KINDS:
                errs.append({"field": f, "message": "Choose the kind of test."})
            else:
                out[k] = v
    return out


def clean_entry(db: Session, s: RegisterSystem, data: dict, current: HistoryEntry | None = None) -> dict:
    errs: list[dict] = []
    kind = data.get("type", current.type if current else None)
    if kind not in HISTORY_TYPES:
        raise Invalid(errors=[{"field": "type", "message": "Choose the type of entry."}])
    out: dict = {"type": kind}
    if "occurred_on" in data or current is None:
        d = svc._date(data.get("occurred_on"), "occurred_on", errs)
        if d is None and not any(e["field"] == "occurred_on" for e in errs):
            errs.append({"field": "occurred_on", "message": "Enter the date."})
        elif d and d > utcnow().date():
            errs.append({"field": "occurred_on", "message": "The date cannot be in the future."})
        out["occurred_on"] = d
    if "summary" in data or current is None:
        summary = str(data.get("summary") or "").strip()
        if not summary:
            errs.append({"field": "summary", "message": "Say what happened." if kind == "incident" else "Describe the entry."})
        out["summary"] = summary[:4000]
    if "result" in data:
        out["result"] = str(data.get("result") or "").strip()[:4000] or None
    sev = data.get("severity", current.severity if current else None)
    if kind == "incident":
        if sev not in SEVERITIES:
            errs.append({"field": "severity", "message": "Choose the severity."})
        out["severity"] = sev
    if "details" in data or current is None:
        raw = data.get("details") if isinstance(data.get("details"), dict) else {}
        merged = (dict(current.details or {}) if current else {}) | raw
        det = _details(kind, merged, errs)
        if kind == "incident" and det.get("reportable"):
            if not det.get("law"):
                errs.append({"field": "details.law", "message": "Name the law that makes it reportable."})
            if not det.get("deadline"):
                errs.append({"field": "details.deadline", "message": "Enter the reporting deadline."})
        if kind == "bias_test":
            if not det.get("tester_type") and "details.tester_type" not in {e["field"] for e in errs}:
                errs.append({"field": "details.tester_type", "message": "Choose who ran the test."})
            if not det.get("result") and "details.result" not in {e["field"] for e in errs}:
                errs.append({"field": "details.result", "message": "Choose the result."})
        out["details"] = det
    for f in ("requirement_ids", "evidence_ids"):
        if f in data:
            v = data.get(f) or []
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errs.append({"field": f, "message": "Choose from the list."})
            else:
                out[f] = list(dict.fromkeys(v))
    if "evidence_ids" in out:
        for fid in out["evidence_ids"]:
            svc._file(db, s.organization_id, fid, "evidence_ids", errs)
    if errs:
        raise Invalid(errors=errs)
    return out


def add_entry(db: Session, actor: User, s: RegisterSystem, data: dict) -> HistoryEntry:
    v = clean_entry(db, s, data)
    if v["type"] == "bias_test":
        det = v["details"]
        return record_bias_test(db, actor, s, {"tested_on": v["occurred_on"], "summary": v["summary"], **det, "result_text": v.get("result"),
                                               "evidence_ids": v.get("evidence_ids", []), "requirement_ids": v.get("requirement_ids", [])})[1]
    e = HistoryEntry(organization_id=s.organization_id, register_system_id=s.id, recorded_by=actor.id, recorded_at=utcnow(), created_by=actor.id,
                     requirement_ids=v.pop("requirement_ids", []), evidence_ids=v.pop("evidence_ids", []), **v)
    db.add(e)
    db.flush()
    svc.log_change(db, actor, s, "history", None, f"Added {TYPE_LABELS[e.type].lower()}: {e.summary[:200]}", None, entity="HistoryEntry", entity_id=e.id, raw=True)
    audit.record(db, actor_id=actor.id, action="register.history_add", obj=s, after={"type": e.type, "occurred_on": e.occurred_on.isoformat(), "summary": e.summary[:300]},
                 summary=f"Added a {TYPE_LABELS[e.type].lower()} to the history of {s.reference} {s.name}")
    return e


def update_entry(db: Session, actor: User, s: RegisterSystem, e: HistoryEntry, data: dict) -> HistoryEntry:
    reason = " ".join(str(data.get("reason") or "").split()) or None
    v = clean_entry(db, s, {k: val for k, val in data.items() if k not in ("type", "reason")}, current=e)
    v.pop("type")
    before = {k: getattr(e, k) for k in v}
    for k, val in v.items():
        setattr(e, k, val)
    e.updated_by = actor.id
    changed = [k for k in v if before[k] != getattr(e, k)]
    if changed:
        svc.log_change(db, actor, s, "history", f"{TYPE_LABELS[e.type]} of {e.occurred_on.isoformat()}", f"Edited {', '.join(changed)}", reason, entity="HistoryEntry", entity_id=e.id, raw=True)
        audit.record(db, actor_id=actor.id, action="register.history_edit", obj=s, before={k: str(before[k]) for k in changed}, after={k: str(getattr(e, k)) for k in changed},
                     summary=f"Edited a history entry of {s.reference} {s.name}")
    if e.type == "bias_test":
        bt = db.scalar(select(BiasTest).where(BiasTest.history_entry_id == e.id, BiasTest.deleted_at.is_(None)))
        if bt is not None:
            _bias_from_entry(bt, e)
    return e


def delete_entry(db: Session, actor: User, s: RegisterSystem, e: HistoryEntry, reason: str | None) -> None:
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why the entry is being deleted."}])
    e.deleted_at, e.updated_by = utcnow(), actor.id
    for bt in db.scalars(select(BiasTest).where(BiasTest.history_entry_id == e.id, BiasTest.deleted_at.is_(None))):
        bt.deleted_at = utcnow()
    svc.log_change(db, actor, s, "history", f"{TYPE_LABELS[e.type]}: {e.summary[:200]}", "Deleted", reason, entity="HistoryEntry", entity_id=e.id, raw=True)
    audit.record(db, actor_id=actor.id, action="register.history_delete", obj=s, before={"type": e.type, "summary": e.summary[:300]}, after={"reason": reason},
                 summary=f"Deleted a history entry of {s.reference} {s.name}")


def get_entry(db: Session, s: RegisterSystem, entry_id: str) -> HistoryEntry:
    e = db.get(HistoryEntry, entry_id)
    if e is None or e.deleted_at is not None or e.register_system_id != s.id:
        raise NotFound()
    return e


# ---- bias tests (§24.5 bias testing; recorded in the history log as well)
def _bias_from_entry(bt: BiasTest, e: HistoryEntry) -> None:
    det = e.details or {}
    bt.tested_on = e.occurred_on
    bt.tester_type = det.get("tester_type", bt.tester_type)
    bt.tester_name, bt.method, bt.groups_tested = det.get("tester_name"), det.get("method"), det.get("groups_tested")
    bt.result, bt.unknown_share, bt.result_text = det.get("result", bt.result), det.get("unknown_share"), e.result
    bt.next_due = date.fromisoformat(det["next_due"]) if det.get("next_due") else e.occurred_on + timedelta(days=365)


def record_bias_test(db: Session, actor: User, s: RegisterSystem, data: dict) -> tuple[BiasTest, HistoryEntry]:
    errs: list[dict] = []
    tested_on = svc._date(data.get("tested_on"), "tested_on", errs)
    if tested_on is None and not errs:
        errs.append({"field": "tested_on", "message": "Enter the test date."})
    det = _details("bias_test", {k: data.get(k) for k in DETAIL_FIELDS["bias_test"]}, errs)
    if not det.get("tester_type") and "details.tester_type" not in {e["field"] for e in errs}:
        errs.append({"field": "tester_type", "message": "Choose who ran the test."})
    if not det.get("result") and "details.result" not in {e["field"] for e in errs}:
        errs.append({"field": "result", "message": "Choose the result."})
    report = svc._file(db, s.organization_id, data.get("report_evidence_id"), "report_evidence_id", errs)
    if errs:
        raise Invalid(errors=[{**e, "field": e["field"].removeprefix("details.")} for e in errs])
    next_due = date.fromisoformat(det["next_due"]) if det.get("next_due") else tested_on + timedelta(days=365)
    det["next_due"] = next_due.isoformat()
    summary = str(data.get("summary") or "").strip() or " · ".join(x for x in (TESTER_LABELS[det["tester_type"]], det.get("tester_name"), det.get("method")) if x)
    evidence = [x for x in (data.get("evidence_ids") or []) if isinstance(x, str)] + ([report] if report else [])
    e = HistoryEntry(organization_id=s.organization_id, register_system_id=s.id, type="bias_test", occurred_on=tested_on, summary=summary[:4000],
                     result=str(data.get("result_text") or "").strip()[:4000] or BIAS_RESULTS[det["result"]], details=det, evidence_ids=list(dict.fromkeys(evidence)),
                     requirement_ids=list(data.get("requirement_ids") or []), recorded_by=actor.id, recorded_at=utcnow(), created_by=actor.id)
    db.add(e)
    db.flush()
    bt = BiasTest(organization_id=s.organization_id, register_system_id=s.id, tested_on=tested_on, next_due=next_due, tester_type=det["tester_type"],
                  tester_name=det.get("tester_name"), method=det.get("method"), groups_tested=det.get("groups_tested"), result=det["result"], result_text=e.result,
                  unknown_share=det.get("unknown_share"), report_evidence_id=report, history_entry_id=e.id, created_by=actor.id)
    db.add(bt)
    db.flush()
    old_due = s.bias_next_due
    s.bias_next_due = next_due
    svc.log_change(db, actor, s, "history", None, f"Recorded a bias test of {tested_on.isoformat()}: {BIAS_RESULTS[det['result']]}", None, entity="BiasTest", entity_id=bt.id, raw=True)
    if old_due != next_due:
        svc.log_change(db, actor, s, "bias_next_due", old_due, next_due, "Set from the latest bias test.")
    audit.record(db, actor_id=actor.id, action="register.bias_test", obj=s, after={"tested_on": tested_on.isoformat(), "result": det["result"], "unknown_share": det.get("unknown_share")},
                 summary=f"Recorded a bias test for {s.reference} {s.name}")
    return bt, e


# ---- first-entry questions and the no-incident statement
def _statement(db: Session, s: RegisterSystem) -> NoIncidentStatement | None:
    return db.scalar(select(NoIncidentStatement).where(NoIncidentStatement.register_system_id == s.id, NoIncidentStatement.deleted_at.is_(None)).order_by(NoIncidentStatement.created_at.desc()).limit(1))


def statement_text(s: RegisterSystem, period_from: date | None) -> str:
    since = f"since {period_from.isoformat()}" if period_from else "to date"
    return f"I am the system owner of {s.name} ({s.reference}). {since[0].upper() + since[1:]}, I know of no incidents, complaints or errors involving this system."


def answer_questions(db: Session, actor: User, s: RegisterSystem, answers: dict) -> RegisterSystem:
    errs = [{"field": k, "message": "Answer yes or no."} for k in QUESTIONS if k in answers and answers[k] not in ANSWERS]
    if "incidents" in answers and answers["incidents"] == "not_applicable":
        errs.append({"field": "incidents", "message": "Answer yes or no."})
    if errs:
        raise Invalid(errors=errs)
    given = {k: answers[k] for k in QUESTIONS if k in answers}
    old = dict(s.history_answers or {})
    s.history_answers = old | given
    svc.log_change(db, actor, s, "history_answers", ", ".join(f"{k}: {v}" for k, v in old.items()) or None, ", ".join(f"{k}: {v}" for k, v in s.history_answers.items()), None, raw=True)
    st = _statement(db, s)
    if given.get("incidents") == "no":
        if st is None or st.signed_at is not None and st.signed_by != s.owner_user_id:
            st = NoIncidentStatement(organization_id=s.organization_id, register_system_id=s.id, period_from=s.live_since or s.created_at.date(), created_by=actor.id,
                                     statement=statement_text(s, s.live_since or s.created_at.date()))
            db.add(st)
            db.flush()
        if st.signed_at is None:
            if s.owner_user_id == actor.id and answers.get("sign_as"):
                sign_statement(db, actor, s, answers["sign_as"])
            elif s.owner_user_id and s.owner_user_id != actor.id:
                from app.notifications.service import notify

                notify(db, [db.get(User, s.owner_user_id)], "register_no_incident_statement", f"Sign the no-incident statement for {s.name}",
                       f"{actor.name} answered that no incidents are known. As system owner, please confirm by signing.", f"/register/{s.id}/history")
    elif given.get("incidents") == "yes" and st is not None and st.signed_at is None:
        st.deleted_at = utcnow()
    audit.record(db, actor_id=actor.id, action="register.history_answers", obj=s, after=given, summary=f"Answered the history questions for {s.reference} {s.name}")
    return s


def sign_statement(db: Session, actor: User, s: RegisterSystem, typed_name: str) -> NoIncidentStatement:
    st = _statement(db, s)
    if st is None:
        raise Conflict("There is no no-incident statement to sign. Answer the history question first.")
    if st.signed_at is not None:
        raise Conflict("This statement is already signed.")
    if s.owner_user_id != actor.id:
        raise Forbidden("Only the system owner can sign the no-incident statement.")
    typed = " ".join(str(typed_name or "").split())
    if typed.casefold() != actor.name.casefold():
        raise Invalid(errors=[{"field": "typed_name", "message": f"Type your name exactly as {actor.name}."}])
    st.signed_by, st.signed_by_name, st.signed_at = actor.id, actor.name, utcnow()
    st.statement = statement_text(s, st.period_from)
    svc.log_change(db, actor, s, "history", None, "Signed the no-incident statement", None, entity="NoIncidentStatement", entity_id=st.id, raw=True)
    audit.record(db, actor_id=actor.id, action="register.no_incident_signed", obj=s, after={"statement": st.statement}, summary=f"Signed the no-incident statement for {s.reference} {s.name}")
    return st


# ---- read
def entry_out(db: Session, e: HistoryEntry) -> dict:
    who = db.get(User, e.recorded_by) if e.recorded_by else None
    from app.files.models import FileObject

    files = [f for f in (db.get(FileObject, i) for i in e.evidence_ids or []) if f is not None and f.deleted_at is None]
    return {"id": e.id, "type": e.type, "type_label": TYPE_LABELS.get(e.type, e.type), "occurred_on": e.occurred_on.isoformat(), "summary": e.summary, "result": e.result,
            "severity": e.severity, "severity_label": SEVERITIES.get(e.severity or ""), "details": e.details or {}, "requirement_ids": e.requirement_ids or [],
            "evidence": [{"id": f.id, "filename": f.filename} for f in files], "recorded_by": who.name if who else None, "recorded_at": e.recorded_at.isoformat()}


def statement_out(db: Session, s: RegisterSystem) -> dict | None:
    st = _statement(db, s)
    if st is None:
        return None
    owner = db.get(User, s.owner_user_id) if s.owner_user_id else None
    return {"id": st.id, "statement": st.statement, "period_from": st.period_from.isoformat() if st.period_from else None, "signed_by": st.signed_by_name,
            "signed_at": st.signed_at.isoformat() if st.signed_at else None, "owner": owner.name if owner else None, "owner_id": owner.id if owner else None}


def tracing(db: Session, s: RegisterSystem) -> dict:
    """The tracing add-on is shown locked on every system; recommended for Tier 3, agents that take actions, or a past incident (§27.3)."""
    reasons = []
    if s.risk_tier == 3:
        reasons.append("Tier 3")
    if s.type == "agent" and (svc.actions_of(db, s) or s.autonomy in ("acts_with_approval", "autonomous")):
        reasons.append("an AI agent that takes actions")
    n = sum(1 for e in _entries(db, s) if e.type == "incident")
    if n:
        reasons.append(f"{n} past incident{'s' if n != 1 else ''}")
    return {"locked": True, "recommended": bool(reasons), "reasons": reasons}


def history_summary(db: Session, s: RegisterSystem) -> dict:
    return {"answers": s.history_answers or {}, "statement": statement_out(db, s), "tracing": tracing(db, s)}


def history_out(db: Session, s: RegisterSystem) -> dict:
    return {"entries": [entry_out(db, e) for e in _entries(db, s)], **history_summary(db, s)}
