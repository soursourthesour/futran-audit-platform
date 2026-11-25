"""BUG-H01: an administrator cannot change the roles on their own account (spec §6 rule 1)."""
from app.tenancy.service import roles_of
from tests.factories import login_as, make_org, make_user


def _futran(db):
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@futran.test")
    admin2 = make_user(db, f, roles=["admin"], name="Bea Admin", email="bea@futran.test")
    aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    db.commit()
    return f, admin, admin2, aud


def _roles(db, u):
    db.expire_all()
    return sorted({r.role for r in roles_of(db, u.id)})


def test_admin_cannot_add_a_judgment_role_to_own_account(client, db):
    _, admin, _, _ = _futran(db)
    login_as(client, db, admin)
    for extra in ("chief_auditor", "auditor", "qa_reviewer"):
        r = client.patch(f"/api/v1/admin/users/{admin.id}", json={"roles": ["admin", extra]})
        assert r.status_code == 409, r.text
        assert "Another administrator" in r.json()["detail"]
    assert _roles(db, admin) == ["admin"]


def test_admin_cannot_add_any_role_to_own_account(client, db):
    _, admin, _, _ = _futran(db)
    login_as(client, db, admin)
    r = client.patch(f"/api/v1/admin/users/{admin.id}", json={"roles": ["admin", "sales_team"]})
    assert r.status_code == 409, r.text
    assert _roles(db, admin) == ["admin"]


def test_admin_cannot_drop_own_extra_role_either(client, db):
    f = make_org(db, type="futran")
    both = make_user(db, f, roles=["admin", "chief_auditor"], name="Bo Both", email="bo@futran.test")
    db.commit()
    login_as(client, db, both)
    r = client.patch(f"/api/v1/admin/users/{both.id}", json={"roles": ["admin"]})
    assert r.status_code == 409, r.text
    assert _roles(db, both) == ["admin", "chief_auditor"]


def test_removing_own_admin_role_keeps_its_own_message(client, db):
    _, admin, _, _ = _futran(db)
    login_as(client, db, admin)
    r = client.patch(f"/api/v1/admin/users/{admin.id}", json={"roles": ["auditor"]})
    assert r.status_code == 409
    assert r.json()["detail"] == "You cannot remove your own Admin role."


def test_resending_own_unchanged_roles_with_other_edits_is_allowed(client, db):
    _, admin, _, _ = _futran(db)
    login_as(client, db, admin)
    r = client.patch(f"/api/v1/admin/users/{admin.id}", json={"roles": ["admin"], "job_title": "Platform lead"})
    assert r.status_code == 200, r.text
    assert r.json()["job_title"] == "Platform lead" and r.json()["roles"] == ["admin"]


def test_another_admin_can_still_change_roles(client, db):
    _, admin, admin2, aud = _futran(db)
    login_as(client, db, admin2)
    r = client.patch(f"/api/v1/admin/users/{admin.id}", json={"roles": ["admin", "chief_auditor"]})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/v1/admin/users/{aud.id}", json={"roles": ["auditor", "qa_reviewer"]})
    assert r.status_code == 200, r.text
    assert _roles(db, admin) == ["admin", "chief_auditor"]
