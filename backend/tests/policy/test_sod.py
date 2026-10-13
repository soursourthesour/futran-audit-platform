import pytest

from app.auth.deps import build_actor
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement, EngagementTeam
from app.policy.actions import Action as A
from app.policy.authorize import authorize
from app.policy.sod import assert_not_admin_judgment, assert_not_self_approval
from tests.factories import make_department, make_org, make_user


class _S:  # stand-in session object for build_actor
    def __init__(self, user):
        self.user_id = user.id
        self.csrf_token = "x"


def actor_for(db, user):
    return build_actor(db, _S(user))


@pytest.fixture
def world(db):
    futran = make_org(db, type="futran")
    abc = make_org(db, type="client", name="ABC Corp")
    bcd = make_org(db, type="client", name="BCD Inc")
    hr = make_department(db, abc, name="Human Resources")
    fin = make_department(db, abc, name="Finance")
    eng = Engagement(organization_id=abc.id, client_id=abc.id, name="Initial AI governance assessment 2026", status="in_progress")
    eng_b = Engagement(organization_id=bcd.id, client_id=bcd.id, name="LL144 bias audit", status="in_progress")
    db.add_all([eng, eng_b])
    db.flush()
    chief = make_user(db, futran, roles=["chief_auditor"], name="Chief One", email="chief@f.test")
    aud = make_user(db, futran, roles=["auditor"], name="Aud Assigned", email="aud@f.test")
    aud2 = make_user(db, futran, roles=["auditor"], name="Aud Other", email="aud2@f.test")
    admin = make_user(db, futran, roles=["admin"], name="Ad Min", email="admin@f.test")
    db.add(EngagementTeam(organization_id=abc.id, engagement_id=eng.id, user_id=aud.id, role="auditor"))
    caico = make_user(db, abc, roles=["caico"], name="Cai Co", email="caico@abc.test")
    lead = make_user(db, abc, roles=[("dept_compliance_lead", "department", hr.id), ("contributor", "department", hr.id)], name="Priya Shah", email="priya@abc.test")
    caico_b = make_user(db, bcd, roles=["caico"], name="Bee Caico", email="caico@bcd.test")
    db.flush()
    return dict(futran=futran, abc=abc, bcd=bcd, hr=hr, fin=fin, eng=eng, eng_b=eng_b, chief=chief, aud=aud, aud2=aud2, admin=admin, caico=caico, lead=lead, caico_b=caico_b)


def test_auditor_assigned_engagement_allowed(db, world):
    authorize(db, actor_for(db, world["aud"]), A.RECORD_FINDINGS, engagement_id=world["eng"].id)


def test_auditor_unassigned_engagement_hidden(db, world):
    with pytest.raises(NotFound):
        authorize(db, actor_for(db, world["aud2"]), A.RECORD_FINDINGS, engagement_id=world["eng"].id)


def test_chief_sees_all_engagements(db, world):
    authorize(db, actor_for(db, world["chief"]), A.VIEW_ENGAGEMENT, engagement_id=world["eng_b"].id)


def test_cross_tenant_client_gets_not_found(db, world):
    with pytest.raises(NotFound):
        authorize(db, actor_for(db, world["caico_b"]), A.VIEW_ENGAGEMENT, engagement_id=world["eng"].id)
    with pytest.raises(NotFound):
        authorize(db, actor_for(db, world["caico_b"]), A.MANAGE_CLIENT_USERS, org_id=world["abc"].id)


def test_same_tenant_missing_permission_forbidden(db, world):
    with pytest.raises(Forbidden):
        authorize(db, actor_for(db, world["lead"]), A.LAUNCH_ATTESTATION, engagement_id=world["eng"].id)


def test_dept_scope_limits_to_own_department(db, world):
    lead = actor_for(db, world["lead"])
    authorize(db, lead, A.APPROVE_USE_CASE, engagement_id=world["eng"].id, department_id=world["hr"].id)
    with pytest.raises(Forbidden):
        authorize(db, lead, A.APPROVE_USE_CASE, engagement_id=world["eng"].id, department_id=world["fin"].id)


def test_dept_lead_aggregate_only_attestations(db, world):
    lead = actor_for(db, world["lead"])
    authorize(db, lead, A.VIEW_ATTESTATION_AGGREGATES, engagement_id=world["eng"].id, department_id=world["hr"].id)
    with pytest.raises(Forbidden):
        authorize(db, lead, A.VIEW_INDIVIDUAL_ATTESTATIONS, engagement_id=world["eng"].id, department_id=world["hr"].id)


def test_sod_no_self_approval_multi_role(db, world):
    lead = world["lead"]
    with pytest.raises(Forbidden, match="cannot approve"):
        assert_not_self_approval(lead.id, lead.id)
    assert_not_self_approval(world["caico"].id, lead.id)


def test_admin_judgment_blocked(db, world):
    with pytest.raises(Forbidden):
        assert_not_admin_judgment(actor_for(db, world["admin"]))
    with pytest.raises(Forbidden):
        authorize(db, actor_for(db, world["admin"]), A.SET_FINAL_TIER, engagement_id=world["eng"].id)
