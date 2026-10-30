from types import SimpleNamespace

import pytest

from tests.factories import login_as, make_department, make_org, make_user


@pytest.fixture
def reg(db, client):
    """ABC Corp with HR and Finance, a CAICO, a Client Admin, two Department Compliance Leads and a Contributor."""
    org = make_org(db)
    hr = make_department(db, org, name="Human Resources")
    fin = make_department(db, org, name="Finance")
    ns = SimpleNamespace(org=org, hr=hr, fin=fin)
    ns.caico = make_user(db, org, roles=["caico"], name="Maria Lopez", email="maria@abc.test", department_id=None)
    ns.admin = make_user(db, org, roles=["client_admin"], name="Sam Admin", email="sam@abc.test")
    ns.hr_lead = make_user(db, org, roles=[("dept_compliance_lead", "department", hr.id)], name="Priya Shah", email="priya@abc.test", department_id=hr.id)
    ns.fin_lead = make_user(db, org, roles=[("dept_compliance_lead", "department", fin.id)], name="Tom Reed", email="tom@abc.test", department_id=fin.id)
    ns.contrib = make_user(db, org, roles=[("contributor", "department", hr.id)], name="Cole Contributor", email="cole@abc.test", department_id=hr.id)
    ns.hr_user = make_user(db, org, roles=[], name="Hana Ito", email="hana@abc.test", department_id=hr.id)
    db.commit()

    def as_(user):
        return login_as(client, db, user)

    ns.as_ = as_
    return ns


def new_system(client, **kw):
    body = {"name": "Résumé screening", "type": "vendor_app", "sourcing": "vendor", "stage": "proposed", "purpose": "Ranks applicants for recruiters."} | kw
    r = client.post("/api/v1/register", json=body)
    assert r.status_code == 200, r.text
    return r.json()
