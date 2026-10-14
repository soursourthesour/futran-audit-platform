import csv
import io

import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.engagements.models import Engagement
from app.invitations.models import Invitation
from app.notifications.models import Notification
from app.tenancy.csv_import import parse_department_csv, parse_user_csv
from app.tenancy.models import Department, User
from app.tenancy.service import roles_of
from tests.factories import login_as, make_user
from tests.initiation.conftest import APPROVAL, people, submitted  # noqa: F401

USERS_HEADER = "first_name,last_name,email,job_title,department,role,location"


def test_user_csv_messy_rows():
    text = "﻿" + USERS_HEADER + "\n" + "\n".join([
        "Priya , Shah ,priya.shah@abc.com , Head of HR,human resources,Department Compliance Lead,New York NY",
        "Tom,Reyes,TOM.REYES@abc.com,Recruiter,Human Resources,contributor,New York NY",
        "Tom,Reyes,tom.reyes@abc.com,Recruiter,Human Resources,Contributor,New York NY",
        "Lee,Park,lee.park@abc.com,Counsel,Legal,Contributor,Chicago IL",
        "Ana,Diaz,ana.diaz@abc.com,Analyst,Finance,dept lead,Chicago IL",
    ]) + "\n"
    r = parse_user_csv(text, ["Human Resources", "Finance"])
    assert [(x["email"], x["department"], x["role"]) for x in r.rows_ok] == [
        ("priya.shah@abc.com", "Human Resources", "dept_compliance_lead"),
        ("tom.reyes@abc.com", "Human Resources", "contributor"),
    ]
    assert r.rows_ok[0]["first_name"] == "Priya" and r.rows_ok[0]["job_title"] == "Head of HR"
    assert r.errors == [
        {"row": 4, "field": "email", "message": "Email appears more than once in this file."},
        {"row": 5, "field": "department", "message": "Department 'Legal' is not in the department list."},
        {"row": 6, "field": "role", "message": "Role 'dept lead' is not recognised."},
    ]


def test_user_csv_wrong_header_and_required_fields():
    r = parse_user_csv("name,email\nA,a@b.com\n", ["HR"])
    assert r.rows_ok == [] and r.errors[0]["row"] == 1 and "first_name" in r.errors[0]["message"]
    r = parse_user_csv(USERS_HEADER + "\n,Shah,not-an-email,,HR,Contributor,\nA,B,a@b.com,,,Contributor,\n", ["HR"])
    msgs = {(e["row"], e["field"]): e["message"] for e in r.errors}
    assert msgs[(2, "first_name")] == "First name is required."
    assert msgs[(2, "email")] == "Email 'not-an-email' is not a valid email address."
    assert msgs[(3, "department")] == "A Contributor needs a department."


def test_department_csv_parse():
    r = parse_department_csv("﻿department,head_name,head_email,headcount\nHuman Resources , Priya Shah,priya@abc.com, 14\nhuman resources,,,\nFinance,,bad,lots\n")
    assert r.rows_ok == [{"department": "Human Resources", "head_name": "Priya Shah", "head_email": "priya@abc.com", "headcount": 14}]
    assert [e["message"] for e in r.errors] == [
        "Department 'human resources' appears more than once in this file.",
        "Email 'bad' is not a valid email address.",
        "Headcount must be a whole number.",
    ]


@pytest.fixture
def live(client, db, people, submitted):
    """An approved engagement with Maria (CAICO and Client Admin) active."""
    cid, e = submitted()
    login_as(client, db, people["chief"])
    client.get(f"/api/v1/clients/{cid}/package")
    assert client.post(f"/api/v1/clients/{cid}/approve", json=APPROVAL).status_code == 200
    maria = db.scalar(select(User).where(User.email == "maria@abc.test"))
    maria.status = "active"
    db.commit()
    from app.signoffs.models import SignOff

    so = db.scalar(select(SignOff).where(SignOff.engagement_id == e.id))
    login_as(client, db, maria)
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Maria Lopez"}).status_code == 200
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Cara Chief"}).status_code == 200
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 2
    return cid, e, maria


def test_department_csv_prefilled_from_scope(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    r = client.get(f"/api/v1/clients/{cid}/departments/template.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["department", "head_name", "head_email", "headcount"]
    assert [x[0] for x in rows[1:]] == ["HR and recruiting", "Engineering and IT"]


def test_import_departments_and_users_then_stage_advances(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    dep_csv = "department,head_name,head_email,headcount\nHR and recruiting,Priya Shah,priya@abc.test,14\nEngineering and IT,,,40\n"
    pv = client.post(f"/api/v1/clients/{cid}/departments/import/preview", json={"csv_text": dep_csv}).json()
    assert len(pv["rows_ok"]) == 2 and pv["errors"] == []
    assert client.post(f"/api/v1/clients/{cid}/departments/import", json={"csv_text": dep_csv}).json()["imported"] == 2
    assert client.post(f"/api/v1/clients/{cid}/departments/confirm").status_code == 200
    users = USERS_HEADER + "\nPriya,Shah,priya@abc.test,Head of HR,HR and recruiting,Department Compliance Lead,New York NY\nTom,Reyes,tom@abc.test,Recruiter,HR and recruiting,Contributor,New York NY\nBad,Row,bad,,Nowhere,Contributor,\n"
    out = client.post(f"/api/v1/clients/{cid}/users/import", json={"csv_text": users}).json()
    assert out["imported"] == 2 and len(out["errors"]) == 2
    priya = db.scalar(select(User).where(User.email == "priya@abc.test"))
    assert priya.organization_id == cid and priya.name == "Priya Shah" and priya.job_title == "Head of HR"
    hr = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "HR and recruiting"))
    assert [(r.role, r.scope_type, r.scope_id) for r in roles_of(db, priya.id)] == [("dept_compliance_lead", "department", hr.id)]
    assert db.query(Invitation).filter(Invitation.user_id == priya.id).count() == 1
    # Engineering still has no lead: still in stage 2
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 2
    page = client.get(f"/api/v1/clients/{cid}/people").json()
    eng = next(d for d in page["departments"] if d["name"] == "Engineering and IT")
    assert eng["lead"] is None and page["gate"]["unmet"] == ["Engineering and IT has no Department Compliance Lead."]
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Raj", "last_name": "Iyer", "email": "raj@abc.test", "job_title": "CTO", "department": "Engineering and IT", "role": "dept_compliance_lead"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 3
    checklist = {i["key"]: i["done"] for i in client.get("/api/v1/me/initiation").json()["items"]}
    assert checklist["departments"] and checklist["users"]


def test_sign_off_role_change_notifies_futran(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Omar", "last_name": "Haddad", "email": "omar@abc.test", "job_title": "COO", "department": "", "role": "exec_sponsor"})
    assert r.status_code == 200, r.text
    omar = db.scalar(select(User).where(User.email == "omar@abc.test"))
    notes = db.scalars(select(Notification).where(Notification.kind == "sign_off_role_changed")).all()
    assert {n.user_id for n in notes} == {people["chief"].id, people["aud"].id, people["em"].id}
    assert "Omar Haddad" in notes[0].title and "Executive Sponsor" in notes[0].title
    assert db.scalar(select(AuditLog).where(AuditLog.action == "role.assign", AuditLog.object_id == omar.id)) is not None
    ra = next(x for x in roles_of(db, omar.id) if x.role == "exec_sponsor")
    assert client.delete(f"/api/v1/clients/{cid}/users/{omar.id}/roles/{ra.id}").status_code == 200
    assert len(db.scalars(select(Notification).where(Notification.kind == "sign_off_role_changed")).all()) == 6
    assert db.scalar(select(AuditLog).where(AuditLog.action == "role.remove")) is not None
    # a contributor is not a sign-off role: no notification
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Finance"})
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Tom", "last_name": "Reyes", "email": "tom@abc.test", "job_title": "", "department": "Finance", "role": "contributor"})
    assert len(db.scalars(select(Notification).where(Notification.kind == "sign_off_role_changed")).all()) == 6


def test_role_holders_not_appointed(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    r = client.put(f"/api/v1/clients/{cid}/role-holders/exec_sponsor", json={"not_appointed": True})
    assert r.status_code == 200
    page = client.get(f"/api/v1/clients/{cid}/people").json()
    assert page["role_holders"]["exec_sponsor"] == {"user": None, "not_appointed": True}
    assert page["role_holders"]["dpo"]["not_appointed"] is True  # set at setup


def test_client_admin_cannot_edit_audit_content(client, db, people, live, settings):
    from app.files.service import upload
    from app.signoffs.models import SignOff

    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Sam", "last_name": "Admin", "email": "sam@abc.test", "job_title": "IT", "department": "", "role": "client_admin"})
    sam = db.scalar(select(User).where(User.email == "sam@abc.test"))
    sam.status = "active"
    ev = upload(db, settings, maria, data=b"report", filename="bias.pdf", content_type="application/pdf", organization_id=cid, engagement_id=e.id, linked_type="evidence", linked_id="x")
    db.commit()
    so = db.scalar(select(SignOff).where(SignOff.engagement_id == e.id))
    login_as(client, db, sam)
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Sam Admin"}).status_code == 403
    assert client.get(f"/api/v1/files/{ev.id}").status_code == 403
    assert client.post("/api/v1/me/initiation/items/notice/done").status_code == 409
    assert client.get(f"/api/v1/clients/{cid}/wizard").status_code == 404
    # but can manage people
    assert client.get(f"/api/v1/clients/{cid}/people").status_code == 200


def test_other_client_cannot_manage_people(client, db, people, live):
    from tests.factories import make_org

    cid, e, maria = live
    other = make_org(db, name="XYZ")
    boss = make_user(db, other, roles=["client_admin"], name="X Admin", email="x@xyz.test")
    db.commit()
    login_as(client, db, boss)
    assert client.get(f"/api/v1/clients/{cid}/people").status_code == 404
    assert client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "A", "last_name": "B", "email": "a@b.test", "job_title": "", "department": "", "role": "contributor"}).status_code == 404
