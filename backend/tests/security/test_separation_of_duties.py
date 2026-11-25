"""Separation of duties on the real routes (spec §6, app/policy/sod.py), in the full demo world.

Rule 1: Admin never creates, edits or approves findings or risk tiers.
Rule 2: nobody approves or signs off their own work.

Each self-approval case takes a real item, makes the caller its author or preparer, and calls the approval route as
that caller, who otherwise holds the approval permission. The refusal must be the separation-of-duties refusal (403
with its own message), not a generic permission refusal, so a case cannot pass for the wrong reason.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.auth.deps import Actor
from app.core.errors import Forbidden
from app.policy import sod
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.service import roles_of
from tests.security._world import World

GENERIC_403 = "You do not have permission to do this."


@pytest.fixture(scope="module")
def w(tmp_path_factory):
    world = World(str(tmp_path_factory.mktemp("files")))
    yield world
    world.close()


def user(w, email):
    from app.tenancy.models import User

    return w.db.scalar(select(User).where(User.email == email))


def org_id(w, name):
    from app.tenancy.models import Organization

    return w.db.scalar(select(Organization.id).where(Organization.name == name))


def first(w, model, *where):
    return w.db.scalar(select(model).where(*where).limit(1))


def actor_for(w, u) -> Actor:
    from app.tenancy.models import Organization

    return Actor(user=u, organization=w.db.get(Organization, u.organization_id), roles=roles_of(w.db, u.id))


# ---------------------------------------------------------------- rule 1: Admin and audit judgments
def test_admin_judgment_guard_unit(w):
    admin = actor_for(w, user(w, "admin@futran.demo"))
    with pytest.raises(Forbidden):
        sod.assert_not_admin_judgment(admin)
    sod.assert_not_admin_judgment(actor_for(w, user(w, "auditor1@futran.demo")))  # an auditor passes


def _judgment_routes(w):
    from app.findings.models import DraftFindingLink, Finding
    from app.inventory.models import UseCase
    from app.register.models import BiasTest  # noqa: F401
    from app.remediation.models import RemediationItem
    from app.systems.models import AISystem

    mer = org_id(w, "Meridian GmbH")
    abc = org_id(w, "ABC Corp")
    f = first(w, Finding, Finding.organization_id == mer) or first(w, Finding)
    uc = first(w, UseCase)
    sysm = first(w, AISystem, AISystem.organization_id == mer) or first(w, AISystem)
    link = first(w, DraftFindingLink)
    rem = first(w, RemediationItem)
    return [
        ("POST", f"/api/v1/clients/{mer}/findings", {"title": "Admin finding", "severity": "high"}),
        ("PATCH", f"/api/v1/findings/{f.id}", {"title": "Changed by admin"}),
        ("POST", f"/api/v1/findings/{f.id}/submit", {}),
        ("POST", f"/api/v1/findings/{f.id}/approve", {}),
        ("POST", f"/api/v1/findings/{f.id}/return", {"comment": "x"}),
        ("POST", f"/api/v1/findings/{f.id}/dismiss", {"reason": "x"}),
        ("POST", f"/api/v1/draft-findings/{link.id}/confirm", {}),
        ("POST", f"/api/v1/use-cases/{uc.id}/final-tier", {"tier": 3, "reason": "Admin sets it"}),
        ("PUT", f"/api/v1/systems/{sysm.id}/score/override", {"rating": "low", "reason": "Admin override"}),
        ("PUT", f"/api/v1/systems/{sysm.id}/score/domains/governance", {"score": 4}),
        ("POST", f"/api/v1/systems/{sysm.id}/score/override/review", {"decision": "approve"}),
        ("POST", f"/api/v1/remediation/{rem.id}/verify", {}),
        ("POST", f"/api/v1/remediation/{rem.id}/close", {}),
        ("POST", f"/api/v1/clients/{abc}/findings", {"title": "Admin finding", "severity": "high"}),
    ]


def test_admin_cannot_set_tiers_or_findings(w):
    """§6 rule 1 on every route that creates, edits, approves or rates a finding, tier or score."""
    c = w.login(user(w, "admin@futran.demo"))
    wrong = []
    for method, url, body in _judgment_routes(w):
        r = c.request(method, url, json=body)
        if r.status_code != 403:
            wrong.append(f"{method} {url} as Admin → {r.status_code} {r.text[:150]}")
    assert wrong == []


# ---------------------------------------------------------------- rule 2: no self-approval
def test_self_approval_guard_unit():
    with pytest.raises(Forbidden):
        sod.assert_not_self_approval("u1", None, "u1")
    sod.assert_not_self_approval("u1", None, "u2")


def _case_finding(w):
    """The Chief Auditor wrote and submitted a finding; it is routed to them for approval."""
    from app.engagements.models import Engagement
    from app.findings.models import Finding

    chief = user(w, "chief@futran.demo")
    e = first(w, Engagement, Engagement.client_id == org_id(w, "Meridian GmbH"), Engagement.status == "in_progress")
    f = Finding(organization_id=e.client_id, engagement_id=e.id, ref="F-YAMA-1", title="Self-approval probe", severity="medium", status="submitted",
                author_id=chief.id, submitted_by=chief.id, created_by=chief.id, review_role="chief_auditor", origin="manual")
    w.db.add(f)
    w.db.commit()
    return chief, "POST", f"/api/v1/findings/{f.id}/approve", {}


def _case_signoff(w):
    """Meridian's CAICO prepared a sign-off that a CAICO signs, and another CAICO exists to sign it."""
    from app.engagements.models import Engagement
    from app.signoffs.service import create_sign_off
    from tests.factories import make_user
    from app.tenancy.models import Organization

    mer = w.db.get(Organization, org_id(w, "Meridian GmbH"))
    katrin = user(w, "katrin.vogel@meridian.example")
    if user(w, "second.caico@meridian.example") is None:
        make_user(w.db, mer, roles=["caico"], name="Second Caico", email="second.caico@meridian.example")
    e = first(w, Engagement, Engagement.client_id == mer.id, Engagement.status == "in_progress")
    so = create_sign_off(w.db, e, 3, preparer_id=katrin.id, required_roles=["caico"])
    w.db.commit()
    return katrin, "POST", f"/api/v1/signoffs/{so.id}/sign", {"typed_name": katrin.name}


def _case_use_case(w):
    """A Department Compliance Lead created and submitted a use case in their own department, then approves it."""
    from app.engagements.models import Engagement
    from app.inventory.models import UseCase
    from app.tenancy.models import RoleAssignment

    aarav = user(w, "aarav.menon@meridian.example")
    dept = w.db.scalar(select(RoleAssignment.scope_id).where(RoleAssignment.user_id == aarav.id, RoleAssignment.role == "dept_compliance_lead"))
    e = first(w, Engagement, Engagement.client_id == aarav.organization_id, Engagement.status == "in_progress")
    uc = UseCase(organization_id=e.client_id, engagement_id=e.id, name="Self-approval probe", department_id=dept, status="submitted",
                 created_by=aarav.id, submitted_by=aarav.id, submitted_at=datetime.utcnow())
    w.db.add(uc)
    w.db.commit()
    return aarav, "POST", f"/api/v1/use-cases/{uc.id}/review", {"approve": True}


def _case_go_live(w):
    """ABC's CAICO submitted a register system for go-live, then approves it."""
    from app.register.models import RegisterSystem

    maria = user(w, "maria.lopez@abccorp.example")
    s = first(w, RegisterSystem, RegisterSystem.organization_id == maria.organization_id, RegisterSystem.stage == "ready_for_go_live")
    s.go_live_requested_by, s.go_live_requested_at = maria.id, datetime.utcnow()
    w.db.commit()
    return maria, "POST", f"/api/v1/register/{s.id}/go-live/decide", {"approve": True}


def _case_system_addition(w):
    """The Engagement Manager asked to add a system to the scope, then approves the request."""
    from app.engagements.models import Engagement
    from app.systems.models import SystemAdditionRequest

    em = user(w, "em@futran.demo")
    e = first(w, Engagement, Engagement.client_id == org_id(w, "Meridian GmbH"), Engagement.status == "in_progress")
    req = SystemAdditionRequest(organization_id=e.client_id, engagement_id=e.id, requested_by=em.id, payload={"name": "Probe system"}, reason="Probe",
                                status="pending", created_by=em.id)
    w.db.add(req)
    w.db.commit()
    return em, "POST", f"/api/v1/system-requests/{req.id}/decide", {"approve": True}


def _case_engagement(w):
    """The Chief Auditor submitted Northwind's engagement for approval, then approves it."""
    from app.demo.seed_demo import APPROVAL
    from app.engagements.models import Engagement

    chief = user(w, "chief@futran.demo")
    nw = org_id(w, "Northwind Logistics")
    e = first(w, Engagement, Engagement.client_id == nw, Engagement.status == "pending_approval")
    e.submitted_by = chief.id
    w.db.commit()
    return chief, "POST", f"/api/v1/clients/{nw}/approve", APPROVAL


def _case_policy(w):
    """ABC's CAICO wrote a policy and sent it for approval, then approves and publishes it."""
    from app.policies.models import PolicyDocument

    maria = user(w, "maria.lopez@abccorp.example")
    p = first(w, PolicyDocument, PolicyDocument.organization_id == maria.organization_id, PolicyDocument.status == "awaiting_approval")
    p.created_by = p.updated_by = p.submitted_by = maria.id
    w.db.commit()
    return maria, "POST", f"/api/v1/policies/{p.id}/approve", {}


def _case_intro_letter(w):
    """The Chief Auditor drafted Meridian's intro letter (the demo does exactly this), then approves it."""
    from app.regmaster.models import IntroLetter

    chief = user(w, "chief@futran.demo")
    mer = org_id(w, "Meridian GmbH")
    letter = first(w, IntroLetter, IntroLetter.organization_id == mer, IntroLetter.status == "draft")
    assert letter.created_by == chief.id
    return chief, "POST", f"/api/v1/clients/{mer}/letters/{letter.id}/approve", {}


def _case_opportunity(w):
    """The Chief Auditor owns an offer to a client, then approves it."""
    from app.sales.models import Opportunity

    chief = user(w, "chief@futran.demo")
    o = first(w, Opportunity, Opportunity.organization_id == org_id(w, "Northwind Logistics"), Opportunity.service_kind == "training")
    o.owner_id = o.created_by = chief.id
    w.db.commit()
    return chief, "POST", f"/api/v1/opportunities/{o.id}/approve", {"decision": "approve", "note": "Self-approved"}


SELF_APPROVAL = [
    pytest.param(_case_finding, Action.APPROVE_FINDINGS, id="finding approve"),
    pytest.param(_case_signoff, Action.VIEW_ENGAGEMENT, id="client sign-off"),
    pytest.param(_case_use_case, Action.APPROVE_USE_CASE, id="use case approve"),
    pytest.param(_case_go_live, Action.APPROVE_GO_LIVE, id="register go-live"),
    pytest.param(_case_system_addition, Action.APPROVE_SYSTEM_ADDITION, id="system addition"),
    pytest.param(_case_engagement, Action.APPROVE_ENGAGEMENT, id="engagement approve"),
    pytest.param(_case_policy, Action.APPROVE_POLICIES, id="policy approve",
                 marks=pytest.mark.xfail(strict=True, reason="FINDING Y03: a CAICO approves and publishes a policy they wrote and submitted")),
    pytest.param(_case_intro_letter, Action.APPROVE_INTRO_LETTER, id="intro letter approve",
                 marks=pytest.mark.xfail(strict=True, reason="FINDING Y04: the Chief Auditor approves an intro letter they drafted")),
    pytest.param(_case_opportunity, Action.APPROVE_OPPORTUNITY, id="opportunity approve",
                 marks=pytest.mark.xfail(strict=True, reason="FINDING Y05: the Chief Auditor approves an offer they own")),
]


@pytest.mark.parametrize("case,action", SELF_APPROVAL)
def test_nobody_approves_their_own_work(w, case, action):
    u, method, url, body = case(w)
    a = actor_for(w, u)
    # precondition: the caller holds the approval permission, so only separation of duties can refuse them
    authorize(w.db, a, action, list_view=True) if not a.is_futran else None
    if a.is_futran:
        from app.policy.matrix import scopes_for

        assert scopes_for(a.role_names, action), f"{u.email} lacks {action}; the case would pass for the wrong reason"
    r = w.login(u).request(method, url, json=body)
    assert r.status_code == 403, f"{u.email} approved their own item: {method} {url} → {r.status_code} {r.text[:200]}"
    assert r.json()["detail"] != GENERIC_403, f"refused, but by the plain permission check rather than separation of duties: {r.text[:200]}"
