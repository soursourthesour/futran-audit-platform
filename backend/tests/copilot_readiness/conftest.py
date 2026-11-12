"""World for G-07: a client on a `copilot_readiness` engagement with an auditor (the Microsoft practice) and an
Engagement Manager on the team, the client's CAICO and Client Admin, and outsiders."""
from types import SimpleNamespace

import pytest

from tests.factories import login_as, make_org, make_user

LICENCES = """Report Refresh Date,User Principal Name,Display Name,Department,Has Copilot License,Last Activity Date of Microsoft 365 Copilot (UTC)
2026-11-08,ana@acme.example,Ana,HR,Yes,2026-11-05
2026-11-08,bo@acme.example,Bo,HR,Yes,2026-09-01
2026-11-08,cy@acme.example,Cy,Finance,Yes,
2026-11-08,di@acme.example,Di,Sales,Yes,2026-11-07
2026-11-08,ed@acme.example,Ed,Sales,No,
"""

PURVIEW = """Site name,Site URL,Site owner,Sensitive items,Label coverage,Sharing scope,Last activity
HR · Candidate files,https://acme.sharepoint.com/sites/hr-candidates,HR IT,"2,140",12%,Everyone except external users,2026-11-01
Finance · Payroll archive,https://acme.sharepoint.com/sites/payroll,Finance,860,0%,Organization-wide link,2025-04-30
Sales · Client contracts,https://acme.sharepoint.com/sites/contracts,Sales ops,310,65%,Specific people,2026-10-20
Marketing · Public assets,https://acme.sharepoint.com/sites/marketing,,0,,Organization-wide,2026-11-02
"""

SAM = """Site URL,Site name,Site owner,Sharing link type,Sensitivity label
https://acme.sharepoint.com/sites/payroll,Finance · Payroll archive,Finance,Anyone link,None
https://acme.sharepoint.com/sites/board,Board papers,Company secretary,Everyone,Confidential
"""


@pytest.fixture
def cp(db, client):
    from app.engagements.models import Engagement, EngagementTeam

    f = make_org(db, type="futran")
    ns = SimpleNamespace(client=client, db=db, futran=f)
    ns.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    ns.auditor = make_user(db, f, roles=["auditor"], name="Mia Practice", email="mia@futran.test")
    ns.em = make_user(db, f, roles=["engagement_manager"], name="Eve Manager", email="eve@futran.test")
    ns.outsider = make_user(db, f, roles=["auditor"], name="Olu Outside", email="olu@futran.test")
    ns.org = make_org(db, name="Acme Staffing LLC", status="active")
    ns.caico = make_user(db, ns.org, roles=["caico"], name="Maria Lopez", email="maria@acme.example")
    ns.client_admin = make_user(db, ns.org, roles=["client_admin"], name="Sam Okafor", email="sam@acme.example")
    ns.other = make_org(db, name="Other Client", status="active")
    ns.other_caico = make_user(db, ns.other, roles=["caico"], name="Otto Other", email="otto@other.example")
    e = Engagement(organization_id=ns.org.id, client_id=ns.org.id, name="Microsoft 365 Copilot readiness", type="copilot_readiness", status="in_progress", stage=3,
                   audit_ref="FSL-AI-AUD-2026-960")
    plain = Engagement(organization_id=ns.org.id, client_id=ns.org.id, name="Initial assessment", type="initial_assessment", status="in_progress", stage=3,
                       audit_ref="FSL-AI-AUD-2026-961")
    db.add_all([e, plain])
    db.flush()
    for u, role in ((ns.auditor, "auditor"), (ns.em, "engagement_manager")):
        for eng in (e, plain):
            db.add(EngagementTeam(organization_id=ns.org.id, engagement_id=eng.id, user_id=u.id, role=role))
    db.commit()
    ns.engagement, ns.plain = e, plain
    ns.url = f"/api/v1/e/{e.id}/copilot"
    ns.as_ = lambda user: login_as(client, db, user)
    return ns


def upload(cp, kind, text, name=None):
    return cp.client.post(f"{cp.url}/imports/{kind}", files={"file": (name or f"{kind}.csv", text.encode(), "text/csv")})
