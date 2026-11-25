"""People > Users loads every person's roles and latest invitation in a fixed number of queries (load test BUG-V03:
three queries per person, 7 to 11 s at 10,000 people), and shows the same values as before."""
from datetime import timedelta

from sqlalchemy import event, select

from app.core.clock import utcnow
from app.invitations.models import Invitation
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def _user(client, cid, first, email, role="contributor", department="Finance"):
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": first, "last_name": "Staff", "email": email, "job_title": "", "department": department, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _statements(client, engine, cid):
    seen = []

    def on(*_):
        seen.append(1)

    event.listen(engine, "before_cursor_execute", on)
    try:
        r = client.get(f"/api/v1/clients/{cid}/people")
    finally:
        event.remove(engine, "before_cursor_execute", on)
    assert r.status_code == 200, r.text
    return len(seen), {u["email"]: u for u in r.json()["users"]}


def test_people_list_queries_do_not_grow_with_the_number_of_people(client, db, engine, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Finance"})
    for i in range(3):
        _user(client, cid, f"A{i}", f"a{i}@abc.test")
    few, _ = _statements(client, engine, cid)
    for i in range(15):
        _user(client, cid, f"B{i}", f"b{i}@abc.test")
    many, users = _statements(client, engine, cid)
    assert many <= few + 2, (few, many)
    assert users["b3@abc.test"]["department"] == "Finance" and users["b3@abc.test"]["roles"][0]["role"] == "contributor"
    assert users["b3@abc.test"]["roles"][0]["department"] == "Finance"


def test_invitation_status_is_shown_as_before(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Finance"})
    pending = _user(client, cid, "Pat", "pat@abc.test")
    late = _user(client, cid, "Lee", "lee@abc.test")
    off = _user(client, cid, "Off", "off@abc.test")
    db.expire_all()
    for inv in db.scalars(select(Invitation).where(Invitation.user_id == late)):
        inv.expires_at = utcnow() - timedelta(days=1)
    db.get(User, off).status = "disabled"
    db.commit()
    users = {u["email"]: u for u in client.get(f"/api/v1/clients/{cid}/people").json()["users"]}
    assert users["pat@abc.test"]["invite_status"] == "Invitation sent, not yet accepted"
    assert users["lee@abc.test"]["invite_status"] == "Invitation expired"
    assert users["off@abc.test"]["invite_status"] == "Disabled"
    assert users["maria@abc.test"]["invite_status"] == "Active"
    assert pending
