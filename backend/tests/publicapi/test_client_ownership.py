"""API client ownership: a Client Admin can hand a client to another Client Admin of the same organization, and API writes
stop when the owner is no longer an active Client Admin (the writes are recorded as the owner's)."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.publicapi.models import ApiClient
from app.tenancy.models import RoleAssignment
from tests.comments.conftest import w  # noqa: F401
from tests.factories import make_user
from tests.publicapi.test_publicapi import API, PUB, bearer, make_client, token

NEW_SYSTEM = {"name": "Claims triage assistant", "type": "genai_chat_tool", "sourcing": "vendor", "purpose": "Drafts replies to routine claims questions.",
              "vendor_name": "Acme AI"}


def _second_admin(db, w):
    u = make_user(db, w.org, roles=["client_admin"], name="Lee Park", email="lee@abc.test")
    db.commit()
    return u


def _drop_client_admin(db, user):
    for ra in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == user.id, RoleAssignment.role == "client_admin")):
        db.delete(ra)
    db.commit()


def test_writes_stop_when_the_owner_is_no_longer_a_client_admin(client, db, w):
    creds = make_client(client, w)
    t = token(client, creds)
    _drop_client_admin(db, w.cadmin)  # still an active user, now a CAICO-less ordinary account
    r = client.post(f"{PUB}/inventory/systems", headers=bearer(t), json=NEW_SYSTEM | {"department_id": w.fin.id})
    assert r.status_code == 409, r.text
    assert "transfer" in r.json()["detail"].lower()
    assert client.get(f"{PUB}/inventory/systems", headers=bearer(t)).status_code == 200  # reads still work


def test_a_client_admin_transfers_a_client_to_another_client_admin(client, db, w):
    lee = _second_admin(db, w)
    creds = make_client(client, w)
    cid = creds["client"]["id"]
    listing = client.get(f"{API}/admin/api").json()
    assert {"id": lee.id, "name": "Lee Park"} in listing["client_admins"]
    r = client.post(f"{API}/admin/api/clients/{cid}/transfer", json={"owner_id": lee.id})
    assert r.status_code == 200, r.text
    assert r.json()["owner"] == "Lee Park" and r.json()["owner_is_client_admin"] is True
    assert db.get(ApiClient, cid).owner_id == lee.id
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "api_client.transferred"))
    assert entry is not None and entry.actor_id == w.cadmin.id and "Lee Park" in entry.summary

    _drop_client_admin(db, w.cadmin)  # the old owner losing the role no longer matters
    t = token(client, creds)
    assert client.post(f"{PUB}/inventory/systems", headers=bearer(t), json=NEW_SYSTEM | {"department_id": w.fin.id}).status_code == 200


def test_a_client_can_go_only_to_an_active_client_admin_of_the_same_organization(client, db, w):
    creds = make_client(client, w)
    cid = creds["client"]["id"]
    for target in (w.caico.id, w.x_admin.id, "no-such-user"):
        r = client.post(f"{API}/admin/api/clients/{cid}/transfer", json={"owner_id": target})
        assert r.status_code == 422, (target, r.text)
    assert db.get(ApiClient, cid).owner_id == w.cadmin.id
    w.as_(w.caico)  # the CAICO may look, not transfer
    assert client.post(f"{API}/admin/api/clients/{cid}/transfer", json={"owner_id": w.caico.id}).status_code == 403
    w.as_(w.x_admin)  # another tenant's admin cannot see it
    assert client.post(f"{API}/admin/api/clients/{cid}/transfer", json={"owner_id": w.x_admin.id}).status_code == 404


def test_the_admin_screen_flags_a_client_whose_owner_lost_the_role(client, db, w):
    lee = _second_admin(db, w)
    make_client(client, w, user=lee)
    _drop_client_admin(db, lee)
    w.as_(w.cadmin)
    row = client.get(f"{API}/admin/api").json()["clients"][0]
    assert row["owner"] == "Lee Park" and row["owner_is_client_admin"] is False
