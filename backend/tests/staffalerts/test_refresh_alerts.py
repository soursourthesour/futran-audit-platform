"""§27.9 M6: Chief Auditor refresh alerts — recipients, channels, content, reminders, escalation and settings."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.core.clock import utcnow
from app.mail.models import OutboxMessage
from app.refresh.models import RefreshRun
from app.regmaster.models import ChangeImpact, ProposedChange
from app.staffalerts.models import AlertSetting, StaffAlert
from app.staffalerts.service import alert_run_finished, get_setting, resolve_run_alerts, run_reminders
from tests.factories import login_as


def _run(db, lit, changes=(("new_law", "high"), ("effective_date", "low")), kind="law"):
    run = RefreshRun(kind=kind, started_by=lit["chief"].id, status="completed", sources_read=41, finished_at=utcnow())
    db.add(run)
    db.flush()
    for ct, conf in changes:
        pc = ProposedChange(refresh_run_id=run.id, origin="claude_refresh", change_type=ct, field_path="law.effective_on", summary=f"{ct} change", confidence=conf)
        db.add(pc)
        db.flush()
        db.add(ChangeImpact(proposed_change_id=pc.id, organization_id=lit["abc"].id, ai_system_ids=[lit["screening"].id]))
    db.commit()
    return run


def _alerts(db, kind="refresh_done"):
    return list(db.scalars(select(StaffAlert).where(StaffAlert.kind == kind)))


def test_finished_run_alerts_every_chief_auditor_in_app_and_by_email(db, lit, settings):
    run = _run(db, lit)
    alert_run_finished(db, settings, run)
    alerts = _alerts(db)
    assert {a.user_id for a in alerts if not a.is_copy} == {lit["chief"].id, lit["chief2"].id}
    a = next(x for x in alerts if x.user_id == lit["chief"].id)
    assert a.summary["counts"]["new_laws"] == 1 and a.summary["counts"]["amendments_dates"] == 1
    assert a.summary["clients_affected"] == 1 and a.summary["systems_affected"] == 1 and a.summary["low_confidence"] == 1
    assert a.summary["sources_read"] == 41
    mail = db.get(OutboxMessage, a.email_send_id)
    assert mail.subject == "Refresh done: 2 law changes need your review"
    assert "client alerts for these changes are on hold" in mail.body_text.lower()
    assert "quinn@futran.test" in (mail.cc or [])  # copy to the QA Reviewer by default
    assert db.scalar(select(AuditLog).where(AuditLog.action == "staff_alert.sent")) is not None
    from app.mail.models import AdminLogEntry

    entry = db.scalar(select(AdminLogEntry).where(AdminLogEntry.action == "refresh_alert"))
    assert entry is not None and entry.owner == "futran" and "Cara Chief" in entry.summary


def test_nothing_new_is_alerted_only_when_the_setting_says_every_run(db, lit, settings):
    run = _run(db, lit, changes=())
    alert_run_finished(db, settings, run)
    assert _alerts(db) and "nothing new" in _alerts(db)[0].title.lower()
    s = get_setting(db, "law_refresh")
    s.when_rule = "changes"
    run2 = _run(db, lit, changes=())
    before = len(_alerts(db))
    alert_run_finished(db, settings, run2)
    assert len(_alerts(db)) == before


def test_only_high_impact_rule_skips_routine_runs(db, lit, settings):
    get_setting(db, "law_refresh").when_rule = "high_impact"
    alert_run_finished(db, settings, _run(db, lit, changes=(("guidance", "high"),)))
    assert _alerts(db) == []
    alert_run_finished(db, settings, _run(db, lit, changes=(("guidance", "low"),)))
    assert _alerts(db)


def test_only_the_runner_and_in_app_only(db, lit, settings):
    s = get_setting(db, "law_refresh")
    s.recipients_rule, s.channels, s.cc_roles = "runner", ["in_app"], []
    run = _run(db, lit)
    alert_run_finished(db, settings, run)
    assert [a.user_id for a in _alerts(db)] == [lit["chief"].id]
    assert _alerts(db)[0].email_send_id is None


def test_litigation_runs_use_their_own_setting(db, lit, settings):
    get_setting(db, "litigation_refresh").channels = ["in_app"]
    run = _run(db, lit, changes=(("case_update", "high"),), kind="litigation")
    alert_run_finished(db, settings, run)
    a = _alerts(db)[0]
    assert a.scope == "litigation_refresh" and a.summary["counts"]["case_updates"] == 1 and a.email_send_id is None
    assert "litigation" in a.title.lower()


def test_reminder_after_three_days_and_escalation_after_seven(db, lit, settings):
    run = _run(db, lit)
    alert_run_finished(db, settings, run)
    t0 = _alerts(db)[0].created_at
    run_reminders(db, settings, t0 + timedelta(days=2))
    assert _alerts(db, "review_reminder") == []
    run_reminders(db, settings, t0 + timedelta(days=3, hours=1))
    reminders = _alerts(db, "review_reminder")
    assert {r.user_id for r in reminders if not r.is_copy} == {lit["chief"].id, lit["chief2"].id}
    run_reminders(db, settings, t0 + timedelta(days=4))
    assert len(_alerts(db, "review_reminder")) == len(reminders)  # once per run
    run_reminders(db, settings, t0 + timedelta(days=7, hours=1))
    esc = {a.user_id for a in _alerts(db, "escalation")}
    assert lit["admin"].id in esc and lit["chief2"].id in esc


def test_escalation_goes_to_the_other_chief_auditor_when_only_the_runner_was_alerted(db, lit, settings):
    get_setting(db, "law_refresh").recipients_rule = "runner"
    run = _run(db, lit)
    alert_run_finished(db, settings, run)
    t0 = _alerts(db)[0].created_at
    run_reminders(db, settings, t0 + timedelta(days=8))
    esc = {a.user_id for a in _alerts(db, "escalation")}
    assert esc == {lit["chief2"].id, lit["admin"].id}


def test_reviewing_every_change_resolves_the_alerts_and_stops_reminders(db, lit, settings):
    run = _run(db, lit)
    alert_run_finished(db, settings, run)
    for pc in db.scalars(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id)):
        pc.status = "approved"
    resolve_run_alerts(db, run.id)
    assert all(a.resolved_at for a in _alerts(db))
    run_reminders(db, settings, utcnow() + timedelta(days=10))
    assert _alerts(db, "review_reminder") == [] and _alerts(db, "escalation") == []


def test_held_changes_still_count_as_waiting(db, lit, settings):
    run = _run(db, lit, changes=(("effective_date", "medium"),))
    alert_run_finished(db, settings, run)
    db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id)).status = "held"
    resolve_run_alerts(db, run.id)
    assert not any(a.resolved_at for a in _alerts(db))


def test_alert_api_lists_own_alerts_unresolved_first_and_marks_read(client, db, lit, settings):
    run = _run(db, lit)
    alert_run_finished(db, settings, run)
    old = _run(db, lit, changes=())
    alert_run_finished(db, settings, old)
    db.commit()
    login_as(client, db, lit["chief"])
    out = client.get("/api/v1/staff/alerts").json()
    assert out["unread"] == 2
    assert out["items"][0]["kind"] == "refresh_done" and out["items"][0]["needs_action"] is True
    assert out["items"][-1]["needs_action"] is False
    aid = out["items"][0]["id"]
    assert client.post(f"/api/v1/staff/alerts/{aid}/read").status_code == 200
    assert client.get("/api/v1/staff/alerts").json()["unread"] == 1
    client.post("/api/v1/staff/alerts/read-all")
    assert client.get("/api/v1/staff/alerts").json()["unread"] == 0
    login_as(client, db, lit["chief2"])
    assert client.post(f"/api/v1/staff/alerts/{aid}/read").status_code == 404  # not hers


def test_settings_are_for_the_chief_auditor_and_admin(client, db, lit):
    login_as(client, db, lit["aud"])
    assert client.get("/api/v1/staff/alerts/settings").status_code == 403
    login_as(client, db, lit["admin"])
    r = client.put("/api/v1/staff/alerts/settings/law_refresh", json={"recipients_rule": "runner", "cc_roles": ["admin"], "when_rule": "changes", "channels": ["in_app", "email"], "remind_after_days": 5, "escalate_after_days": None})
    assert r.status_code == 200, r.text
    s = db.scalar(select(AlertSetting).where(AlertSetting.scope == "law_refresh"))
    db.refresh(s)
    assert s.remind_after_days == 5 and s.escalate_after_days is None and s.cc_roles == ["admin"]
    assert client.put("/api/v1/staff/alerts/settings/law_refresh", json={"remind_after_days": 0}).status_code == 422


def test_send_a_test_alert(client, db, lit):
    login_as(client, db, lit["chief"])
    r = client.post("/api/v1/staff/alerts/test", json={"scope": "law_refresh"})
    assert r.status_code == 200
    a = db.scalar(select(StaffAlert).where(StaffAlert.user_id == lit["chief"].id))
    assert a.title.startswith("Test alert")
