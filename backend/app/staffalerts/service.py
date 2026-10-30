"""Alerts to the Chief Auditor when a law or litigation refresh finishes, with reminders and escalation (spec §27.9)."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.config import Settings
from app.refresh.models import RefreshRun
from app.refresh.service import GROUP_LABELS, open_items, run_summary
from app.staffalerts.models import SCOPES, AlertSetting, StaffAlert
from app.tenancy.models import Organization, User
from app.tenancy.service import roles_of

HIGH_IMPACT_CLIENTS = 5


def get_setting(db: Session, scope: str) -> AlertSetting:
    s = db.scalar(select(AlertSetting).where(AlertSetting.scope == scope))
    if s is None:
        s = AlertSetting(scope=scope, recipients_rule="all_chief_auditors", cc_roles=["qa_reviewer"], when_rule="every",
                         channels=["in_app", "email"], remind_after_days=3, escalate_after_days=7, escalate_to_roles=["chief_auditor", "admin"])
        db.add(s)
        db.flush()
    return s


def futran_users_with(db: Session, roles: set[str]) -> list[User]:
    out = []
    q = select(User).join(Organization, Organization.id == User.organization_id).where(Organization.type == "futran", User.deleted_at.is_(None), User.status != "disabled").order_by(User.name)
    for u in db.scalars(q):
        if {r.role for r in roles_of(db, u.id)} & roles:
            out.append(u)
    return out


def scope_of(run: RefreshRun) -> str:
    return "litigation_refresh" if run.kind == "litigation" else "law_refresh"


def _wanted(s: AlertSetting, summary: dict) -> bool:
    if s.when_rule == "every":
        return True
    if s.when_rule == "changes":
        return summary["total"] > 0
    return summary["low_confidence"] > 0 or summary["new_laws"] > 0 or summary["clients_affected"] >= HIGH_IMPACT_CLIENTS


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _title(kind: str, scope: str, summary: dict, days: int | None = None) -> str:
    what = "case update" if scope == "litigation_refresh" else "law change"
    whats = what + "s"
    label = "Litigation refresh" if scope == "litigation_refresh" else "Refresh"
    if kind == "review_reminder":
        return f"Reminder: {_plural(summary['open'], what, whats)} still waiting for review"
    if kind == "escalation":
        return f"Escalation: {_plural(summary['open'], what, whats)} waiting more than {days} days"
    if summary["total"] == 0:
        return f"{label} done: nothing new"
    need = "needs" if summary["total"] == 1 else "need"
    return f"{label} done: {_plural(summary['total'], what, whats)} {need} your review"


def _recipients(db: Session, s: AlertSetting, run: RefreshRun) -> tuple[list[User], list[User]]:
    chiefs = futran_users_with(db, {"chief_auditor"})
    if s.recipients_rule == "runner" and run.started_by and any(u.id == run.started_by for u in chiefs):
        main = [u for u in chiefs if u.id == run.started_by]
    elif run.alert_recipients == "me" and run.started_by:
        main = [u for u in chiefs if u.id == run.started_by] or chiefs
    else:
        main = chiefs
    ids = {u.id for u in main}
    copies = [u for u in futran_users_with(db, set(s.cc_roles or [])) if u.id not in ids]
    return main, copies


def _send(db: Session, settings: Settings, kind: str, scope: str, run: RefreshRun | None, summary: dict, main: list[User], copies: list[User],
          channels: list[str], title: str, *, is_test: bool = False) -> list[StaffAlert]:
    if not main:
        return []
    mail_id = None
    if "email" in channels and settings is not None:
        from app.mail.service import send

        rows = [{"label": GROUP_LABELS[k], "count": v} for k, v in summary["counts"].items() if v]
        link = f"{settings.base_url}/litigation" if scope == "litigation_refresh" else f"{settings.base_url}/reg/refresh" + (f"?run={run.id}" if run else "")
        msg = send(db, settings, "staff_refresh_alert", to=[u.email for u in main], cc=[u.email for u in copies] or None, organization_id=main[0].organization_id,
                   context={"title": title, "kind": kind, "scope": scope, "summary": summary, "rows": rows, "link": link, "litigation_link": f"{settings.base_url}/litigation", "is_test": is_test})
        mail_id = msg.id
    out = []
    for u, copy in [(u, False) for u in main] + [(u, True) for u in copies]:
        a = StaffAlert(user_id=u.id, kind=kind, scope=scope, refresh_run_id=run.id if run else None, title=title[:300], summary=summary, is_copy=copy, is_test=is_test,
                       email_send_id=mail_id, read_at=None)
        if "in_app" not in channels:
            a.read_at = utcnow()  # email only: nothing waits under the bell
        db.add(a)
        out.append(a)
    db.flush()
    from app.mail import adminlog

    adminlog.write(db, organization_id=main[0].organization_id, category="send", action="refresh_alert" if kind == "refresh_done" else kind,
                   summary=f"{title} — to {', '.join(u.name for u in main)}" + (f"; copy {', '.join(u.name for u in copies)}" if copies else ""),
                   details={"run_id": run.id if run else None, "channels": list(channels), "email_message_id": mail_id})
    audit.record(db, actor_id=None, action="staff_alert.sent", object_type="StaffAlert", object_id=out[0].id, organization_id=main[0].organization_id,
                 summary=f"{title} — to {', '.join(u.name for u in main)}" + (f"; copy {', '.join(u.name for u in copies)}" if copies else ""))
    return out


def alert_run_finished(db: Session, settings: Settings, run: RefreshRun) -> list[StaffAlert]:
    scope = scope_of(run)
    s = get_setting(db, scope)
    summary = run_summary(db, run)
    if not _wanted(s, summary):
        run.alert_status = "No alert: the settings skip runs like this one"
        return []
    main, copies = _recipients(db, s, run)
    out = _send(db, settings, "refresh_done", scope, run, summary, main, copies, s.channels or [], _title("refresh_done", scope, summary))
    if out and summary["open"] == 0:
        for a in out:
            a.resolved_at = utcnow()
    run.alert_status = f"Alerted {', '.join(u.name for u in main)}" if out else "No Chief Auditor to alert"
    return out


def resolve_run_alerts(db: Session, run_id: str) -> None:
    if open_items(db, run_id):
        return
    now = utcnow()
    for a in db.scalars(select(StaffAlert).where(StaffAlert.refresh_run_id == run_id, StaffAlert.resolved_at.is_(None))):
        a.resolved_at = now
    db.flush()


def _already(db: Session, run_id: str, kind: str) -> bool:
    return db.scalar(select(StaffAlert.id).where(StaffAlert.refresh_run_id == run_id, StaffAlert.kind == kind).limit(1)) is not None


def run_reminders(db: Session, settings: Settings, now: datetime) -> int:
    """Daily: remind after N days, escalate after M days, while a run's changes still wait (held counts as waiting)."""
    sent = 0
    firsts = db.scalars(select(StaffAlert).where(StaffAlert.kind == "refresh_done", StaffAlert.resolved_at.is_(None), StaffAlert.is_test.is_(False), StaffAlert.is_copy.is_(False)))
    seen: set[str] = set()
    for first in firsts:
        if first.refresh_run_id is None or first.refresh_run_id in seen:
            continue
        seen.add(first.refresh_run_id)
        run = db.get(RefreshRun, first.refresh_run_id)
        if run is None:
            continue
        if not open_items(db, run.id):
            resolve_run_alerts(db, run.id)
            continue
        s = get_setting(db, first.scope)
        age = now - first.created_at
        summary = run_summary(db, run)
        if s.escalate_after_days and age >= timedelta(days=s.escalate_after_days) and not _already(db, run.id, "escalation"):
            original = {a.user_id for a in db.scalars(select(StaffAlert).where(StaffAlert.refresh_run_id == run.id, StaffAlert.kind == "refresh_done", StaffAlert.is_copy.is_(False)))}
            targets = futran_users_with(db, set(s.escalate_to_roles or []))
            if s.recipients_rule == "runner":  # "the other Chief Auditor": not the one who was alerted first
                targets = [u for u in targets if u.id not in original]
            sent += len(_send(db, settings, "escalation", first.scope, run, summary, targets, [], s.channels or [], _title("escalation", first.scope, summary, s.escalate_after_days)))
        elif s.remind_after_days and age >= timedelta(days=s.remind_after_days) and not _already(db, run.id, "review_reminder"):
            main, copies = _recipients(db, s, run)
            sent += len(_send(db, settings, "review_reminder", first.scope, run, summary, main, copies, s.channels or [], _title("review_reminder", first.scope, summary)))
    db.flush()
    return sent


def send_test_alert(db: Session, settings: Settings, user: User, scope: str) -> list[StaffAlert]:
    s = get_setting(db, scope)
    summary = {"kind": "law" if scope == "law_refresh" else "litigation", "trigger": "test", "sources_read": 0, "total": 0, "counts": {k: 0 for k in GROUP_LABELS},
               "open": 0, "clients_affected": 0, "systems_affected": 0, "low_confidence": 0, "low_confidence_items": [], "new_laws": 0}
    out = _send(db, settings, "refresh_done", scope, None, summary, [user], [], s.channels or ["in_app"], "Test alert: refresh alerts reach you", is_test=True)
    for a in out:
        a.resolved_at = utcnow()
    return out


__all__ = ["SCOPES", "alert_run_finished", "get_setting", "resolve_run_alerts", "run_reminders", "send_test_alert"]
