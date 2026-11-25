"""Every user with a login is a person who can be emailed. ensure_platform_people() is set-based (a fixed number of
statements whatever the company size) and does nothing when nothing has changed (load test BUG-V02)."""
from sqlalchemy import event, select

from app.core.clock import utcnow
from app.mail.models import DirectoryPerson
from app.mail.people import ensure_platform_people
from tests.factories import make_department, make_org, make_user


class Count:
    def __init__(self, engine):
        self.engine, self.n = engine, 0

    def _on(self, *_):
        self.n += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *_):
        event.remove(self.engine, "before_cursor_execute", self._on)


def _people(db, org):
    return {p.email: p for p in db.scalars(select(DirectoryPerson).where(DirectoryPerson.organization_id == org.id, DirectoryPerson.deleted_at.is_(None)))}


def test_users_become_people_with_their_department_and_existing_people_are_linked_not_copied(db):
    org = make_org(db)
    hr = make_department(db, org, name="HR")
    fin = make_department(db, org, name="Finance")
    a = make_user(db, org, name="Ann Lee", email="ann@abc.test", department_id=hr.id, job_title="Analyst", location="Berlin")
    b = make_user(db, org, name="Bob Ray", email="Bob@ABC.test", roles=[("dept_compliance_lead", "department", fin.id)])
    off = make_user(db, org, name="Cy Off", email="cy@abc.test")
    off.status = "disabled"
    known = DirectoryPerson(organization_id=org.id, email="bob@abc.test", name="Robert Ray", source="directory", status="active", directory_group_ids=[])
    db.add(known)
    db.flush()
    ensure_platform_people(db, org.id)
    people = _people(db, org)
    assert set(people) == {"ann@abc.test", "bob@abc.test"}  # the disabled user is left out
    ann = people["ann@abc.test"]
    assert (ann.user_id, ann.department_id, ann.job_title, ann.office, ann.source) == (a.id, hr.id, "Analyst", "Berlin", "platform")
    bob = people["bob@abc.test"]
    assert bob.id == known.id and bob.user_id == b.id and bob.department_id == fin.id and bob.name == "Robert Ray"  # linked, not renamed


def test_statements_do_not_grow_with_the_number_of_users(db, engine):
    def run(n):
        org = make_org(db, name=f"Org {n}")
        dept = make_department(db, org, name="Ops")
        for i in range(n):
            make_user(db, org, name=f"User {i}", email=f"u{i}@org{n}.test", roles=[("contributor", "department", dept.id)] if i % 2 else ())
        db.flush()
        with Count(engine) as c:
            ensure_platform_people(db, org.id)
        assert len(_people(db, org)) == n
        return c.n

    small, large = run(5), run(60)
    assert large <= small + 2, (small, large)  # was one lookup per user (and one more per user without a department)


def test_nothing_is_read_again_until_a_user_or_person_changes(db, engine):
    org = make_org(db)
    make_user(db, org, name="Ann Lee", email="ann@abc.test")
    ensure_platform_people(db, org.id)
    with Count(engine) as c:
        ensure_platform_people(db, org.id)
    assert c.n == 1  # the change check only
    new = make_user(db, org, name="Dan New", email="dan@abc.test")
    ensure_platform_people(db, org.id)
    assert _people(db, org)["dan@abc.test"].user_id == new.id
    # a person removed by hand is added back for a user who still has a login, as before
    p = _people(db, org)["ann@abc.test"]
    p.deleted_at = utcnow()
    db.flush()
    ensure_platform_people(db, org.id)
    assert "ann@abc.test" in _people(db, org)


def test_a_rolled_back_run_is_done_again(db):
    org = make_org(db)
    make_user(db, org, name="Ann Lee", email="ann@abc.test")
    db.commit()
    ensure_platform_people(db, org.id)
    db.rollback()
    assert _people(db, org) == {}
    ensure_platform_people(db, org.id)
    assert set(_people(db, org)) == {"ann@abc.test"}


def test_people_are_found_through_an_index_on_the_lower_case_email(db):
    rows = db.connection().exec_driver_sql("EXPLAIN QUERY PLAN SELECT id FROM directory_people WHERE organization_id = 'x' AND lower(email) = 'a@b.test'").fetchall()
    assert "ix_directory_people_org_email_ci" in " ".join(str(r) for r in rows)
