"""11-03 review fixes on the new-system form: departments (C9), who uses it (C10), owner by department (C11),
the company's own data (C13). Existing systems open and save unchanged."""
from app.register.models import RegisterSystem
from tests.register.conftest import new_system


def test_options_give_people_department_job_level_and_compliance_roles(client, db, reg):
    reg.as_(reg.caico)
    d = client.get("/api/v1/register").json()
    hana = next(p for p in d["people"] if p["name"] == "Hana Ito")
    assert hana["department_id"] == reg.hr.id and "job_level" in hana and hana["compliance_roles"] == []
    priya = next(p for p in d["people"] if p["name"] == "Priya Shah")
    assert priya["compliance_roles"] == ["dept_compliance_lead"]
    codes = [x["value"] for x in d["job_levels"]]
    assert codes == ["executive", "department_head", "manager", "level_3", "level_2", "level_1"]
    assert {"value": "dept_compliance_lead", "label": "Department Compliance Lead"} in d["compliance_roles"]


def test_used_by_several_departments_is_stored(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, department_ids=[reg.hr.id, reg.fin.id])
    assert {x["id"] for x in s["departments"]} == {reg.hr.id, reg.fin.id}
    r = client.patch(f"/api/v1/register/{s['id']}", json={"department_ids": [reg.fin.id]})
    assert r.status_code == 200 and [x["name"] for x in r.json()["departments"]] == ["Finance"]
    changes = client.get(f"/api/v1/register/{s['id']}/changes").json()
    assert any(c["field"] == "department_ids" and c["new_value"] == "Finance" for c in changes)


def test_used_by_departments_must_be_the_clients(client, db, reg):
    from tests.factories import make_department, make_org

    other = make_department(db, make_org(db, name="Other Co"), name="Elsewhere")
    db.commit()
    reg.as_(reg.caico)
    r = client.post("/api/v1/register", json={"name": "X", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.hr.id, "department_ids": [other.id]})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "department_ids"


def test_named_users_count_is_calculated(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, users_scope="named", user_count=99,
                   user_selection={"user_ids": [reg.hr_user.id, reg.contrib.id]})
    assert s["user_count"] == 2 and s["user_selection"]["user_ids"] == [reg.hr_user.id, reg.contrib.id]


def test_named_users_must_be_the_clients(client, db, reg):
    from tests.factories import make_org, make_user

    stranger = make_user(db, make_org(db, name="Other Co"), name="Stranger")
    db.commit()
    reg.as_(reg.caico)
    r = client.post("/api/v1/register", json={"name": "X", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.hr.id, "users_scope": "named",
                                              "user_selection": {"user_ids": [stranger.id]}})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "user_selection"


def test_role_level_counts_matching_users_in_the_systems_departments(client, db, reg):
    reg.as_(reg.caico)
    # HR people: Priya (dept lead), Cole (contributor), Hana. Finance: Tom (dept lead).
    s = new_system(client, department_id=reg.hr.id, users_scope="role", user_selection={"compliance_roles": ["dept_compliance_lead", "contributor"]})
    assert s["user_count"] == 2  # Priya and Cole; Tom is in Finance
    s2 = new_system(client, name="Both", department_id=reg.hr.id, department_ids=[reg.hr.id, reg.fin.id], users_scope="role",
                    user_selection={"compliance_roles": ["dept_compliance_lead"]})
    assert s2["user_count"] == 2  # Priya and Tom
    s3 = new_system(client, name="Titles", department_id=reg.hr.id, users_scope="role", user_selection={"job_titles": ["Recruiter"]})
    assert s3["user_count"] == 0


def test_role_level_job_levels_tolerate_a_missing_column(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, users_scope="role", user_selection={"job_levels": ["manager"]})
    assert s["user_count"] == 0 and s["user_selection"]["job_levels"] == ["manager"]
    r = client.post("/api/v1/register", json={"name": "Bad", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.hr.id, "users_scope": "role",
                                              "user_selection": {"job_levels": ["janitor"]}})
    assert r.status_code == 422


def test_without_a_selection_the_typed_count_stays(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, users_scope="role", users_description="Recruiting team", user_count=12)
    assert s["user_count"] == 12 and s["user_selection"] is None


def test_company_own_data_is_a_choice(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, data={"data_subjects": ["company"], "data_categories": ["confidential"]})
    assert s["data"]["data_subjects"] == ["company"]
    assert "company" not in (s["risk_tier_reason"] or "").split(", ")[1:]  # not named as a group of people


def test_existing_system_saves_unchanged(client, db, reg):
    """A system saved before 11-03 has none of the new fields; saving the form as it loads changes nothing."""
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, users_scope="role", user_count=7, owner_user_id=reg.hr_user.id)
    row = db.get(RegisterSystem, s["id"])
    row.department_ids = row.user_selection = row.run_location = row.data_locations = row.dismissed_law_ids = None
    db.commit()
    before = client.get(f"/api/v1/register/{s['id']}").json()
    body = {k: before[k] for k in ("name", "type", "sourcing", "stage", "purpose", "users_scope", "users_description", "user_count", "company_wide")}
    body |= {"department_id": reg.hr.id, "owner_user_id": reg.hr_user.id, "department_ids": None, "user_selection": None, "run_location": None, "data_locations": None}
    r = client.patch(f"/api/v1/register/{s['id']}", json=body)
    assert r.status_code == 200
    assert r.json()["user_count"] == 7
    assert [c for c in client.get(f"/api/v1/register/{s['id']}/changes").json() if c["field"] != "created"] == []
