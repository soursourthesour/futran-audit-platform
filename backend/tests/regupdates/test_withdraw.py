"""Withdrawing a published regulatory update (spec §21 F4): its pending client alerts are cancelled, the reassessment
triggers it raised are closed, and clients who were told about it see it marked withdrawn with the reason."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.clientalerts.models import AlertSend
from app.impact.models import ReassessmentTrigger
from tests.factories import login_as
from tests.regupdates.conftest import nyc_enforcement, publish


def _queue(client, db, world, uid):
    login_as(client, db, world["chief"])
    r = client.post(f"/api/v1/reg/updates/{uid}/alerts", json={"organization_ids": [world["abc"].id]})
    assert r.status_code == 200, r.text
    return db.get(AlertSend, r.json()["queued"][0]["alert_send_id"])


def _withdraw(client, db, world, uid, reason="The source was misread"):
    login_as(client, db, world["legal"])
    r = client.post(f"/api/v1/reg/updates/{uid}/withdraw", json={"reason": reason})
    assert r.status_code == 200, r.text
    return r.json()


def test_withdrawal_cancels_the_alert_waiting_for_approval(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world))
    s = _queue(client, db, world, d["id"])
    _withdraw(client, db, world, d["id"])
    db.refresh(s)
    assert s.status == "cancelled"
    login_as(client, db, world["chief"])
    r = client.post("/api/v1/alerts/sends/approve", json={"ids": [s.id]})
    assert r.status_code == 200 and r.json()["sent"] == 0
    db.refresh(s)
    assert s.status == "cancelled" and s.sent_at is None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "client_alert.cancel", AuditLog.object_id == s.id)) is not None


def test_withdrawal_closes_the_reassessment_triggers_it_raised(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world))
    t = db.scalar(select(ReassessmentTrigger).where(ReassessmentTrigger.register_system_id == world["screening"].id))
    assert t.status == "open"
    _withdraw(client, db, world, d["id"])
    db.refresh(t)
    assert t.status == "dismissed" and t.resolved_at is not None and t.resolved_by == world["legal"].id
    assert t.resolution_note.endswith("withdrawn: The source was misread")
    assert db.scalar(select(AuditLog).where(AuditLog.action == "reassessment.dismiss", AuditLog.object_id == t.id)) is not None


def test_a_client_that_was_told_sees_the_update_marked_withdrawn_with_the_reason(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world))
    s = _queue(client, db, world, d["id"])
    assert client.post("/api/v1/alerts/sends/approve", json={"ids": [s.id]}).json()["sent"] == 1
    _withdraw(client, db, world, d["id"])
    login_as(client, db, world["maria"])
    items = client.get("/api/v1/updates").json()["items"]
    assert len(items) == 1
    i = items[0]
    assert i["status"] == "withdrawn" and i["withdrawn_reason"] == "The source was misread" and i["withdrawn_at"]
    assert i["todos"] == []


def test_a_client_that_received_it_in_the_weekly_digest_also_sees_it_withdrawn(client, db, world):
    from datetime import datetime

    from app.regupdates.models import RegulatoryAlert

    d = publish(client, db, world, nyc_enforcement(world))
    a = db.scalar(select(RegulatoryAlert).where(RegulatoryAlert.update_id == d["id"], RegulatoryAlert.organization_id == world["abc"].id))
    a.digested_at = datetime(2026, 11, 2, 10)
    db.commit()
    _withdraw(client, db, world, d["id"])
    login_as(client, db, world["maria"])
    assert [i["status"] for i in client.get("/api/v1/updates").json()["items"]] == ["withdrawn"]
