from types import SimpleNamespace

import pytest

from app.connectors.adapters.fake import FAKE
from tests.factories import login_as, make_department, make_org, make_user


@pytest.fixture(autouse=True)
def _reset_fake():
    FAKE.reset()
    yield
    FAKE.reset()


@pytest.fixture
def w(db, client):
    """Futran (Chief Auditor, an assigned and an unassigned auditor, Admin); ABC Corp (abccorp.example) with a Client Admin,
    CAICO, an HR Department Compliance Lead and a contributor; a second client, Other Co (otherco.example)."""
    from app.core.clock import today
    from app.engagements.models import Engagement, EngagementTeam

    f = make_org(db, type="futran")
    ns = SimpleNamespace(client=client, db=db)
    ns.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    ns.auditor = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    ns.other_auditor = make_user(db, f, roles=["auditor"], name="Olly Other", email="olly@futran.test")
    ns.fadmin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    org = make_org(db, name="ABC Corp")
    ns.org = org
    ns.hr = make_department(db, org, name="HR")
    ns.sales = make_department(db, org, name="Sales & Marketing")
    ns.fin = make_department(db, org, name="Finance")
    ns.admin = make_user(db, org, roles=["client_admin"], name="Sam Okafor", email="sam.okafor@abccorp.example")
    ns.caico = make_user(db, org, roles=["caico"], name="Maria Lopez", email="maria.lopez@abccorp.example")
    ns.hr_lead = make_user(db, org, roles=[("dept_compliance_lead", "department", ns.hr.id)], name="Priya Shah", email="priya.shah@abccorp.example", department_id=ns.hr.id)
    ns.contrib = make_user(db, org, roles=[("contributor", "department", ns.hr.id)], name="Tom Reyes", email="tom.reyes@abccorp.example", department_id=ns.hr.id)
    other = make_org(db, name="Other Co")
    ns.other = other
    ns.other_admin = make_user(db, other, roles=["client_admin"], name="Olga Admin", email="olga@otherco.example")
    e = Engagement(organization_id=org.id, client_id=org.id, name="ABC Corp AI audit", status="fieldwork")
    db.add(e)
    db.flush()
    db.add(EngagementTeam(organization_id=org.id, engagement_id=e.id, user_id=ns.auditor.id, role="auditor"))
    db.commit()
    ns.engagement = e
    ns.today = today()
    ns.as_ = lambda user: login_as(client, db, user)
    return ns
