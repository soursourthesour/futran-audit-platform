"""11-03 review, items C2, C3 and C6: job level, department changes in the audit log, a person's change history and the
admin home's role-change grid."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.tenancy.models import User
from tests.factories import login_as, make_org, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def _dept(client, cid, name):
    r = client.post(f"/api/v1/clients/{cid}/departments", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _user(client, cid, first, last, email, role="contributor", department="Finance"):
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": first, "last_name": last, "email": email, "job_title": "", "department": department, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _row(client, cid, uid):
    return next(u for u in client.get(f"/api/v1/clients/{cid}/people").json()["users"] if u["id"] == uid)


def test_job_level_is_shown_and_edited(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    assert _row(client, cid, tom)["job_level"] is None
    r = client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"job_level": "manager"})
    assert r.status_code == 200, r.text
    row = _row(client, cid, tom)
    assert row["job_level"] == "manager" and row["job_level_label"] == "Manager"
    assert client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"job_level": "Department head"}).status_code == 200  # the label works too
    assert _row(client, cid, tom)["job_level"] == "department_head"
    bad = client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"job_level": "boss"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "job_level"
    assert client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"job_level": ""}).status_code == 200
    assert _row(client, cid, tom)["job_level"] is None
    edits = db.scalars(select(AuditLog).where(AuditLog.action == "user.edit", AuditLog.object_id == tom)).all()
    assert any((a.after or {}).get("job_level") == "manager" for a in edits)


def test_department_changes_are_audit_logged_like_role_changes(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    _dept(client, cid, "Legal")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    ana = _user(client, cid, "Ana", "Diaz", "ana@abc.test", role="exec_sponsor", department="Legal")  # an org-wide role with a department
    # the new sponsor's department is kept on her record and recorded
    assert _row(client, cid, ana)["department"] == "Legal"
    set_ana = db.scalars(select(AuditLog).where(AuditLog.action == "user.department_change", AuditLog.object_id == ana)).all()
    assert [(a.before, a.after) for a in set_ana] == [({"department": None}, {"department": "Legal"})]
    # single edit and the bulk change both go through the same edit: one row per person, from and to by name
    assert client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"department": "Legal"}).status_code == 200
    assert client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"department": "Legal"}).status_code == 200  # no change, no row
    moves = db.scalars(select(AuditLog).where(AuditLog.action == "user.department_change", AuditLog.object_id == tom)).all()
    assert [(a.before, a.after) for a in moves][-1] == ({"department": "Finance"}, {"department": "Legal"})
    assert len([a for a in moves if a.before["department"] == "Finance"]) == 1
    assert moves[-1].actor_name == "Maria Lopez" and moves[-1].summary == "Moved Tom Reyes from Finance to Legal"
    assert _row(client, cid, tom)["department"] == "Legal"


def test_history_lists_role_and_department_changes_newest_first(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    _dept(client, cid, "Legal")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"department": "Legal"})
    client.post(f"/api/v1/clients/{cid}/users/{tom}/roles", json={"role": "dpo"})
    r = client.get(f"/api/v1/clients/{cid}/users/{tom}/history")
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["user"]["name"] == "Tom Reyes"
    kinds = [(x["kind"], x["change"]) for x in h["events"]]
    assert kinds[0] == ("role", "Role given") and h["events"][0]["to"] == "Data Protection Officer"
    move = next(x for x in h["events"] if x["kind"] == "department" and x["from"] == "Finance")
    assert move["to"] == "Legal" and move["by"] == "Maria Lopez" and move["at"]
    first = h["events"][-1]
    assert first["kind"] == "role" and first["to"] == "Contributor" and first["department"] == "Finance"
    ats = [x["at"] for x in h["events"]]
    assert ats == sorted(ats, reverse=True)


def test_history_is_scoped_to_the_client(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    other = make_org(db, name="XYZ")
    boss = make_user(db, other, roles=["client_admin"], name="X Admin", email="x@xyz.test")
    db.commit()
    assert client.get(f"/api/v1/clients/{cid}/users/{boss.id}/history").status_code == 404  # not one of this client's people
    login_as(client, db, boss)
    assert client.get(f"/api/v1/clients/{cid}/users/{tom}/history").status_code == 404
    assert client.get(f"/api/v1/clients/{other.id}/users/{tom}/history").status_code == 404


def test_admin_home_lists_changes_as_grid_rows(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    _dept(client, cid, "Legal")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"department": "Legal"})
    rows = client.get("/api/v1/home/client-admin").json()["role_changes"]
    assert rows[0]["kind"] == "department" and rows[0]["user_id"] == tom and rows[0]["name"] == "Tom Reyes"
    assert rows[0]["department"] == "Legal" and rows[0]["from"] == "Finance" and rows[0]["by"] == "Maria Lopez"
    given = next(x for x in rows if x["kind"] == "role" and x["user_id"] == tom)
    assert given["role"] == "Contributor" and given["department"] == "Finance" and given["change"] == "Role given"
    assert all(set(x) >= {"id", "user_id", "name", "role", "department", "change", "by", "at", "summary", "sign_off_role"} for x in rows)
    assert db.get(User, tom).name == "Tom Reyes"
