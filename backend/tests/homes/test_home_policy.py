"""WS-F (spec §13.1): each role lands on its own home, the navigation is driven by the permission matrix, and a role
cannot load another role's home data."""
import pytest

from tests.factories import login_as, make_department, make_org, make_user

FUTRAN_HOMES = {
    "chief_auditor": "/audits",
    "admin": "/staff/admin",
    "auditor": "/my-work",
    "qa_reviewer": "/qa",
    "engagement_manager": "/my-work",
    "legal_reviewer": "/my-work",
    "sales_team": "/opportunities",
}
CLIENT_HOMES = {
    "caico": "/start",
    "client_admin": "/admin/home",
    "exec_sponsor": "/summary",
    "dpo": "/data-review",
    "dept_compliance_lead": "/my-department",
    "contributor": "/my-tasks",
}
# home data endpoint -> the only roles that may load it
HOME_ENDPOINTS = {
    "/home/admin": {"admin"},
    "/home/my-work": {"auditor", "engagement_manager", "legal_reviewer"},
    "/home/qa": {"qa_reviewer"},
    "/home/client-admin": {"client_admin"},
    "/home/sponsor": {"exec_sponsor"},
    "/home/dpo": {"dpo"},
    "/home/department": {"dept_compliance_lead"},
    "/home/my-tasks": {"contributor"},
}


@pytest.fixture
def orgs(db):
    f = make_org(db, type="futran")
    c = make_org(db, name="ABC Corp")
    hr = make_department(db, c, name="Human Resources")
    db.commit()
    return f, c, hr


def _user(db, orgs, role, n=0):
    f, c, hr = orgs
    if role in FUTRAN_HOMES:
        return make_user(db, f, roles=[role], name=f"F {role} {n}", email=f"{role}{n}@futran.test")
    spec = (role, "department", hr.id) if role in ("dept_compliance_lead", "contributor") else role
    return make_user(db, c, roles=[spec], name=f"C {role} {n}", email=f"{role}{n}@abc.test", department_id=hr.id if role in ("dept_compliance_lead", "contributor") else None)


@pytest.mark.parametrize("role,home", sorted({**FUTRAN_HOMES, **CLIENT_HOMES}.items()))
def test_me_names_the_role_home(client, db, orgs, role, home):
    login_as(client, db, _user(db, orgs, role))
    me = client.get("/api/v1/auth/me").json()
    assert me["home"] == home


def test_me_lists_the_actions_the_matrix_grants(client, db, orgs):
    from app.policy.matrix import MATRIX
    from app.policy.roles import Role

    login_as(client, db, _user(db, orgs, "sales_team"))
    acts = set(client.get("/api/v1/auth/me").json()["actions"])
    assert acts == {str(a) for a in MATRIX[Role.SALES_TEAM]}
    assert "view_engagement" not in acts and "view_opportunities" in acts


@pytest.mark.parametrize("roles,home", [
    (["caico", "client_admin"], "/start"),  # the CAICO with Client Admin powers (how the user tests)
    (["client_admin", "dept_compliance_lead"], "/admin/home"),
    (["exec_sponsor", "dpo"], "/summary"),
    (["dpo", "client_admin"], "/data-review"),
    (["dept_compliance_lead", "contributor"], "/my-department"),
])
def test_several_client_roles_land_on_the_higher_authority_home(client, db, orgs, roles, home):
    _, c, hr = orgs
    specs = [(r, "department", hr.id) if r in ("dept_compliance_lead", "contributor") else r for r in roles]
    u = make_user(db, c, roles=specs, name="Multi Role", email="multi@abc.test", department_id=hr.id)
    login_as(client, db, u)
    me = client.get("/api/v1/auth/me").json()
    assert me["home"] == home


def test_several_roles_see_the_union_of_their_modules(client, db, orgs):
    _, c, _ = orgs
    u = make_user(db, c, roles=["caico", "client_admin"], name="Katrin Vogel", email="katrin@abc.test")
    login_as(client, db, u)
    acts = set(client.get("/api/v1/auth/me").json()["actions"])
    assert {"view_client_admin_home", "view_initiation_checklist", "manage_client_mailbox", "set_company_roles"} <= acts


@pytest.mark.parametrize("roles,home", [
    (["chief_auditor", "admin"], "/audits"),
    (["admin", "auditor"], "/staff/admin"),
    (["qa_reviewer", "auditor"], "/qa"),
    (["auditor", "sales_team"], "/my-work"),
])
def test_several_futran_roles_land_on_the_higher_authority_home(client, db, orgs, roles, home):
    f, _, _ = orgs
    u = make_user(db, f, roles=roles, name="Multi Staff", email="multi@futran.test")
    login_as(client, db, u)
    assert client.get("/api/v1/auth/me").json()["home"] == home


@pytest.mark.parametrize("path", sorted(HOME_ENDPOINTS))
def test_each_home_loads_only_for_its_own_roles(client, db, orgs, path):
    allowed = HOME_ENDPOINTS[path]
    for i, role in enumerate(sorted({**FUTRAN_HOMES, **CLIENT_HOMES})):
        client.cookies.clear()
        login_as(client, db, _user(db, orgs, role, n=i))
        r = client.get(f"/api/v1{path}")
        if role in allowed:
            assert r.status_code == 200, (role, path, r.text)
        else:
            assert r.status_code in (403, 404), (role, path, r.status_code)


def test_home_data_needs_a_session(client):
    for path in HOME_ENDPOINTS:
        assert client.get(f"/api/v1{path}").status_code == 401
