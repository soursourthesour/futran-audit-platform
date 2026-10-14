import pytest

from app.core.clock import utcnow
from app.core.errors import Conflict
from app.engagements import gates
from app.engagements.gates import GATES, advance_stage, gate_status
from app.engagements.service import create_engagement
from app.tenancy.service import assign_role, create_department
from tests.factories import make_org, make_user


@pytest.fixture
def eng(db):
    f = make_org(db, type="futran")
    aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@f.test")
    client = make_org(db, name="ABC Corp")
    e = create_engagement(db, aud, client, name="x")
    e.status = "initiated"
    return aud, client, e


def test_gates_registered_for_stage_1_and_2():
    assert {1, 2} <= set(GATES)


def test_stage1_gate_waits_for_signoff1(db, eng, monkeypatch):
    aud, _, e = eng
    r = gate_status(db, e)
    assert not r.ready and any("Sign-off 1" in u for u in r.unmet)
    with pytest.raises(Conflict) as exc:
        advance_stage(db, aud, e)
    assert e.stage == 1 and exc.value.errors[0]["message"].startswith("Sign-off 1")
    monkeypatch.setattr(gates, "signoff_approved", lambda db, e, n: n == 1)
    advance_stage(db, aud, e)
    assert e.stage == 2


def test_stage2_gate_requires_lead_per_department(db, eng):
    aud, client, e = eng
    e.stage = 2
    r = gate_status(db, e)
    assert not r.ready and r.unmet == ["Set up the client's departments."]
    fin = create_department(db, client, name="Finance")
    hr = create_department(db, client, name="HR")
    create_department(db, client, name="Facilities", in_scope=False)
    lead = make_user(db, client, name="Fay Lead", email="fay@abc.test")
    assign_role(db, lead, "dept_compliance_lead", scope_type="department", scope_id=fin.id)
    contrib = make_user(db, client, name="Hal Staff", email="hal@abc.test")
    assign_role(db, contrib, "contributor", scope_type="department", scope_id=hr.id)
    r = gate_status(db, e)
    assert r.unmet == ["The client has not confirmed the department list.", "HR has no Department Compliance Lead."]
    e.departments_confirmed_at = utcnow()
    db.flush()
    assert gate_status(db, e).unmet == ["HR has no Department Compliance Lead."]
    # a disabled lead does not count
    lead2 = make_user(db, client, name="Hana Lead", email="hana@abc.test")
    assign_role(db, lead2, "dept_compliance_lead", scope_type="department", scope_id=hr.id)
    lead2.status = "disabled"
    assert gate_status(db, e).unmet == ["HR has no Department Compliance Lead."]
    lead2.status = "invited"
    assert gate_status(db, e).ready
    advance_stage(db, aud, e)
    assert e.stage == 3


def test_stage_without_gate_cannot_advance(db, eng):
    aud, _, e = eng
    e.stage = 9
    with pytest.raises(Conflict):
        advance_stage(db, aud, e)


def test_draft_engagement_cannot_advance(db, eng, monkeypatch):
    aud, _, e = eng
    e.status = "draft"
    monkeypatch.setattr(gates, "signoff_approved", lambda db, e, n: True)
    r = gate_status(db, e)
    assert not r.ready and "approved" in r.unmet[0]


def test_gate_and_advance_api(client, db, eng):
    from tests.factories import login_as

    aud, cl, e = eng
    e.stage = 2
    futran = db.get(type(cl), aud.organization_id)
    other = make_user(db, futran, roles=["auditor"], name="Ola Other", email="ola@f.test")
    db.commit()
    login_as(client, db, other)
    assert client.get(f"/api/v1/engagements/{e.id}/gate").status_code == 404  # not on the team
    from app.engagements.models import EngagementTeam

    db.add(EngagementTeam(organization_id=e.client_id, engagement_id=e.id, user_id=aud.id, role="auditor"))
    db.commit()
    login_as(client, db, aud)
    g = client.get(f"/api/v1/engagements/{e.id}/gate").json()
    assert g == {"stage": 2, "stage_name": "Setup", "ready": False, "unmet": ["Set up the client's departments."]}
    r = client.post(f"/api/v1/engagements/{e.id}/advance")
    assert r.status_code == 409 and r.json()["errors"][0]["message"] == "Set up the client's departments."
