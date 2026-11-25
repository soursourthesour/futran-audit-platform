"""Y03: a CAICO does not approve and publish a policy they wrote, unless they are the only CAICO (a stand-in, as on
sign-offs), and then the stand-in is in the audit log."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from tests.factories import login_as, make_user
from tests.policies.test_policy_builder import ANSWERS, API, _start

SOD = "You prepared this item, so you cannot approve it. Another approver must sign it off."


def _submitted(client, db, w, author):
    login_as(client, db, author)
    p = _start(client, w)
    client.put(f"{API}/policies/{p['id']}/answers", json={"answers": p["answers"] | ANSWERS, "regenerate": True})
    assert client.post(f"{API}/policies/{p['id']}/submit").json()["status"] == "awaiting_approval"
    return p


def _publish_entry(db, pid):
    db.expire_all()
    return db.scalar(select(AuditLog).where(AuditLog.action == "policy.publish", AuditLog.object_id == pid))


def test_the_author_cannot_approve_when_another_caico_can(client, db, world):
    second = make_user(db, world["org"], roles=["caico"], name="Chloe Second", email="chloe@abc.test")
    db.commit()
    p = _submitted(client, db, world, world["caico"])
    assert client.get(f"{API}/policies/{p['id']}").json()["can"]["approve"] is False
    r = client.post(f"{API}/policies/{p['id']}/approve", json={})
    assert r.status_code == 403 and r.json()["detail"] == SOD
    assert client.get(f"{API}/policies/{p['id']}").json()["status"] == "awaiting_approval"
    login_as(client, db, second)
    r = client.post(f"{API}/policies/{p['id']}/approve", json={})
    assert r.status_code == 200, r.text
    assert (_publish_entry(db, p["id"]).after or {}).get("stand_in") is False


def test_an_editor_who_is_not_the_author_is_also_a_preparer(client, db, world):
    second = make_user(db, world["org"], roles=["caico"], name="Chloe Second", email="chloe@abc.test")
    db.commit()
    p = _submitted(client, db, world, world["admin"])  # the Client Admin wrote and sent it
    from app.policies.models import PolicyDocument

    db.get(PolicyDocument, p["id"]).updated_by = second.id  # the second CAICO edited the text
    db.commit()
    login_as(client, db, second)
    assert client.post(f"{API}/policies/{p['id']}/approve", json={}).status_code == 403
    login_as(client, db, world["caico"])
    assert client.post(f"{API}/policies/{p['id']}/approve", json={}).status_code == 200


def test_the_only_caico_may_approve_their_own_policy_as_a_stand_in(client, db, world):
    p = _submitted(client, db, world, world["caico"])
    r = client.post(f"{API}/policies/{p['id']}/approve", json={})
    assert r.status_code == 200, r.text
    entry = _publish_entry(db, p["id"])
    assert entry.after["stand_in"] is True
    assert "only Chief AI Compliance Officer" in entry.summary
