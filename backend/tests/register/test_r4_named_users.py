"""Named users: only active people, and the count recalculated only when the selection changes (review R4)."""


from tests.factories import make_user
from tests.register.conftest import new_system


def test_disabled_people_cannot_be_named_users(client, db, reg):
    u = make_user(db, reg.org, roles=[], name="Gone Person", email="gone@abc.test", department_id=reg.hr.id)
    u.status = "disabled"
    db.commit()
    reg.as_(reg.caico)
    r = client.post("/api/v1/register", json={"name": "X", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.hr.id, "users_scope": "named",
                                              "user_selection": {"user_ids": [u.id, reg.hr_user.id]}})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "user_selection"


def test_a_person_disabled_later_does_not_log_a_count_change_on_an_unrelated_save(client, db, reg):
    u = make_user(db, reg.org, roles=[], name="Later Gone", email="later@abc.test", department_id=reg.hr.id)
    db.commit()
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, users_scope="named", user_selection={"user_ids": [u.id, reg.hr_user.id]})
    assert s["user_count"] == 2
    u.status = "disabled"
    db.commit()
    r = client.patch(f"/api/v1/register/{s['id']}", json={"purpose": "Something else."})
    assert r.status_code == 200 and r.json()["user_count"] == 2
    fields = [c["field"] for c in client.get(f"/api/v1/register/{s['id']}/changes").json()]
    assert "user_count" not in fields


def test_switching_to_role_level_ignores_a_stale_named_selection(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, users_scope="named", user_selection={"user_ids": [reg.hr_user.id]})
    r = client.patch(f"/api/v1/register/{s['id']}", json={"users_scope": "role", "user_count": 40})
    assert r.status_code == 200, r.text
    assert r.json()["user_count"] == 40
    assert not (r.json()["user_selection"] or {}).get("user_ids")


def test_named_selection_is_kept_only_for_named_users(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, users_scope="role", user_selection={"user_ids": [reg.hr_user.id], "compliance_roles": ["caico"]})
    assert not (s["user_selection"] or {}).get("user_ids")
