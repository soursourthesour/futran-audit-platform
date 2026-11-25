"""BUG-H10: a department_id that is not a string is a validation error (422), not a server error."""
import pytest

from tests.factories import login_as, make_department, make_org, make_user


@pytest.fixture
def cleo(client, db):
    make_org(db, type="futran")
    org = make_org(db, type="client")
    make_department(db, org, name="Finance")
    u = make_user(db, org, roles=["client_admin"], name="Cleo Admin", email="cleo@abc.com")
    db.commit()
    login_as(client, db, u)
    return u


@pytest.mark.parametrize("bad", [{"a": 1}, ["x"], 7, True])
def test_new_group_refuses_a_department_that_is_not_a_string(client, cleo, bad):
    r = client.post("/api/v1/mail/groups", json={"name": "Finance leads", "department_id": bad})
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["field"] == "department_id"


@pytest.mark.parametrize("bad", [{"a": 1}, ["x"], 7])
def test_add_member_refuses_a_department_that_is_not_a_string(client, cleo, bad):
    g = client.post("/api/v1/mail/groups", json={"name": "Finance leads"})
    assert g.status_code == 200, g.text
    r = client.post(f"/api/v1/mail/groups/{g.json()['id']}/members", json={"email": "new.person@abc.com", "department_id": bad})
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["field"] == "department_id"
