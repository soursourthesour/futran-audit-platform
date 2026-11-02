"""An update with a point still to confirm is not published as settled fact: the reviewer clears the note (logged) when
it is confirmed, or sends the update back."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.regupdates.models import RegulatoryAlert, RegulatoryUpdate
from tests.factories import login_as
from tests.regupdates.conftest import nyc_enforcement

NOTE = "Confirm the report number against the Comptroller's page."


def _awaiting(client, db, world):
    login_as(client, db, world["legal"])
    uid = client.post("/api/v1/reg/updates", json=nyc_enforcement(world, verify_note=NOTE)).json()["id"]
    assert client.post(f"/api/v1/reg/updates/{uid}/submit").status_code == 200
    login_as(client, db, world["chief"])
    return uid


def test_an_update_with_a_point_to_confirm_is_not_published(client, db, world):
    uid = _awaiting(client, db, world)
    r = client.post(f"/api/v1/reg/updates/{uid}/review", json={"approve": True, "note": "Looks right."})
    assert r.status_code == 409 and "confirm" in r.json()["detail"].lower()
    u = db.get(RegulatoryUpdate, uid)
    db.refresh(u)
    assert u.status == "awaiting_review" and u.published_at is None
    assert db.scalars(select(RegulatoryAlert).where(RegulatoryAlert.update_id == uid)).all() == []


def test_the_reviewer_clears_the_note_when_confirmed_and_it_is_logged(client, db, world):
    uid = _awaiting(client, db, world)
    r = client.post(f"/api/v1/reg/updates/{uid}/review", json={"approve": True, "note": "Report 2024-N-6 confirmed.", "clear_verify_note": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published" and r.json()["verify_note"] is None
    e = db.scalar(select(AuditLog).where(AuditLog.action == "regupdate.verify_note_cleared", AuditLog.object_id == uid))
    assert e is not None and e.before == {"verify_note": NOTE} and e.actor_id == world["chief"].id


def test_the_reviewer_can_send_it_back_instead(client, db, world):
    uid = _awaiting(client, db, world)
    r = client.post(f"/api/v1/reg/updates/{uid}/review", json={"approve": False, "note": "Confirm the report number first."})
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["verify_note"] == NOTE
