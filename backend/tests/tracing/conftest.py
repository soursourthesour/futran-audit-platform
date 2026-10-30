from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.laws.models import Regulation
from app.register.models import GovernanceRoleAssignment, RegisterSystem, RegisterSystemAction
from tests.factories import login_as, make_department, make_org, make_user


@pytest.fixture
def trc(db, client, matrix):
    """Futran (Chief Auditor, Sales Team, auditor) and ABC Corp: CAICO, Client Admin, Executive Sponsor, an HR and a
    Finance Department Compliance Lead, a DPO; a Tier 3 résumé screener (HR), an acting agent (Finance) and a plain tool (HR)."""
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(db)
    f = make_org(db, type="futran")
    ns = SimpleNamespace()
    ns.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    ns.sales = make_user(db, f, roles=["sales_team"], name="Sam Seller", email="sam@futran.test")
    ns.auditor = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    org = make_org(db, name="ABC Corp")
    hr = make_department(db, org, name="Human Resources")
    fin = make_department(db, org, name="Finance")
    ns.org, ns.hr, ns.fin = org, hr, fin
    ns.caico = make_user(db, org, roles=["caico"], name="Maria Lopez", email="maria@abc.test")
    ns.admin = make_user(db, org, roles=["client_admin"], name="Sam Okafor", email="sam@abc.test")
    ns.sponsor = make_user(db, org, roles=["exec_sponsor"], name="Robert Chen", email="robert@abc.test")
    ns.hr_lead = make_user(db, org, roles=[("dept_compliance_lead", "department", hr.id)], name="Priya Shah", email="priya@abc.test", department_id=hr.id)
    ns.fin_lead = make_user(db, org, roles=[("dept_compliance_lead", "department", fin.id)], name="Grace Liu", email="grace@abc.test", department_id=fin.id)
    ns.dpo = make_user(db, org, roles=["dpo"], name="Daniel Kim", email="daniel@abc.test")
    ns.contrib = make_user(db, org, roles=[("contributor", "department", hr.id)], name="Tom Reyes", email="tom@abc.test", department_id=hr.id)
    ns.screening = RegisterSystem(organization_id=org.id, reference="AIS-001", name="Résumé screening", type="vendor_app", sourcing="vendor", department_id=hr.id,
                                  purpose="Ranks job applicants", decision_impact="consequential", risk_tier=3, stage="live")
    ns.agent = RegisterSystem(organization_id=org.id, reference="AIS-002", name="Invoice approval agent", type="agent", sourcing="vendor", department_id=fin.id,
                              purpose="Approves invoices under 5,000 USD", autonomy="acts_with_approval", risk_tier=2, stage="ready_for_go_live", guardrail_policy_ref="Invoices-v1")
    ns.notes = RegisterSystem(organization_id=org.id, reference="AIS-003", name="Meeting notes", type="genai_chat_tool", sourcing="vendor", department_id=hr.id,
                              purpose="Summarises meetings", risk_tier=1, stage="live")
    db.add_all([ns.screening, ns.agent, ns.notes])
    db.flush()
    db.add(RegisterSystemAction(organization_id=org.id, register_system_id=ns.agent.id, action_code="approve_payment"))
    db.commit()
    ns.as_ = lambda user: login_as(client, db, user)
    return ns


def law(db, code: str, pattern: str) -> Regulation:
    from app.regmaster.seed import find_law

    reg = find_law(db, code, pattern)
    assert reg is not None, (code, pattern)
    return reg


def in_scope(db, org, *keys: str) -> None:
    """Put laws in scope for the client through the applicability engine's table (WS-A)."""
    from app.regmaster.models import ClientLawApplicability

    pats = {"eu": ("EU", "2024/1689"), "co": ("US-CO", "26-189"), "certin": ("IN", "CERT-In"), "dpdp": ("IN", "Digital Personal Data"), "ll144": ("US-NYC", "Local Law 144")}
    for k in keys:
        reg = law(db, *pats[k])
        db.add(ClientLawApplicability(organization_id=org.id, regulation_id=reg.id, law_version_id=reg.current_version_id, in_scope=True, reason_text="test"))
    db.commit()


def incident_lead(db, org, user) -> None:
    """Assign `user` as the company-wide AI Incident Response Lead (a governance role, §24.1 row 6)."""
    from app.regmaster.models import RoleCatalog

    role = db.scalar(select(RoleCatalog).where(RoleCatalog.code == "incident_response_lead"))
    db.add(GovernanceRoleAssignment(organization_id=org.id, register_system_id=None, role_id=role.id, status="assigned", user_id=user.id))
    db.commit()


def activate(client, t, systems, plan="per_system", trial=True):
    """Request the add-on as the CAICO and approve it as the Executive Sponsor; returns the subscription."""
    t.as_(t.caico)
    r = client.post("/api/v1/addons/tracing/requests", json={"system_ids": [s.id for s in systems], "plan": plan, "trial": trial, "approver_id": t.sponsor.id})
    assert r.status_code == 200, r.text
    t.as_(t.sponsor)
    r = client.post(f"/api/v1/addons/requests/{r.json()['id']}/decide", json={"approve": True})
    assert r.status_code == 200, r.text
    return r.json()


__all__ = ["activate", "in_scope", "incident_lead", "law"]
