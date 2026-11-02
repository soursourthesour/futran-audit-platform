"""A small audit world for comments (F18) and the public API (F17), built directly in the database so the tests stay fast.

Futran: Chief Auditor and auditor on the ABC engagement, a second auditor who is not. ABC Corp (stage 7, findings shared):
CAICO, an HR Department Compliance Lead, a Finance lead. XYZ Inc: a second client with its own CAICO.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.docrequests.models import EvidenceRequest
from app.engagements.models import Engagement, EngagementTeam
from app.findings.models import Finding
from app.questionnaire.models import Question, Response, TemplateVersion
from app.remediation.models import ManagementResponse, RemediationItem
from app.systems.models import AISystem
from tests.factories import login_as, make_department, make_org, make_user


def _engagement(db, org, ref, stage=7):
    e = Engagement(organization_id=org.id, client_id=org.id, name=f"{org.name} AI audit", audit_ref=ref, status="active", stage=stage)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def w(db, client):
    ns = SimpleNamespace()
    f = make_org(db, type="futran")
    ns.futran = f
    ns.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    ns.aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    ns.aud2 = make_user(db, f, roles=["auditor"], name="Bea Auditor", email="bea@futran.test")
    ns.admin = make_user(db, f, roles=["admin"], name="Fran Admin", email="fran@futran.test")
    org = make_org(db, name="ABC Corp")
    ns.org = org
    ns.hr = make_department(db, org, name="Human Resources")
    ns.fin = make_department(db, org, name="Finance")
    ns.caico = make_user(db, org, roles=["caico"], name="Maria Lopez", email="maria@abc.test")
    ns.cadmin = make_user(db, org, roles=["client_admin"], name="Sam Okafor", email="sam@abc.test")
    ns.hr_lead = make_user(db, org, roles=[("dept_compliance_lead", "department", ns.hr.id)], name="Priya Shah", email="priya@abc.test", department_id=ns.hr.id)
    ns.fin_lead = make_user(db, org, roles=[("dept_compliance_lead", "department", ns.fin.id)], name="Grace Liu", email="grace@abc.test", department_id=ns.fin.id)
    other = make_org(db, name="XYZ Inc")
    ns.other = other
    ns.x_caico = make_user(db, other, roles=["caico"], name="Xavier Young", email="xavier@xyz.test")
    ns.x_admin = make_user(db, other, roles=["client_admin"], name="Xena Admin", email="xena@xyz.test")

    e = _engagement(db, org, "FAP-2026-001")
    ns.e = e
    for u, role in ((ns.chief, "chief_auditor"), (ns.aud, "auditor")):
        db.add(EngagementTeam(organization_id=org.id, engagement_id=e.id, user_id=u.id, role=role))
    ns.sys = AISystem(organization_id=org.id, engagement_id=e.id, name="Résumé screening", reference_id="SYS-001", department_id=ns.hr.id, built_by="vendor")
    db.add(ns.sys)
    tv = TemplateVersion(name="Futran AI Audit Template", version="t1")
    db.add(tv)
    db.flush()
    q = Question(template_version_id=tv.id, code="6.2.01", section="6", sub_section="6.2", section_title="Bias", scope="system", label="Bias testing performed", type="single")
    db.add(q)
    db.flush()
    ns.resp = Response(organization_id=org.id, engagement_id=e.id, ai_system_id=ns.sys.id, question_id=q.id, value="no", status="answered")
    ns.draft = Finding(organization_id=org.id, engagement_id=e.id, ref="F-002", ai_system_id=ns.sys.id, title="No ongoing bias monitoring", severity="medium", status="draft", author_id=ns.aud.id)
    ns.finding = Finding(organization_id=org.id, engagement_id=e.id, ref="F-001", ai_system_id=ns.sys.id, title="No bias test before go-live", severity="high", status="approved",
                         author_id=ns.aud.id, description="The screening tool went live without a bias test.", recommended_remediation="Commission an independent bias audit.")
    db.add_all([ns.resp, ns.draft, ns.finding])
    db.flush()
    ns.mresp = ManagementResponse(organization_id=org.id, engagement_id=e.id, finding_id=ns.finding.id, response="agree", planned_action="Commission an audit.",
                                  owner_user_id=ns.hr_lead.id, due_date=date.today() + timedelta(days=30))
    db.add(ns.mresp)
    db.flush()
    ns.item = RemediationItem(organization_id=org.id, engagement_id=e.id, finding_id=ns.finding.id, response_id=ns.mresp.id, action="Commission an independent bias audit.",
                              owner_user_id=ns.hr_lead.id, due_date=date.today() + timedelta(days=30), status="open")
    ns.er = EvidenceRequest(organization_id=org.id, engagement_id=e.id, ref="ER-001", ai_system_id=ns.sys.id, description="Last bias test report", requested_by=ns.aud.id,
                            owner_user_id=ns.hr_lead.id, due_date=date.today() + timedelta(days=7))
    db.add_all([ns.item, ns.er])

    ns.xe = _engagement(db, other, "FAP-2026-002")
    ns.x_finding = Finding(organization_id=other.id, engagement_id=ns.xe.id, ref="F-001", title="XYZ finding", severity="low", status="approved")
    db.add(ns.x_finding)
    db.commit()
    ns.as_ = lambda user: login_as(client, db, user)
    return ns
