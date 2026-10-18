"""Sign-offs 2–4 (spec §8, schematic §8a), management representation and the inventory snapshot (Task 27)."""
import re

import pytest
from sqlalchemy import select

from app.engagements.models import Engagement
from app.inventory.models import NamedUser
from app.inventory.snapshot import InventorySnapshot, SnapshotAddendum
from app.mail.models import OutboxMessage
from app.signoffs.models import SignOff
from app.tenancy.models import RoleAssignment, User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import _uc, inv  # noqa: F401


@pytest.fixture
def rev(db, inv):
    """ABC Corp in discovery (stage 3), where the client review sign-offs open."""
    db.get(Engagement, inv[1].id).stage = 3
    db.commit()
    return inv


def _u(db, email):
    return db.scalar(select(User).where(User.email == email))


def _submit(client, cid, number, scope=None):
    return client.post(f"/api/v1/clients/{cid}/signoffs/{number}/submit", json={"scope_ref": scope} if scope else {})


def _sign(client, so_id, user):
    return client.post(f"/api/v1/signoffs/{so_id}/sign", json={"typed_name": user.name})


def _approved_dept(client, db, cid, hr, copilot):
    """Tom adds a Tier 1 use case, Priya approves it, Tom submits sign-off 2 and Priya signs."""
    tom, priya = _u(db, "tom@abc.test"), _u(db, "priya@abc.test")
    login_as(client, db, tom)
    uc = _uc(client, cid, hr, [copilot["id"]], name="Meeting notes")
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    login_as(client, db, priya)
    assert client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": True}).status_code == 200
    login_as(client, db, tom)
    so = _submit(client, cid, 2, hr.id).json()
    login_as(client, db, priya)
    assert _sign(client, so["id"], priya).status_code == 200
    return so


def test_signoff2_per_department_preconditions(client, db, rev):
    cid, e, maria, hr, copilot, chatgpt = rev
    tom, priya = _u(db, "tom@abc.test"), _u(db, "priya@abc.test")
    login_as(client, db, tom)
    uc = _uc(client, cid, hr, [chatgpt["id"]], name="Drafting", named_users=[{"person_name": "Lee Park", "email": "lee@abc.test"}])
    assert client.post(f"/api/v1/use-cases/{uc['id']}/submit").status_code == 200
    r = _submit(client, cid, 2, hr.id)
    assert r.status_code == 409 and any("Drafting" in m["message"] for m in r.json()["errors"]), r.text
    login_as(client, db, priya)
    client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": True})
    login_as(client, db, tom)
    r = _submit(client, cid, 2, hr.id)
    assert r.status_code == 409 and any("Lee Park" in m["message"] for m in r.json()["errors"])
    lee = db.scalar(select(NamedUser).where(NamedUser.person_name == "Lee Park"))
    assert client.post(f"/api/v1/named-users/{lee.id}/unable", json={"reason": "x"}).status_code == 403  # the Department Lead decides
    login_as(client, db, priya)
    assert client.post(f"/api/v1/named-users/{lee.id}/unable", json={"reason": ""}).status_code == 422
    assert client.post(f"/api/v1/named-users/{lee.id}/unable", json={"reason": "Left the company in September."}).status_code == 200
    login_as(client, db, tom)
    so = _submit(client, cid, 2, hr.id)
    assert so.status_code == 200, so.text
    so = so.json()
    assert so["status"] == "in_review" and [p["role"] for p in so["parties"]] == ["dept_compliance_lead"]
    assert _sign(client, so["id"], tom).status_code == 403  # the preparer
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "notification", OutboxMessage.to == ["priya@abc.test"])) is not None
    login_as(client, db, priya)
    assert _sign(client, so["id"], priya).json()["status"] == "approved"


def test_dpo_not_appointed_falls_back_to_caico(client, db, rev, settings):
    cid, e, maria, hr, copilot, chatgpt = rev
    _approved_dept(client, db, cid, hr, copilot)
    priya = _u(db, "priya@abc.test")
    login_as(client, db, priya)
    so = _submit(client, cid, 3).json()
    assert [p["role"] for p in so["parties"]] == ["caico"]  # DPO not appointed: the CAICO reviews and approves
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Dee", "last_name": "Po", "email": "dee@abc.test", "role": "dpo"})
    dee = _u(db, "dee@abc.test")
    dee.status = "active"
    db.commit()
    login_as(client, db, priya)
    db.get(SignOff, so["id"]).status = "returned"
    db.commit()
    so2 = _submit(client, cid, 3).json()
    assert [p["role"] for p in so2["parties"]] == ["dpo", "caico"] and so2["version"] == 2


def test_preparer_cannot_approve_signoff3(client, db, rev):
    cid, e, maria, hr, copilot, chatgpt = rev
    _approved_dept(client, db, cid, hr, copilot)
    priya = _u(db, "priya@abc.test")
    db.add(RoleAssignment(organization_id=cid, user_id=priya.id, role="caico", scope_type="org"))
    db.commit()
    login_as(client, db, priya)
    so = _submit(client, cid, 3).json()
    assert _sign(client, so["id"], priya).status_code == 403
    login_as(client, db, maria)
    assert _sign(client, so["id"], maria).json()["status"] == "approved"


def _through_signoff3(client, db, cid, hr, copilot, maria):
    _approved_dept(client, db, cid, hr, copilot)
    login_as(client, db, _u(db, "priya@abc.test"))
    so3 = _submit(client, cid, 3).json()
    login_as(client, db, maria)
    _sign(client, so3["id"], maria)


def test_signoff4_locks_snapshot(client, db, rev):
    cid, e, maria, hr, copilot, chatgpt = rev
    login_as(client, db, maria)
    assert _submit(client, cid, 4).status_code == 409  # sign-off 3 first
    _through_signoff3(client, db, cid, hr, copilot, maria)
    login_as(client, db, maria)
    review = client.get(f"/api/v1/clients/{cid}/review").json()
    assert "complete and accurate" in review["representation"] and "ABC Corp" in review["representation"]
    so4 = _submit(client, cid, 4).json()
    assert [p["role"] for p in so4["parties"]] == ["caico"]  # no DPO, no Sponsor: the CAICO signs
    assert _sign(client, so4["id"], maria).json()["status"] == "approved"
    db.expire_all()
    snap = db.scalar(select(InventorySnapshot).where(InventorySnapshot.engagement_id == e.id))
    assert snap.version == 1 and snap.sign_off_id == so4["id"] and snap.locked_at is not None
    assert [u["name"] for u in snap.payload["use_cases"]] == ["Meeting notes"] and {t["product"] for t in snap.payload["tools"]} >= {"Copilot"}
    assert "systems" in snap.payload and "responses" in snap.payload
    assert db.get(Engagement, e.id).client_answers_locked_at is not None
    assert client.get(f"/api/v1/clients/{cid}/review").json()["snapshot"]["version"] == 1


def test_signed_item_edit_creates_version(client, db, rev):
    cid, e, maria, hr, copilot, chatgpt = rev
    so = _approved_dept(client, db, cid, hr, copilot)
    login_as(client, db, _u(db, "priya@abc.test"))  # the only HR lead cannot reopen it: she would have to sign her own correction
    assert client.post(f"/api/v1/signoffs/{so['id']}/correct", json={"reason": "A use case was left out."}).status_code == 409
    login_as(client, db, _u(db, "tom@abc.test"))
    assert client.post(f"/api/v1/signoffs/{so['id']}/correct", json={"reason": ""}).status_code == 422
    r = client.post(f"/api/v1/signoffs/{so['id']}/correct", json={"reason": "A use case was left out."})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["status"] == "in_review"
    db.expire_all()
    old = db.get(SignOff, so["id"])
    assert old.status == "approved"
    new = db.get(SignOff, r.json()["id"])
    assert new.supersedes_id == old.id and new.correction_reason == "A use case was left out."


def test_late_confirmation_becomes_addendum(client, db, rev, settings):
    cid, e, maria, hr, copilot, chatgpt = rev
    tom = _u(db, "tom@abc.test")
    login_as(client, db, tom)
    uc = _uc(client, cid, hr, [chatgpt["id"]], name="Drafting", named_users=[{"person_name": "Lee Park", "email": "lee@abc.test"}])
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "named_user_confirm").order_by(OutboxMessage.created_at.desc()))
    token = re.search(r"/confirm/([A-Za-z0-9_\-]+)", msg.body_text).group(1)
    login_as(client, db, _u(db, "priya@abc.test"))
    client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": True})
    lee = db.scalar(select(NamedUser).where(NamedUser.person_name == "Lee Park"))
    client.post(f"/api/v1/named-users/{lee.id}/unable", json={"reason": "On leave until December."})
    login_as(client, db, tom)
    so2 = _submit(client, cid, 2, hr.id).json()
    login_as(client, db, _u(db, "priya@abc.test"))
    _sign(client, so2["id"], _u(db, "priya@abc.test"))
    so3 = _submit(client, cid, 3).json()
    login_as(client, db, maria)
    _sign(client, so3["id"], maria)
    so4 = _submit(client, cid, 4).json()
    _sign(client, so4["id"], maria)
    snap = db.scalar(select(InventorySnapshot).where(InventorySnapshot.engagement_id == e.id))
    before = dict(snap.payload)
    client.cookies.clear()
    r = client.post(f"/api/v1/public/confirm/{token}", json={"training_complete": True, "policy_acknowledged": True, "oversight_role_confirmed": True})
    assert r.status_code == 200
    db.expire_all()
    add = db.scalars(select(SnapshotAddendum).where(SnapshotAddendum.snapshot_id == snap.id)).all()
    assert len(add) == 1 and add[0].kind == "named_user_confirmation" and add[0].payload["person_name"] == "Lee Park"
    assert db.get(InventorySnapshot, snap.id).payload == before
