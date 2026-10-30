"""Security review I4: adding a group member by email never moves or renames an existing person, and a Department
Compliance Lead places new people only in a department they manage."""
from app.mail.models import DirectoryPerson, MailRecipient
from app.mail.people import upsert_person
from tests.factories import login_as, make_department, make_org, make_user

API = "/api/v1"


def _world(client, db):
    make_org(db, type="futran")
    org = make_org(db, name="ABC")
    hr, fin = make_department(db, org, name="Human Resources"), make_department(db, org, name="Finance")
    lead = make_user(db, org, roles=[("dept_compliance_lead", "department", hr.id)], name="Hana Lead", email="hana@abc.com")
    cfo = upsert_person(db, org.id, email="cfo@abc.com", name="Carl CFO", department_id=fin.id)
    db.commit()
    login_as(client, db, lead)
    g = client.post(f"{API}/mail/groups", json={"name": "HR notices", "source": "manual", "department_id": hr.id})
    assert g.status_code == 200, g.text
    return org, hr, fin, lead, cfo, g.json()["id"]


def test_adding_an_existing_person_by_email_keeps_their_name_and_department(client, db):
    org, hr, fin, lead, cfo, gid = _world(client, db)
    r = client.post(f"{API}/mail/groups/{gid}/members", json={"email": "CFO@abc.com", "name": "Renamed By Lead", "department_id": hr.id})
    assert r.status_code == 200, r.text
    db.expire_all()
    p = db.get(DirectoryPerson, cfo.id)
    assert p.department_id == fin.id and p.name == "Carl CFO"
    # and the lead's send still stops at their own departments
    s = client.post(f"{API}/mail/send", json={"group_ids": [gid], "template_key": "regulatory_change_alert", "body": "Anything the lead writes"})
    if s.status_code == 200:
        assert "cfo@abc.com" not in [x.email for x in db.query(MailRecipient).filter_by(send_id=s.json()["id"])]
    else:
        assert s.status_code == 422


def test_a_department_lead_cannot_place_a_new_person_in_another_department(client, db):
    org, hr, fin, lead, cfo, gid = _world(client, db)
    r = client.post(f"{API}/mail/groups/{gid}/members", json={"email": "new.analyst@abc.com", "name": "New Analyst", "department_id": fin.id})
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["field"] == "department_id"
    assert db.query(DirectoryPerson).filter_by(email="new.analyst@abc.com").count() == 0
    ok = client.post(f"{API}/mail/groups/{gid}/members", json={"email": "new.recruiter@abc.com", "name": "New Recruiter", "department_id": hr.id})
    assert ok.status_code == 200, ok.text
    db.expire_all()
    assert db.query(DirectoryPerson).filter_by(email="new.recruiter@abc.com").one().department_id == hr.id


def test_csv_import_does_not_rename_existing_people(client, db):
    org, hr, fin, lead, cfo, gid = _world(client, db)
    r = client.post(f"{API}/mail/groups/{gid}/import", json={"csv": "email,name\ncfo@abc.com,Someone Else\nfresh@abc.com,Fresh Face\n"})
    assert r.status_code == 200 and r.json()["added"] == 2, r.text
    db.expire_all()
    assert db.get(DirectoryPerson, cfo.id).name == "Carl CFO"
    assert db.query(DirectoryPerson).filter_by(email="fresh@abc.com").one().name == "Fresh Face"
