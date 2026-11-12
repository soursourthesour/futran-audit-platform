"""Continuous monitoring (spec §21 F3, screen 31).

A client on the Monitor or Monitor Plus plan gets a run of every registered check once a month (with a re-sync of its
connectors first) and after each connector sync or upload. A run is claimed through the unique (organization_id,
run_key), so two schedulers that overlap never run or alert twice. A failed result alerts the client's CAICO and the
assigned Futran auditor once: when the same check and object were not failed in the previous run. Monitoring only reads
audit data and writes its own tables, notifications and the follow-ups a person starts; it never changes a signed report.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Invalid, NotFound
from app.monitoring import registry
from app.monitoring.models import MONITOR_PLANS, PLANS, SEVERITIES, STATUSES, MonitorCheck, MonitorResult, MonitorRun, Subscription
from app.monitoring.registry import CheckOutcome
from app.tenancy.models import Organization, RoleAssignment, User

log = logging.getLogger(__name__)
PLAN_LABELS = {"audit_only": "Audit only", "monitor": "Monitor", "monitor_plus": "Monitor Plus"}
OFFERS = [
    "Monthly re-sync of your connected identity, email and expense sources",
    "New undeclared AI tool found through a connector or an expense or network-log upload",
    "Tier 3 system with no bias test in 12 months, and NYC Local Law 144 bias audits older than 12 months",
    "AI policy older than 12 months or past its review date",
    "Commitments overdue or due within 14 days",
    "AI literacy training below its target",
    "Vendor SOC 2 report expired or expiring within 30 days",
    "Alerts to your Chief AI Compliance Officer and your Futran auditor, and a dashboard of every check",
]
ACTION_LABELS = {"start_reassessment": "Start reassessment", "review": "Review", "open": "Open", "send_reminder": "Send reminder", "request_report": "Request new report"}
_suppress_after_sync: set[str] = set()  # organisations whose monthly run is re-syncing connectors right now


def plan_of(org: Organization) -> str:
    return org.subscription_plan or "audit_only"


def is_monitored(org: Organization) -> bool:
    return plan_of(org) in MONITOR_PLANS


def current_subscription(db: Session, org_id: str) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.organization_id == org_id, Subscription.deleted_at.is_(None), Subscription.end_on.is_(None))
                     .order_by(Subscription.created_at.desc()).limit(1))


def set_plan(db: Session, user: User, org: Organization, plan: str, *, start_on: date | None = None, end_on: date | None = None,
             next_review_on: date | None = None, note: str | None = None) -> Subscription:
    if plan not in PLANS:
        raise Invalid(errors=[{"field": "plan", "message": "Choose Audit only, Monitor or Monitor Plus."}])
    if org.type != "client":
        raise NotFound()
    before = plan_of(org)
    prev = current_subscription(db, org.id)
    if prev is not None:
        prev.end_on = today()
    sub = Subscription(organization_id=org.id, plan=plan, start_on=start_on or today(), end_on=end_on, next_review_on=next_review_on, set_by=user.id,
                       note=(" ".join((note or "").split()) or None) if note else None, created_by=user.id)
    db.add(sub)
    org.subscription_plan = plan
    audit.record(db, actor_id=user.id, action="subscription.plan_set", obj=sub, organization_id=org.id,
                 summary=f"{org.name}: plan changed from {PLAN_LABELS[before]} to {PLAN_LABELS[plan]}"
                         + (f"; next Futran annual review {next_review_on.isoformat()}" if next_review_on else ""))
    db.flush()
    return sub


# ---------------------------------------------------------------- runs
def _claim(db: Session, org: Organization, trigger: str, key: str, actor_id: str | None, now: datetime) -> MonitorRun | None:
    run = MonitorRun(organization_id=org.id, run_key=key[:80], trigger=trigger, started_at=now, status="running", counts={}, started_by=actor_id)
    try:
        with db.begin_nested():
            db.add(run)
            db.flush()
    except IntegrityError:
        return None
    return run


def _outcomes(db: Session, org: Organization, rc) -> list[CheckOutcome]:
    try:
        with db.begin_nested():
            out = list(rc.fn(db, org) or [])
    except Exception as exc:  # noqa: BLE001 (one failing check must not stop the others)
        log.exception("Monitoring check %s failed for %s", rc.code, org.id)
        return [CheckOutcome(None, org.name, "not_started", f"The check could not run ({exc.__class__.__name__}). Futran has been told.")]
    return out or [CheckOutcome(None, org.name, "healthy", "Nothing needs action.")]


def _previous_status(db: Session, org_id: str, check_id: str, object_id: str | None, run_id: str) -> str | None:
    q = (select(MonitorResult.status).join(MonitorRun, MonitorRun.id == MonitorResult.run_id)
         .where(MonitorResult.organization_id == org_id, MonitorResult.check_id == check_id, MonitorResult.run_id != run_id, MonitorRun.status == "completed"))
    q = q.where(MonitorResult.object_id.is_(None) if object_id is None else MonitorResult.object_id == object_id)
    return db.scalar(q.order_by(MonitorRun.started_at.desc(), MonitorRun.created_at.desc()).limit(1))


def alert_recipients(db: Session, org: Organization) -> list[User]:
    """The client's CAICO(s) and the auditors assigned to its current engagement."""
    from app.engagements.models import Engagement, EngagementTeam

    caicos = list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(
        User.organization_id == org.id, RoleAssignment.role == "caico", RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None))))
    e = db.scalar(select(Engagement).where(Engagement.client_id == org.id, Engagement.deleted_at.is_(None), Engagement.status.not_in(["draft", "pending_approval"]), Engagement.type != "incident_response")
                  .order_by(Engagement.created_at.desc()).limit(1))
    auditors = list(db.scalars(select(User).join(EngagementTeam, EngagementTeam.user_id == User.id).where(
        EngagementTeam.engagement_id == e.id, EngagementTeam.role == "auditor", EngagementTeam.deleted_at.is_(None)))) if e else []
    return caicos + auditors


def _alert(db: Session, settings: Settings | None, org: Organization, check: MonitorCheck, r: MonitorResult, now: datetime) -> bool:
    res = db.execute(update(MonitorResult).where(MonitorResult.id == r.id, MonitorResult.alert_sent.is_(False))
                     .values(alert_sent=True, alert_sent_at=now).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        return False
    r.alert_sent, r.alert_sent_at = True, now
    from app.notifications.service import notify

    users = alert_recipients(db, org)
    for u in users:
        futran = db.get(Organization, u.organization_id).type == "futran"
        link = f"/clients/{org.id}/monitoring" if futran else "/monitoring"
        notify(db, [u], "monitoring_check_failed", f"{org.name}: {check.description}", f"{r.object_label}: {r.detail}", link, settings=settings,
               email_template="notification" if settings is not None else None)
    return True


def run(db: Session, settings: Settings | None, org: Organization, trigger: str, key: str, actor: User | None = None, now: datetime | None = None) -> MonitorRun | None:
    """Run every registered check for `org`, or return None when the client is not on a Monitor plan or the run key was
    already claimed."""
    if not is_monitored(org):
        return None
    now = now or utcnow()
    mr = _claim(db, org, trigger, key, actor.id if actor else None, now)
    if mr is None:
        return None
    registry.load_checks()
    rows = registry.sync_checks(db)
    counts = dict.fromkeys(STATUSES, 0)
    failed: list[tuple[MonitorCheck, MonitorResult]] = []
    for code, rc in registry.CHECKS.items():
        check = rows[code]
        for o in _outcomes(db, org, rc):
            r = MonitorResult(organization_id=org.id, run_id=mr.id, check_id=check.id, object_id=o.object_id, object_label=(o.object_label or "")[:300], status=o.status,
                              detail=o.detail, action=o.action, action_link=(o.action_link or None), register_system_id=o.register_system_id, run_at=now, alert_sent=False)
            db.add(r)
            counts[o.status] += 1
            if o.status == "failed":
                failed.append((check, r))
    db.flush()
    for check, r in failed:
        if _previous_status(db, org.id, check.id, r.object_id, mr.id) != "failed":
            _alert(db, settings, org, check, r, now)
    mr.status, mr.finished_at, mr.counts = "completed", utcnow(), counts
    audit.record(db, actor_id=actor.id if actor else None, actor_name=None if actor else "Scheduler", action="monitoring.run", obj=mr,
                 summary=f"Monitoring run ({trigger}): {counts['healthy']} healthy, {counts['attention']} attention, {counts['failed']} failed, {counts['not_started']} not started")
    db.flush()
    return mr


def after_sync(db: Session, settings: Settings | None, org: Organization, connector_run) -> MonitorRun | None:
    """The run after a connector sync or upload. A failure here is logged and undone; it never fails the sync or upload."""
    if org is None or org.id in _suppress_after_sync:
        return None
    try:
        with db.begin_nested():
            return run(db, settings, org, "sync", f"sync:{connector_run.id}", now=connector_run.finished_at)
    except Exception:  # noqa: BLE001
        log.exception("Monitoring run after %s %s failed for %s", connector_run.kind, connector_run.id, org.id)
        return None


def run_monthly(db: Session, settings: Settings | None, now: datetime | date) -> int:
    """The scheduled job: once a calendar month for each client on a Monitor plan, re-sync its connectors, then run."""
    now = now if isinstance(now, datetime) else datetime.combine(now, datetime.min.time())
    n = 0
    for org in list(db.scalars(select(Organization).where(Organization.type == "client", Organization.deleted_at.is_(None), Organization.subscription_plan.in_(MONITOR_PLANS)))):
        key = f"monthly:{now:%Y-%m}"
        if db.scalar(select(MonitorRun.id).where(MonitorRun.organization_id == org.id, MonitorRun.run_key == key)):
            continue
        try:
            with db.begin_nested():  # one client's failure leaves the other clients' runs in place
                _resync(db, settings, org, now)
                done = run(db, settings, org, "monthly", key, now=now) is not None
        except Exception:  # noqa: BLE001 (logged; nothing of this client's run is kept, so the next daily job tries again)
            log.exception("Monthly monitoring run failed for %s", org.id)
            continue
        n += int(done)
    db.flush()
    return n


def _resync(db: Session, settings: Settings | None, org: Organization, now: datetime) -> None:
    from app.connectors import service as csvc
    from app.connectors.models import UPLOAD_TYPES, Connector

    if settings is None:
        return
    _suppress_after_sync.add(org.id)
    try:
        for c in list(db.scalars(select(Connector).where(Connector.organization_id == org.id, Connector.status == "connected", Connector.deleted_at.is_(None)))):
            if c.type in UPLOAD_TYPES:
                continue
            try:
                with db.begin_nested():
                    csvc.sync(db, settings, c, None, now=now)
            except Exception:  # noqa: BLE001 (a failed sync is logged on its run; the checks still run)
                log.exception("Monthly re-sync of %s failed for %s", c.type, org.id)
    finally:
        _suppress_after_sync.discard(org.id)


# ---------------------------------------------------------------- dashboard
def latest_run(db: Session, org_id: str) -> MonitorRun | None:
    return db.scalar(select(MonitorRun).where(MonitorRun.organization_id == org_id, MonitorRun.status == "completed", MonitorRun.deleted_at.is_(None))
                     .order_by(MonitorRun.started_at.desc(), MonitorRun.created_at.desc()).limit(1))


def next_review(db: Session, org: Organization) -> date | None:
    sub = current_subscription(db, org.id)
    if sub is not None and sub.next_review_on:
        return sub.next_review_on
    from app.engagements.models import Engagement
    from app.reports.models import Report

    signed = db.scalar(select(Report.signed_at).join(Engagement, Engagement.id == Report.engagement_id).where(
        Engagement.client_id == org.id, Report.status == "final", Report.signed_at.is_not(None)).order_by(Report.signed_at.desc()).limit(1))
    return (signed + timedelta(days=365)).date() if signed else None


def _training_reminder(db: Session, settings, user: User, org: Organization, result: MonitorResult) -> str:
    from app.training.service import send_reminders

    n = send_reminders(db, settings, user, org.id)
    return f"Reminder sent to {n} {'person' if n == 1 else 'people'} who have not finished their AI literacy training."


# Follow-ups for checks registered without on_action, by (check code, action)
FALLBACK_HANDLERS = {("training_below_target", "send_reminder"): _training_reminder}


def _handler(code: str, action: str | None):
    rc = registry.load_checks().get(code)
    return (getattr(rc, "on_action", None) if rc else None) or FALLBACK_HANDLERS.get((code, action or ""))


def action_kind(code: str, action: str | None) -> str | None:
    """"server": the button starts something here; "link": it opens action_link; None: no button."""
    if not action:
        return None
    if action == "start_reassessment":
        return "server"
    if action in ("request_report", "send_reminder") and _handler(code, action) is not None:
        return "server"
    return "link"


def result_out(r: MonitorResult, check: MonitorCheck) -> dict:
    return {"id": r.id, "check_code": check.code, "check": check.description, "severity": check.severity, "status": r.status, "object_id": r.object_id,
            "object_label": r.object_label, "detail": r.detail, "action": r.action, "action_label": ACTION_LABELS.get(r.action or ""), "action_link": r.action_link,
            "action_kind": action_kind(check.code, r.action),
            "action_taken": r.action_taken, "action_taken_at": r.action_taken_at.isoformat() if r.action_taken_at else None, "alert_sent": r.alert_sent,
            "run_at": r.run_at.isoformat()}


def dashboard(db: Session, org: Organization, *, for_futran: bool = False) -> dict:
    """The monitoring screen. The plan note is Futran's internal record (pricing, renewal plans): only Futran staff see it."""
    plan = plan_of(org)
    sub = current_subscription(db, org.id)
    nr = next_review(db, org)
    base = {"organization": {"id": org.id, "name": org.name}, "plan": plan, "plan_label": PLAN_LABELS[plan], "plans": [{"value": p, "label": PLAN_LABELS[p]} for p in PLANS],
            "subscription": {"start_on": sub.start_on.isoformat() if sub and sub.start_on else None, "end_on": None, "note": sub.note if for_futran else None} if sub else None,
            "next_review_on": nr.isoformat() if nr else None, "offers": OFFERS}
    if plan not in MONITOR_PLANS:
        return base | {"kpis": None, "needs_action": [], "healthy": [], "last_run": None, "runs": []}
    mr = latest_run(db, org.id)
    checks = {c.id: c for c in db.scalars(select(MonitorCheck))}
    results = list(db.scalars(select(MonitorResult).where(MonitorResult.run_id == mr.id))) if mr else []
    order = {"failed": 0, "attention": 1, "not_started": 2, "healthy": 3}
    sev = {s: i for i, s in enumerate(SEVERITIES)}
    results.sort(key=lambda r: (order[r.status], sev.get(checks[r.check_id].severity, 9), checks[r.check_id].description, r.object_label or ""))
    kpis = dict.fromkeys(STATUSES, 0)
    for r in results:
        kpis[r.status] += 1
    runs = db.scalars(select(MonitorRun).where(MonitorRun.organization_id == org.id, MonitorRun.deleted_at.is_(None)).order_by(MonitorRun.started_at.desc()).limit(12))
    return base | {"kpis": kpis, "needs_action": [result_out(r, checks[r.check_id]) for r in results if r.status in ("failed", "attention")],
                   "healthy": [result_out(r, checks[r.check_id]) for r in results if r.status in ("healthy", "not_started")],
                   "last_run": {"id": mr.id, "at": mr.started_at.isoformat(), "trigger": mr.trigger} if mr else None,
                   "runs": [{"id": x.id, "at": x.started_at.isoformat(), "trigger": x.trigger, "status": x.status, "counts": x.counts} for x in runs]}


# ---------------------------------------------------------------- acting on a result
def _load_result(db: Session, org: Organization, result_id: str) -> tuple[MonitorResult, MonitorCheck]:
    r = db.get(MonitorResult, result_id)
    if r is None or r.organization_id != org.id or r.deleted_at is not None:
        raise NotFound()
    return r, db.get(MonitorCheck, r.check_id)


def act(db: Session, settings: Settings | None, user: User, org: Organization, result_id: str) -> dict:
    """Start what the result's button offers: a reassessment trigger (WS-H), or the check's own follow-up (a document
    request for a new report, a training reminder). Review and Open are links and need no server action."""
    r, check = _load_result(db, org, result_id)
    if r.status not in ("failed", "attention"):
        raise Conflict("This check needs no action.")
    if r.action_taken:
        raise Conflict(f"{ACTION_LABELS.get(r.action_taken, r.action_taken)} was already started on {r.action_taken_at:%d %b %Y}.")
    if r.action == "start_reassessment":
        if not r.register_system_id:
            raise Conflict("This result is not linked to a system in your AI register.")
        try:
            from app.impact.triggers import raise_trigger
        except ImportError as exc:
            raise Conflict("Reassessment triggers are not available on this platform yet.") from exc
        t = raise_trigger(db, r.register_system_id, type="failed_monitor_check", source="monitor", detail=f"{check.description}: {r.detail}"[:500],
                          source_ref=f"monitor:{check.code}:{r.object_id or org.id}", actor_id=user.id)
        if t is None:
            raise Conflict("This system is no longer in your AI register, or it is retired.")
        message = "Reassessment started. The system shows the trigger on its register record, and its assessment is reopened for review when it is in an engagement."
    elif r.action in ("request_report", "send_reminder"):
        handler = _handler(check.code, r.action)
        if handler is None:
            raise Conflict("This follow-up opens a page; there is nothing to start here.")
        message = handler(db, settings, user, org, r) or "Done."
    else:
        raise Conflict("This result opens a page; there is nothing to start.")
    r.action_taken, r.action_taken_at, r.action_taken_by = r.action, utcnow(), user.id
    audit.record(db, actor_id=user.id, action=f"monitoring.{r.action}", obj=r, summary=f"{ACTION_LABELS[r.action]}: {check.description}, {r.object_label}")
    db.flush()
    return {"message": message, "result": result_out(r, check)}
