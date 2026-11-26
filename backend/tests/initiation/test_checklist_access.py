"""Y02: the Getting started checklist (screen 10) is worked by the CAICO and the Client Admin, the holders of
VIEW_INITIATION_CHECKLIST. Other client roles still see the engagement but not the checklist."""
import pytest

from tests.factories import login_as, make_department, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def _person(db, cid, role, email):
    from app.tenancy.models import Organization

    org = db.get(Organization, cid)
    if role in ("dept_compliance_lead", "contributor"):
        d = make_department(db, org, name=f"Dept {role}")
        u = make_user(db, org, roles=[(role, "department", d.id)], name=f"Test {role}", email=email, department_id=d.id)
    else:
        u = make_user(db, org, roles=[role], name=f"Test {role}", email=email)
    u.status = "active"
    db.commit()
    return u


@pytest.mark.parametrize("role", ["caico", "client_admin"])
def test_the_checklist_holders_work_it(client, db, live, role):
    cid, e, maria = live
    login_as(client, db, _person(db, cid, role, f"{role}@abc.test"))
    assert client.get("/api/v1/me/initiation").status_code == 200
    assert client.post("/api/v1/me/initiation/items/guide/done").status_code == 200


@pytest.mark.parametrize("role", ["exec_sponsor", "dpo", "dept_compliance_lead", "contributor"])
def test_other_client_roles_see_the_engagement_but_not_the_checklist(client, db, live, role):
    cid, e, maria = live
    login_as(client, db, _person(db, cid, role, f"{role}@abc.test"))
    assert client.get("/api/v1/me/stages").status_code == 200  # VIEW_ENGAGEMENT still holds
    for r in (client.get("/api/v1/me/initiation"), client.post("/api/v1/me/initiation/items/guide/done")):
        assert r.status_code == 403 and r.json()["detail"] == "You do not have permission to do this."
