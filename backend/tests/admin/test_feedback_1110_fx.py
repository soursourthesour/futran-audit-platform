"""Feedback of 10 November, F1: Futran staff departments and the read-only Client users view."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.policy.actions import Action as A
from app.policy.matrix import MATRIX, Scope as S
from app.policy.roles import Role as R
from tests.factories import login_as, make_department, make_org, make_user


def _world(db):
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@futran.test")
    chief = make_user(db, f, roles=["chief_auditor"], name="Cleo Chief", email="chief@futran.test")
    aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    abc = make_org(db, name="ABC Corp")
    hr = make_department(db, abc, name="Human Resources")
    caico = make_user(db, abc, roles=["caico"], name="Casey Caico", email="casey@abc.test", job_title="Chief AI officer")
    lead = make_user(db, abc, roles=[("dept_compliance_lead", "department", hr.id)], name="Lee Lead", email="lee@abc.test", department_id=hr.id)
    xyz = make_org(db, name="XYZ Ltd")
    zed = make_user(db, xyz, roles=["contributor"], name="Zed Contributor", email="zed@xyz.test", status="invited")
    db.commit()
    return {"futran": f, "admin": admin, "chief": chief, "aud": aud, "abc": abc, "hr": hr, "caico": caico, "lead": lead, "xyz": xyz, "zed": zed}


# ---- (a) Futran staff departments

def test_admin_manages_futran_departments_and_each_change_is_audit_logged(client, db):
    w = _world(db)
    login_as(client, db, w["admin"])
    r = client.post("/api/v1/admin/departments", json={"name": "Audit delivery"})
    assert r.status_code == 200, r.text
    dept = r.json()
    assert dept["name"] == "Audit delivery" and dept["people"] == 0
    assert client.post("/api/v1/admin/departments", json={"name": "audit delivery"}).status_code == 409
    assert client.post("/api/v1/admin/departments", json={"name": "  "}).status_code == 422
    r = client.patch(f"/api/v1/admin/departments/{dept['id']}", json={"name": "Audit practice"})
    assert r.status_code == 200 and r.json()["name"] == "Audit practice"
    listed = client.get("/api/v1/admin/departments").json()
    assert [d["name"] for d in listed] == ["Audit practice"]
    # Futran's departments never include a client's
    assert "Human Resources" not in {d["name"] for d in listed}
    assert client.delete(f"/api/v1/admin/departments/{dept['id']}").status_code == 200
    assert client.get("/api/v1/admin/departments").json() == []
    db.expire_all()
    acts = set(db.scalars(select(AuditLog.action).where(AuditLog.organization_id == w["futran"].id)))
    assert {"department.create", "department.update", "department.delete"} <= acts


def test_futran_user_gets_a_department_on_add_and_edit(client, db):
    w = _world(db)
    login_as(client, db, w["admin"])
    ops = client.post("/api/v1/admin/departments", json={"name": "Operations"}).json()
    sales = client.post("/api/v1/admin/departments", json={"name": "Sales"}).json()
    r = client.post("/api/v1/admin/users", json={"name": "Quinn Reviewer", "email": "quinn@futran.test", "roles": ["qa_reviewer"], "department_id": ops["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["department_id"] == ops["id"] and r.json()["department"] == "Operations"
    uid = r.json()["id"]
    r = client.patch(f"/api/v1/admin/users/{uid}", json={"department_id": sales["id"]})
    assert r.status_code == 200 and r.json()["department"] == "Sales"
    db.expire_all()
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "user.update", AuditLog.object_id == uid)).all()[-1]
    assert entry.before["department_id"] == ops["id"] and entry.after["department_id"] == sales["id"]
    # clearing it
    r = client.patch(f"/api/v1/admin/users/{uid}", json={"department_id": None})
    assert r.status_code == 200 and r.json()["department"] is None
    # a client's department cannot be given to a Futran user
    r = client.patch(f"/api/v1/admin/users/{uid}", json={"department_id": w["hr"].id})
    assert r.status_code == 422
    rows = {u["email"]: u for u in client.get("/api/v1/admin/users").json()}
    assert rows["quinn@futran.test"]["department"] is None and "department" in rows["admin@futran.test"]
    # a department still holding people cannot be removed
    client.patch(f"/api/v1/admin/users/{uid}", json={"department_id": ops["id"]})
    assert client.delete(f"/api/v1/admin/departments/{ops['id']}").status_code == 409
    assert next(d for d in client.get("/api/v1/admin/departments").json() if d["id"] == ops["id"])["people"] == 1


def test_only_the_futran_admin_changes_futran_departments(client, db):
    w = _world(db)
    login_as(client, db, w["chief"])
    assert client.get("/api/v1/admin/departments").status_code == 200  # the Chief Auditor reads Futran users
    assert client.post("/api/v1/admin/departments", json={"name": "Nope"}).status_code == 403
    login_as(client, db, w["aud"])
    assert client.post("/api/v1/admin/departments", json={"name": "Nope"}).status_code == 403


def test_no_client_user_sees_futran_departments(client, db):
    w = _world(db)
    login_as(client, db, w["admin"])
    d = client.post("/api/v1/admin/departments", json={"name": "Audit delivery"}).json()
    for who in ("caico", "lead"):
        login_as(client, db, w[who])
        assert client.get("/api/v1/admin/departments").status_code in (403, 404)
        assert client.post("/api/v1/admin/departments", json={"name": "X"}).status_code in (403, 404)
        assert client.patch(f"/api/v1/admin/departments/{d['id']}", json={"name": "X"}).status_code in (403, 404)
        assert client.delete(f"/api/v1/admin/departments/{d['id']}").status_code in (403, 404)
    # and the client's own department routes cannot reach a Futran department
    login_as(client, db, w["caico"])
    assert client.patch(f"/api/v1/clients/{w['abc'].id}/departments/{d['id']}", json={"name": "X"}).status_code == 404


# ---- (b) Administration > Client users

def test_matrix_grants_client_users_view_to_admin_and_chief_only():
    for role in R:
        expected = S.ALL if role in (R.ADMIN, R.CHIEF_AUDITOR) else S.NONE
        assert MATRIX.get(role, {}).get(A.VIEW_ALL_CLIENT_USERS, S.NONE) == expected, role


def test_client_users_lists_every_client_with_department_roles_and_status(client, db):
    w = _world(db)
    login_as(client, db, w["admin"])
    r = client.get("/api/v1/admin/client-users")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {u["email"]: u for u in body["users"]}
    assert set(rows) == {"casey@abc.test", "lee@abc.test", "zed@xyz.test"}  # no Futran staff
    lee = rows["lee@abc.test"]
    assert lee["client"] == "ABC Corp" and lee["client_id"] == w["abc"].id and lee["department"] == "Human Resources"
    assert lee["roles"] == ["Department Compliance Lead"] and lee["role_keys"] == ["dept_compliance_lead"]
    assert rows["casey@abc.test"]["job_title"] == "Chief AI officer"
    assert rows["zed@xyz.test"]["status"] == "invited"
    assert {c["name"] for c in body["clients"]} == {"ABC Corp", "XYZ Ltd"}
    assert "Human Resources" in {d for d in body["departments"]}
    # read-only: no write route exists under the view
    assert client.post("/api/v1/admin/client-users", json={}).status_code in (404, 405)
    assert client.patch(f"/api/v1/admin/client-users/{w['lead'].id}", json={"status": "disabled"}).status_code in (404, 405)


def test_client_users_view_is_audit_logged_each_time(client, db):
    w = _world(db)
    login_as(client, db, w["chief"])
    assert client.get("/api/v1/admin/client-users").status_code == 200
    assert client.get("/api/v1/admin/client-users").status_code == 200
    db.expire_all()
    views = db.scalars(select(AuditLog).where(AuditLog.action == "client_users.view")).all()
    assert len(views) == 2 and all(v.actor_id == w["chief"].id and v.organization_id == w["futran"].id for v in views)


def test_client_users_view_refuses_other_futran_roles_and_every_client(client, db):
    w = _world(db)
    login_as(client, db, w["aud"])
    assert client.get("/api/v1/admin/client-users").status_code == 403
    for who in ("caico", "lead"):
        login_as(client, db, w[who])
        assert client.get("/api/v1/admin/client-users").status_code in (403, 404)


def test_me_lists_the_new_action_for_admin_only(client, db):
    w = _world(db)
    login_as(client, db, w["admin"])
    assert "view_all_client_users" in client.get("/api/v1/auth/me").json()["actions"]
    login_as(client, db, w["aud"])
    assert "view_all_client_users" not in client.get("/api/v1/auth/me").json()["actions"]
