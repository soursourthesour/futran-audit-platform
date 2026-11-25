"""The groups list counts members in SQL for the groups that can be large, and the count is the same as the members a
send would reach (load test BUG-V02: the groups list took 90 s at 10,000 people)."""
import pytest

from app.mail.groups import active_members, create_group, default_group, member_count
from app.mail.models import DirectoryGroup
from app.mail.people import upsert_person
from tests.factories import login_as, make_department, make_org, make_user


@pytest.fixture
def org(db):
    make_org(db, type="futran")
    return make_org(db, type="client")


def test_counts_match_the_members_for_every_kind_of_group(db, org):
    admin = make_user(db, org, roles=["client_admin"], name="Cleo Admin", email="cleo@abc.com")
    hr = make_department(db, org, name="HR")
    make_user(db, org, name="Uma User", email="uma@abc.com", department_id=hr.id)
    dg = DirectoryGroup(organization_id=org.id, directory_id="dir-1", name="AI-NIST", member_count=0)
    db.add(dg)
    db.flush()
    people = [
        upsert_person(db, org.id, email="ana@abc.com", name="Ana", department_id=hr.id, directory_group_ids=["dir-1"]),
        upsert_person(db, org.id, email="ben@abc.com", name="Ben", status="on_leave", department_id=hr.id, directory_group_ids=["dir-1"]),
        upsert_person(db, org.id, email="cy@abc.com", name="Cy", status="left", directory_group_ids=["dir-1"]),
        upsert_person(db, org.id, email="gus@abc.com", name="Gus Guest", is_guest=True, department_id=hr.id),
        upsert_person(db, org.id, email="dee@abc.com", name="Dee", department_id=hr.id, directory_group_ids=["dir-2"]),
    ]
    everyone = default_group(db, org.id, "all_employees")
    dept = create_group(db, admin, org.id, name="HR people", source="rule", rule={"kind": "department", "department_id": hr.id})
    dirg = create_group(db, admin, org.id, name="NIST", source="directory", directory_group_id=dg.id)
    guests = create_group(db, admin, org.id, name="With guests", source="rule", rule={"kind": "all_people", "include_guests": True})
    left_out = create_group(db, admin, org.id, name="All but Dee", source="rule", rule={"kind": "all_people"})
    left_out.exclusions = [people[4].id]
    db.flush()
    for g in (everyone, dept, dirg, guests, left_out, default_group(db, org.id, "dept_heads")):
        assert member_count(db, g) == len(active_members(db, g)), g.name
    assert member_count(db, everyone) == 4  # Ana, Dee, Cleo and Uma (platform users); not Ben, Cy or the guest
    assert member_count(db, guests) == 5 and member_count(db, left_out) == 3 and member_count(db, dirg) == 1


def test_the_groups_list_does_not_expand_everyone(client, db, org, monkeypatch):
    import app.mail.groups as groups

    admin = make_user(db, org, roles=["client_admin"], name="Cleo Admin", email="cleo@abc.com")
    for i in range(5):
        upsert_person(db, org.id, email=f"p{i}@abc.com", name=f"Person {i}")
    db.commit()
    expanded = []
    real = groups.resolve

    def spy(db_, g, *a, **kw):
        expanded.append(g.system_key or g.name)
        return real(db_, g, *a, **kw)

    monkeypatch.setattr(groups, "resolve", spy)
    login_as(client, db, admin)
    r = client.get(f"/api/v1/mail/groups?client_id={org.id}")
    assert r.status_code == 200, r.text
    counts = {g["system_key"]: g["member_count"] for g in r.json()["groups"]}
    assert counts["all_employees"] == 6
    assert "all_employees" not in expanded
