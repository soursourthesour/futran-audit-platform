"""People > Departments and People > Users: edit, delete and remove from the grids without breaking history."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.invitations.models import Invitation
from app.tenancy.models import Department, User
from app.tenancy.service import roles_of
from tests.factories import login_as, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def _user(client, cid, first, last, email, role="contributor", department="Finance"):
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": first, "last_name": last, "email": email, "job_title": "", "department": department, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _dept(client, cid, name):
    r = client.post(f"/api/v1/clients/{cid}/departments", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_checklist_titles_and_order(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    items = client.get("/api/v1/me/initiation").json()["items"]
    assert [i["title"] for i in items] == [
        "Read the getting started guide", "Sign the engagement letter and scope", "Nominate role holders", "Confirm departments",
        "Add employees", "Review employee AI audit and data notice and kick off audit", "Describe your AI governance structure",
    ]


def test_rename_edit_and_delete_departments(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    fin = _dept(client, cid, "Finance")
    ops = _dept(client, cid, "Operations")
    r = client.patch(f"/api/v1/clients/{cid}/departments/{fin}", json={"name": "Finance and accounts", "head_name": "Fay Ng", "headcount": "12"})
    assert r.status_code == 200, r.text
    d = db.get(Department, fin)
    db.refresh(d)
    assert (d.name, d.head_name, d.headcount) == ("Finance and accounts", "Fay Ng", 12)
    assert client.patch(f"/api/v1/clients/{cid}/departments/{fin}", json={"name": "operations"}).status_code == 409  # duplicate
    assert client.patch(f"/api/v1/clients/{cid}/departments/{fin}", json={"name": " "}).status_code == 422
    # a department with people in it can't be deleted; an empty one can (soft delete, recorded)
    _user(client, cid, "Tom", "Reyes", "tom@abc.test", department="Finance and accounts")
    r = client.delete(f"/api/v1/clients/{cid}/departments/{fin}")
    assert r.status_code == 409 and "Tom Reyes" in r.json()["detail"]
    assert client.delete(f"/api/v1/clients/{cid}/departments/{ops}").status_code == 200
    db.expire_all()
    assert db.get(Department, ops).deleted_at is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "department.delete", AuditLog.object_id == ops)) is not None
    names = [x["name"] for x in client.get(f"/api/v1/clients/{cid}/people").json()["departments"]]
    assert "Operations" not in names


def test_department_delete_is_closed_after_setup(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    ops = _dept(client, cid, "Operations")
    e.stage = 3
    db.commit()
    assert client.delete(f"/api/v1/clients/{cid}/departments/{ops}").status_code == 409


def test_edit_user_details_and_department(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    _dept(client, cid, "Legal")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    r = client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"name": "Thomas Reyes", "job_title": "Analyst", "department": "Legal", "email": "thomas@abc.test"})
    assert r.status_code == 200, r.text
    u = db.get(User, tom)
    db.refresh(u)
    legal = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "Legal"))
    assert (u.name, u.job_title, u.email) == ("Thomas Reyes", "Analyst", "thomas@abc.test")
    assert [(r.role, r.scope_id) for r in roles_of(db, tom)] == [("contributor", legal.id)]
    row = next(x for x in client.get(f"/api/v1/clients/{cid}/people").json()["users"] if x["id"] == tom)
    assert row["department"] == "Legal" and row["name"] == "Thomas Reyes"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "user.edit", AuditLog.object_id == tom)) is not None
    # bad values come back against the field
    r = client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"department": "Nowhere"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "department"
    assert client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"email": "not-an-email"}).status_code == 422
    assert client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"name": ""}).status_code == 422
    # once someone has signed in, their email is theirs to keep
    u.status, u.password_hash = "active", "x"
    db.commit()
    assert client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"email": "t2@abc.test"}).status_code == 409


def test_add_a_role_to_an_existing_user(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    r = client.post(f"/api/v1/clients/{cid}/users/{tom}/roles", json={"role": "dpo"})
    assert r.status_code == 200, r.text
    assert sorted(r.role for r in roles_of(db, tom)) == ["contributor", "dpo"]


def test_remove_user_without_history_is_soft_deleted(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    r = client.delete(f"/api/v1/clients/{cid}/users/{tom}")
    assert r.status_code == 200 and r.json()["result"] == "removed"
    db.expire_all()
    u = db.get(User, tom)
    assert u.deleted_at is not None and roles_of(db, tom) == []
    assert db.scalar(select(Invitation).where(Invitation.user_id == tom, Invitation.status == "pending")) is None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "user.remove", AuditLog.object_id == tom)) is not None
    assert tom not in [x["id"] for x in client.get(f"/api/v1/clients/{cid}/people").json()["users"]]


def test_remove_user_with_history_is_deactivated_not_deleted(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    u = db.get(User, tom)
    u.status = "active"
    db.commit()
    login_as(client, db, u)
    client.get("/api/v1/me/initiation")
    from app.audit_log import service as audit

    audit.record(db, actor_id=tom, action="usecase.create", organization_id=cid, summary="Added a use case")  # Tom authored a record
    db.commit()
    login_as(client, db, maria)
    r = client.delete(f"/api/v1/clients/{cid}/users/{tom}")
    assert r.status_code == 200 and r.json()["result"] == "deactivated"
    db.expire_all()
    u = db.get(User, tom)
    assert u.deleted_at is None and u.status == "disabled"
    row = next(x for x in client.get(f"/api/v1/clients/{cid}/people").json()["users"] if x["id"] == tom)
    assert row["invite_status"] == "Disabled"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "user.deactivate", AuditLog.object_id == tom)) is not None


def test_signer_of_a_sign_off_is_never_deleted(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _user(client, cid, "Sam", "Admin", "sam@abc.test", role="caico", department="")  # a second CAICO, so Maria's role may go
    login_as(client, db, maria)
    r = client.delete(f"/api/v1/clients/{cid}/users/{maria.id}")
    assert r.status_code == 409  # not yourself
    sam = db.scalar(select(User).where(User.email == "sam@abc.test"))
    sam.status = "active"
    db.commit()
    login_as(client, db, sam)
    r = client.delete(f"/api/v1/clients/{cid}/users/{maria.id}")
    assert r.status_code == 200 and r.json()["result"] == "deactivated"  # Maria signed sign-off 1
    db.expire_all()
    assert db.get(User, maria.id).deleted_at is None


def test_last_caico_cannot_be_removed(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    sam = _user(client, cid, "Sam", "Admin", "sam@abc.test", role="client_admin", department="")
    u = db.get(User, sam)
    u.status = "active"
    db.commit()
    login_as(client, db, u)
    r = client.delete(f"/api/v1/clients/{cid}/users/{maria.id}")
    assert r.status_code == 409 and "Chief AI Compliance Officer" in r.json()["detail"]


def test_dept_lead_cannot_edit_or_remove_people(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    lead = _user(client, cid, "Fay", "Ng", "fay@abc.test", role="dept_compliance_lead")
    tom = _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    fay = db.get(User, lead)
    fay.status = "active"
    db.commit()
    login_as(client, db, fay)
    page = client.get(f"/api/v1/clients/{cid}/people").json()
    assert page["can_manage"] is False and {u["id"] for u in page["users"]} == {lead, tom}
    assert client.patch(f"/api/v1/clients/{cid}/users/{tom}", json={"job_title": "x"}).status_code == 403
    assert client.delete(f"/api/v1/clients/{cid}/users/{tom}").status_code == 403
    fin = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "Finance"))
    assert client.delete(f"/api/v1/clients/{cid}/departments/{fin.id}").status_code == 403


def test_other_client_cannot_touch_users(client, db, people, live):
    from tests.factories import make_org

    cid, e, maria = live
    other = make_org(db, name="XYZ")
    boss = make_user(db, other, roles=["client_admin"], name="X Admin", email="x@xyz.test")
    db.commit()
    login_as(client, db, boss)
    assert client.patch(f"/api/v1/clients/{cid}/users/{maria.id}", json={"job_title": "x"}).status_code == 404
    assert client.delete(f"/api/v1/clients/{cid}/users/{maria.id}").status_code == 404


def test_user_csv_template(client, db, people, live):
    import csv
    import io

    cid, e, maria = live
    login_as(client, db, maria)
    r = client.get(f"/api/v1/clients/{cid}/users/template.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["first_name", "last_name", "email", "job_title", "department", "role", "location"]
