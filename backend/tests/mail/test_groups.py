import pytest

from app.core.errors import Conflict
from app.mail.groups import active_members, add_member, create_group, default_group, ensure_default_groups, resolve, rule_text
from app.mail.models import MailGroup
from app.mail.people import upsert_person
from tests.factories import make_department, make_org, make_user


@pytest.fixture
def org(db):
    make_org(db, type="futran")
    return make_org(db, type="client")


@pytest.fixture
def admin(db, org):
    return make_user(db, org, roles=["client_admin"], name="Cleo Admin", email="cleo@abc.com")


def _person(db, org, name, **kw):
    return upsert_person(db, org.id, email=f"{name.split()[0].lower()}@abc.com", name=name, **kw)


def test_every_client_gets_the_four_default_groups_once(db, org):
    ensure_default_groups(db, org.id)
    ensure_default_groups(db, org.id)
    names = sorted(g.name for g in db.query(MailGroup).filter_by(organization_id=org.id))
    assert names == ["AI Governance Committee", "AIComplianceTeam", "DeptHeads", "Employees · All"]


def test_futran_gets_role_groups_and_one_group_per_engagement_team(db):
    from app.engagements.models import Engagement, EngagementTeam

    futran = db.query(__import__("app.tenancy.models", fromlist=["Organization"]).Organization).filter_by(type="futran").first() or make_org(db, type="futran")
    client = make_org(db, type="client", name="Meridian")
    chief = make_user(db, futran, roles=["chief_auditor"], name="Carla Chief", email="carla@futran.test")
    al = make_user(db, futran, roles=["auditor"], name="Al Auditor", email="al@futran.test")
    e = Engagement(organization_id=client.id, client_id=client.id, name="AI audit", status="active", stage=3)
    db.add(e)
    db.flush()
    db.add(EngagementTeam(organization_id=client.id, engagement_id=e.id, user_id=al.id, role="auditor"))
    db.flush()
    ensure_default_groups(db, futran.id)
    names = {g.name for g in db.query(MailGroup).filter_by(organization_id=futran.id)}
    assert {"AuditTeam", "ChiefAuditors", "Auditors", "QAReviewers", "FutranAdmins", "Engagement · Meridian"} <= names
    assert [p.email for p in active_members(db, default_group(db, futran.id, "chief_auditors"))] == ["carla@futran.test"]
    team = db.query(MailGroup).filter_by(organization_id=futran.id, name="Engagement · Meridian").one()
    assert [p.email for p in active_members(db, team)] == ["al@futran.test"]
    assert {p.email for p in active_members(db, default_group(db, futran.id, "audit_team"))} == {"carla@futran.test", "al@futran.test"}
    assert chief  # used


def test_nested_groups_expand_and_a_loop_is_rejected(db, org, admin):
    a = create_group(db, admin, org.id, name="AI-NIST", source="manual")
    b = create_group(db, admin, org.id, name="AI-EUAct", source="manual")
    c = create_group(db, admin, org.id, name="Working groups", source="manual")
    add_member(db, admin, a, person_id=_person(db, org, "Ana Ruiz").id)
    add_member(db, admin, b, person_id=_person(db, org, "Ben Ode").id)
    add_member(db, admin, c, nested_group_id=a.id)
    add_member(db, admin, c, nested_group_id=b.id)
    assert {p.name for p in resolve(db, c).values()} == {"Ana Ruiz", "Ben Ode"}
    with pytest.raises(Conflict):
        add_member(db, admin, a, nested_group_id=c.id)  # c already includes a
    with pytest.raises(Conflict):
        add_member(db, admin, a, nested_group_id=a.id)


def test_rule_groups_follow_departments_and_roles(db, org, admin):
    hr = make_department(db, org, name="Human Resources")
    fin = make_department(db, org, name="Finance")
    _person(db, org, "Hana Sato", department_id=hr.id)
    _person(db, org, "Finn Berg", department_id=fin.id)
    lead = make_user(db, org, roles=[("dept_compliance_lead", "department", hr.id)], name="Lena Lead", email="lena@abc.com", department_id=hr.id)
    g = create_group(db, admin, org.id, name="Employees · HR", source="rule", rule={"kind": "department", "department_id": hr.id})
    assert {p.name for p in active_members(db, g)} == {"Hana Sato", "Lena Lead"}
    assert rule_text(db, g) == "Rule: department = Human Resources"
    heads = default_group(db, org.id, "dept_heads")
    assert [p.email for p in active_members(db, heads)] == [lead.email]


def test_people_on_leave_and_leavers_are_not_active_members(db, org, admin):
    g = create_group(db, admin, org.id, name="Contractors", source="manual")
    for name, status in (("Ana Ruiz", "active"), ("Ben Ode", "on_leave"), ("Cy Doe", "left")):
        add_member(db, admin, g, person_id=_person(db, org, name, status=status).id)
    assert [p.name for p in active_members(db, g)] == ["Ana Ruiz"]


def test_rule_and_directory_groups_cannot_have_members_added(db, org, admin):
    heads = default_group(db, org.id, "dept_heads")
    with pytest.raises(Conflict):
        add_member(db, admin, heads, person_id=_person(db, org, "Ana Ruiz").id)


def test_employees_all_includes_everyone_with_a_login_before_any_directory_sync(db, org, admin):
    _person(db, org, "Ana Ruiz")
    everyone = default_group(db, org.id, "all_employees")
    assert {p.email for p in active_members(db, everyone)} == {"ana@abc.com", "cleo@abc.com"}
