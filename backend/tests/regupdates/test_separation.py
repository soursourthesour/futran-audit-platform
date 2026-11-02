"""Separation of duties on regulatory updates (spec §6 rule 2): only the author edits a draft, and nobody who wrote,
edited or submitted an update reviews it."""
from sqlalchemy import select

from app.regupdates import service as svc
from app.regupdates.models import RegulatoryUpdate
from tests.factories import login_as
from tests.regupdates.conftest import nyc_enforcement


def _draft(client, db, world, who="legal"):
    login_as(client, db, world[who])
    r = client.post("/api/v1/reg/updates", json=nyc_enforcement(world))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_only_the_author_edits_a_draft(client, db, world):
    uid = _draft(client, db, world)
    login_as(client, db, world["legal2"])
    assert client.get(f"/api/v1/reg/updates/{uid}").json()["can_edit"] is False
    r = client.patch(f"/api/v1/reg/updates/{uid}", json={"summary": "Rewritten by Kim", "affected_features": ["employment_hiring"]})
    assert r.status_code == 403
    login_as(client, db, world["legal"])
    assert client.get(f"/api/v1/reg/updates/{uid}").json()["can_edit"] is True
    assert client.patch(f"/api/v1/reg/updates/{uid}", json={"summary": "Clarified by the author"}).status_code == 200


def test_a_reviewer_who_edited_or_submitted_the_update_cannot_publish_it(client, db, world):
    uid = _draft(client, db, world)
    u = db.get(RegulatoryUpdate, uid)
    svc.update(db, world["legal"], u, {"summary": "Edited"})  # the author
    db.commit()
    login_as(client, db, world["legal2"])  # Kim submits Jordan's draft
    assert client.post(f"/api/v1/reg/updates/{uid}/submit").status_code == 200
    assert client.get(f"/api/v1/reg/updates/{uid}").json()["can_review"] is False
    assert client.post(f"/api/v1/reg/updates/{uid}/review", json={"approve": True, "note": "ok"}).status_code == 403
    login_as(client, db, world["chief"])
    r = client.post(f"/api/v1/reg/updates/{uid}/review", json={"approve": True, "note": "Checked."})
    assert r.status_code == 200 and r.json()["status"] == "published"


def test_an_editor_recorded_in_the_audit_log_cannot_review(client, db, world):
    """Even if someone else's edit reached the draft (for example before this rule), the audit log names them."""
    from app.audit_log import service as audit

    uid = _draft(client, db, world)
    u = db.get(RegulatoryUpdate, uid)
    audit.record(db, actor_id=world["legal2"].id, action="regupdate.edit", obj=u, organization_id=world["legal2"].organization_id, summary="Edited")
    db.commit()
    login_as(client, db, world["legal"])
    assert client.post(f"/api/v1/reg/updates/{uid}/submit").status_code == 200
    login_as(client, db, world["legal2"])
    assert client.post(f"/api/v1/reg/updates/{uid}/review", json={"approve": True, "note": "ok"}).status_code == 403
    assert db.scalar(select(RegulatoryUpdate.status).where(RegulatoryUpdate.id == uid)) == "awaiting_review"
