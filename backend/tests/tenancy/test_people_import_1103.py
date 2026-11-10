"""11-03 review, items C4, C5 and C6: the department workbook, per-department user upload, heads of department matched
from the file, the new user columns (old ones still accepted), and uploads that apply all or nothing."""
import io

import openpyxl
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.invitations.models import Invitation
from app.tenancy.models import Department, User
from app.tenancy.service import roles_of
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NEW_HEADER = "Full name,Work email,Department,Job title,Job level,AI compliance role"


def _dept(client, cid, name):
    r = client.post(f"/api/v1/clients/{cid}/departments", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _user(client, cid, first, last, email, role="contributor", department="Finance"):
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": first, "last_name": last, "email": email, "job_title": "", "department": department, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _send(client, cid, path, data: bytes, name: str, department_id: str | None = None):
    ctype = XLSX if name.endswith(".xlsx") else "text/csv"
    form = {"department_id": department_id} if department_id else {}
    return client.post(f"/api/v1/clients/{cid}/people/{path}", files={"file": (name, data, ctype)}, data=form)


def preview(client, cid, data, name, department_id=None):
    r = _send(client, cid, "import/preview", data, name, department_id)
    assert r.status_code == 200, r.text
    return r.json()


def apply(client, cid, data, name, department_id=None):
    return _send(client, cid, "import", data, name, department_id)


def _book(r) -> openpyxl.Workbook:
    return openpyxl.load_workbook(io.BytesIO(r.content))


def _bytes(wb) -> bytes:
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _emails(db, cid):
    return {u.email for u in db.scalars(select(User).where(User.organization_id == cid, User.deleted_at.is_(None)))}


# ---- C6 user template
def test_user_template_has_the_new_columns(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    r = client.get(f"/api/v1/clients/{cid}/users/template.csv")
    assert r.text.lstrip("﻿").splitlines()[0] == NEW_HEADER


def test_new_columns_import_with_job_level_and_several_roles(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    text = NEW_HEADER + "\nFay Ng Wong,fay@abc.test,finance,Head of finance,Department head,Department Compliance Lead; Data Protection Officer\n"
    pv = preview(client, cid, text.encode(), "users.csv")
    assert pv["errors"] == [] and pv["ready"] is True
    assert pv["users"][0]["action"] == "add" and pv["users"][0]["roles"] == ["Department Compliance Lead", "Data Protection Officer"]
    r = apply(client, cid, text.encode(), "users.csv")
    assert r.status_code == 200, r.text
    fay = db.scalar(select(User).where(User.email == "fay@abc.test"))
    assert (fay.name, fay.job_title, fay.job_level) == ("Fay Ng Wong", "Head of finance", "department_head")
    assert {x.role for x in roles_of(db, fay.id)} == {"dept_compliance_lead", "dpo"}
    assert db.query(Invitation).filter(Invitation.user_id == fay.id).count() == 1  # one invitation, not one per role


def test_old_column_names_still_import(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    old = "first_name,last_name,email,job_title,department,role,location\nTom,Reyes,tom@abc.test,Analyst,Finance,Contributor,Chicago IL\n"
    assert preview(client, cid, old.encode(), "old.csv")["errors"] == []
    assert apply(client, cid, old.encode(), "old.csv").status_code == 200
    # the JSON endpoints the old screen used still work too
    old2 = old.replace("Tom,Reyes,tom@", "Ana,Diaz,ana@")
    assert client.post(f"/api/v1/clients/{cid}/users/import", json={"csv_text": old2}).json()["imported"] == 1
    assert {"tom@abc.test", "ana@abc.test"} <= _emails(db, cid)
    tom = db.scalar(select(User).where(User.email == "tom@abc.test"))
    assert tom.name == "Tom Reyes" and tom.job_title == "Analyst"


def test_a_bad_file_applies_nothing(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    before = _emails(db, cid)
    invites = db.query(Invitation).count()
    text = NEW_HEADER + "\nTom Reyes,tom@abc.test,Finance,Analyst,Level 2,Contributor\nAna Diaz,ana@abc.test,Nowhere,,Level 9,Contributor\n"
    pv = preview(client, cid, text.encode(), "users.csv")
    assert pv["ready"] is False
    assert {(x["row"], x["field"]) for x in pv["errors"]} == {(3, "department"), (3, "job_level")}
    r = apply(client, cid, text.encode(), "users.csv")
    assert r.status_code == 422 and r.json()["detail"].startswith("Nothing was imported")
    db.expire_all()
    assert _emails(db, cid) == before and db.query(Invitation).count() == invites
    # the same through the old JSON endpoint: nothing half-applies
    r = client.post(f"/api/v1/clients/{cid}/users/import", json={"csv_text": text})
    assert r.status_code == 422
    db.expire_all()
    assert _emails(db, cid) == before


# ---- C5 workbook
def test_department_workbook_template(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    _dept(client, cid, "Legal")
    _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    r = client.get(f"/api/v1/clients/{cid}/departments/template.xlsx")
    assert r.status_code == 200 and r.headers["content-type"].startswith(XLSX)
    wb = _book(r)
    assert wb.sheetnames == ["Instructions", "Departments", "Finance", "Legal"]
    ds = wb["Departments"]
    assert [c.value for c in ds[1]] == ["Department", "Parent department", "Head of department", "Headcount"]
    assert {ds.cell(row=i, column=1).value for i in (2, 3)} == {"Finance", "Legal"}
    assert ds.data_validations.dataValidation  # parent list and whole-number headcount
    fin = wb["Finance"]
    assert [c.value for c in fin[1]] == NEW_HEADER.split(",")
    assert [c.value for c in fin[2]][:3] == ["Tom Reyes", "tom@abc.test", "Finance"]
    assert any("Level 1" in (dv.formula1 or "") for dv in fin.data_validations.dataValidation)


def test_workbook_with_no_departments_has_two_example_sheets(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    e.wizard_state = {**(e.wizard_state or {}), "departments": []}
    db.commit()
    wb = _book(client.get(f"/api/v1/clients/{cid}/departments/template.xlsx"))
    assert len(wb.sheetnames) == 4 and wb.sheetnames[:2] == ["Instructions", "Departments"]
    # the example rows are refused if uploaded unchanged, so they can't become real users
    pv = preview(client, cid, _bytes(wb), "people.xlsx")
    assert any("example" in x["message"] for x in pv["errors"])


def test_workbook_round_trip_then_add_a_department_and_its_people(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    _user(client, cid, "Tom", "Reyes", "tom@abc.test")
    data = client.get(f"/api/v1/clients/{cid}/departments/template.xlsx").content
    pv = preview(client, cid, data, "people.xlsx")  # unchanged: nothing to do, nothing wrong
    assert pv["errors"] == [] and {x["action"] for x in pv["departments"] + pv["users"]} == {"unchanged"}
    wb = openpyxl.load_workbook(io.BytesIO(data))
    wb["Departments"].append(["Legal", "Finance", "lee.park@abc.test", 6])
    wb["Finance"].append(["Ana Diaz", "ana@abc.test", None, "Analyst", "Level 1", "Contributor"])  # department from the sheet
    legal = wb.create_sheet("Legal")
    legal.append(NEW_HEADER.split(","))
    legal.append(["Lee Park", "lee.park@abc.test", None, "Counsel", "Manager", "Department Compliance Lead"])
    pv = preview(client, cid, _bytes(wb), "people.xlsx")
    assert pv["errors"] == [], pv["errors"]
    assert [(x["name"], x["action"]) for x in pv["departments"]] == [("Finance", "unchanged"), ("Legal", "add")]
    assert pv["departments"][1]["head"] == "Lee Park"  # a person added by the same file
    r = apply(client, cid, _bytes(wb), "people.xlsx")
    assert r.status_code == 200, r.text
    db.expire_all()
    lg = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "Legal"))
    fin = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "Finance"))
    assert (lg.parent_id, lg.headcount, lg.head_name, lg.head_email) == (fin.id, 6, "Lee Park", "lee.park@abc.test")
    lee = db.scalar(select(User).where(User.email == "lee.park@abc.test"))
    assert [(x.role, x.scope_id) for x in roles_of(db, lee.id)] == [("dept_compliance_lead", lg.id)] and lee.job_level == "manager"
    ana = db.scalar(select(User).where(User.email == "ana@abc.test"))
    assert [(x.role, x.scope_id) for x in roles_of(db, ana.id)] == [("contributor", fin.id)]


def test_workbook_errors_name_the_sheet_and_row(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    wb = _book(client.get(f"/api/v1/clients/{cid}/departments/template.xlsx"))
    wb["Finance"].append(["Ana Diaz", "not-an-email", None, None, None, "Contributor"])
    pv = preview(client, cid, _bytes(wb), "people.xlsx")
    assert [(x["sheet"], x["row"], x["field"]) for x in pv["errors"]] == [("Finance", 2, "email")]
    assert apply(client, cid, _bytes(wb), "people.xlsx").status_code == 422


def test_upload_users_to_one_department(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    fin = _dept(client, cid, "Finance")
    _dept(client, cid, "Legal")
    text = "Full name,Work email,Job title,AI compliance role\nAna Diaz,ana@abc.test,Analyst,Contributor\n"
    pv = preview(client, cid, text.encode(), "fin.csv", department_id=fin)
    assert pv["errors"] == [] and pv["users"][0]["department"] == "Finance"
    assert apply(client, cid, text.encode(), "fin.csv", department_id=fin).status_code == 200
    ana = db.scalar(select(User).where(User.email == "ana@abc.test"))
    assert [x.scope_id for x in roles_of(db, ana.id)] == [fin]
    # a row for another department is refused, not moved
    bad = NEW_HEADER + "\nLee Park,lee@abc.test,Legal,,,Contributor\n"
    pv = preview(client, cid, bad.encode(), "fin.csv", department_id=fin)
    assert pv["errors"][0]["field"] == "department" and "Legal" in pv["errors"][0]["message"]
    # a workbook: only the sheet for that department is read
    wb = _book(client.get(f"/api/v1/clients/{cid}/departments/template.xlsx"))
    wb["Finance"].append(["Bo Chan", "bo@abc.test", None, None, None, "Contributor"])
    wb["Legal"].append(["Cy Diaz", "cy@abc.test", None, None, None, "Contributor"])
    pv = preview(client, cid, _bytes(wb), "people.xlsx", department_id=fin)
    assert pv["errors"] == [] and {x["email"] for x in pv["users"] if x["action"] == "add"} == {"bo@abc.test"}
    other = client.post(f"/api/v1/clients/{cid}/people/import/preview", files={"file": ("x.csv", text.encode(), "text/csv")}, data={"department_id": "nope"})
    assert other.status_code == 404


# ---- C4 heads of department
def test_head_of_department_is_matched_by_email_then_exact_name(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    for d in ("Finance", "Legal", "Sales", "Ops", "Risk"):
        _dept(client, cid, d)
    _user(client, cid, "Sam", "Lee", "sam1@abc.test")
    _user(client, cid, "Sam", "Lee", "sam2@abc.test", department="Legal")
    _user(client, cid, "Fay", "Ng", "fay@abc.test")
    text = ("Department,Parent department,Head of department,Headcount\n"
            "Finance,,FAY@abc.test,\n"        # email, any case
            "Legal,,  fay   NG ,\n"            # exact full name, case and spaces ignored
            "Sales,,Sam Lee,\n"                # two people with that name: not guessed
            "Ops,,Nobody Here,\n"              # no match
            "Risk,,nobody@abc.test,\n")        # an email that matches no one is not tried as a name
    pv = preview(client, cid, text.encode(), "depts.csv")
    assert pv["errors"] == []
    heads = {x["name"]: x["head"] for x in pv["departments"]}
    assert heads == {"Finance": "Fay Ng", "Legal": "Fay Ng", "Sales": None, "Ops": None, "Risk": None}
    warn = {x["row"]: x["message"] for x in pv["warnings"]}
    assert "2 people are called Sam Lee" in warn[4] and "Nobody Here" in warn[5] and "nobody@abc.test" in warn[6]
    assert apply(client, cid, text.encode(), "depts.csv").status_code == 200
    db.expire_all()
    got = {d.name: (d.head_name, d.head_email) for d in db.scalars(select(Department).where(Department.organization_id == cid))}
    assert got["Finance"] == ("Fay Ng", "fay@abc.test") and got["Legal"] == ("Fay Ng", "fay@abc.test")
    assert got["Sales"] == (None, None) and got["Ops"] == (None, None)
    edits = db.scalars(select(AuditLog).where(AuditLog.action == "department.edit")).all()
    assert any((a.after or {}).get("head_email") == "fay@abc.test" for a in edits)  # recorded as the screen records it


def test_department_scope_is_fixed_after_setup(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    e.stage = 3
    db.commit()
    text = "Department,Parent department,Head of department,Headcount\nFinance,,,12\nLegal,,,3\n"
    pv = preview(client, cid, text.encode(), "d.csv")
    assert [x["row"] for x in pv["errors"]] == [3] and "fixed after setup" in pv["errors"][0]["message"]
