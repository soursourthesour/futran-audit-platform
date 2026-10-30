"""Deadline reminders (spec §14 pattern, §27.3) and the recommended add-on opportunity (§27.5)."""
from datetime import datetime

from sqlalchemy import select

from app.core import clock
from app.mail.models import OutboxMessage
from app.notifications import jobs
from app.notifications.models import Notification
from app.tracing.jobs import run_incident_deadlines
from tests.tracing.conftest import activate, in_scope, incident_lead


def _setup(client, db, trc):
    clock.set_now(datetime(2028, 3, 1, 8, 0))
    try:
        in_scope(db, trc.org, "dpdp", "eu")
        incident_lead(db, trc.org, trc.dpo)
        activate(client, trc, [trc.agent])
        trc.as_(trc.caico)
        r = client.post(f"/api/v1/register/{trc.agent.id}/tracing/incidents", json={"description": "Supplier bank details changed by the agent", "found_at": "2028-03-01T08:00",
                                                                                     "severity": "high", "serious_kind": "none", "cyber_incident": True, "owner_id": trc.fin_lead.id})
        assert r.status_code == 200, r.text
        return r.json()
    finally:
        clock.set_now(None)


def _kinds(db, kind):
    return sorted(n.user_id for n in db.scalars(select(Notification).where(Notification.kind == kind)))


def test_reminder_then_missed_each_once(client, db, trc, settings):
    _setup(client, db, trc)  # CERT-In: due 14:00, reminder from 12:30
    assert run_incident_deadlines(db, settings, datetime(2028, 3, 1, 12, 0)) == 0
    assert run_incident_deadlines(db, settings, datetime(2028, 3, 1, 12, 30)) == 1
    assert run_incident_deadlines(db, settings, datetime(2028, 3, 1, 13, 0)) == 0
    assert _kinds(db, "incident_deadline_reminder") == sorted([trc.dpo.id, trc.caico.id, trc.fin_lead.id])
    n = db.scalar(select(Notification).where(Notification.kind == "incident_deadline_reminder", Notification.user_id == trc.dpo.id))
    assert "CERT-In" in n.title and "1 h 30 min" in n.title and n.link == f"/register/{trc.agent.id}/tracing"
    assert run_incident_deadlines(db, settings, datetime(2028, 3, 1, 14, 1)) == 1
    assert run_incident_deadlines(db, settings, datetime(2028, 3, 1, 18, 0)) == 0
    assert len(_kinds(db, "incident_deadline_missed")) == 3
    assert sum(1 for m in db.scalars(select(OutboxMessage)) if "daniel@abc.test" in m.to and "CERT-In" in m.subject) >= 2  # emailed too


def test_recorded_notices_are_not_chased(client, db, trc, settings):
    inc = _setup(client, db, trc)
    did = inc["deadlines"][0]["id"]
    clock.set_now(datetime(2028, 3, 1, 10, 30))
    try:
        trc.as_(trc.caico)
        r = client.post(f"/api/v1/register/{trc.agent.id}/tracing/deadlines/{did}", json={"action": "done", "done_at": "2028-03-01T10:00", "reference": "CERT-In ack 991"})
        assert r.status_code == 200, r.text
    finally:
        clock.set_now(None)
    assert run_incident_deadlines(db, settings, datetime(2028, 3, 1, 15, 0)) == 0


def test_deadline_job_runs_daily_and_on_its_own_tick():
    assert "incident_deadlines" in jobs.JOBS


def test_recommended_addon_opportunity_skips_traced_systems_and_counts_past_incidents(client, db, trc, settings):
    """WS-D's daily trigger (app.sales.service) with WS-E's coverage and past-incident rules."""
    from app.register.models import HistoryEntry
    from app.sales.service import open_recommended_addon_opportunities, tracing_candidates

    db.add(HistoryEntry(organization_id=trc.org.id, register_system_id=trc.notes.id, type="incident", occurred_on=datetime(2026, 5, 1).date(), summary="Wrong summary sent", severity="low"))
    db.commit()
    assert {s.id for s in tracing_candidates(db)[trc.org.id]} == {trc.screening.id, trc.agent.id, trc.notes.id}
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    client.post("/api/v1/addons/tracing/requests", json={"system_ids": [trc.agent.id], "plan": "per_system", "trial": False, "approver_id": trc.sponsor.id})
    assert {s.id for s in tracing_candidates(db)[trc.org.id]} == {trc.notes.id}
    made = open_recommended_addon_opportunities(db)
    assert [o.system_ids for o in made] == [[trc.notes.id]]
