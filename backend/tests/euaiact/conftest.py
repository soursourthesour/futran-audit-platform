"""World for G-08: a client with EU-exposed register systems, an `eu_ai_act_readiness` engagement, its audit team with a
Legal/Compliance Reviewer, and outsiders (an unassigned auditor, another client)."""
from types import SimpleNamespace

import pytest

from tests.factories import login_as, make_org, make_user


@pytest.fixture
def eu(db, client):
    from app.engagements.models import Engagement, EngagementTeam
    from app.register.models import RegisterSystem

    f = make_org(db, type="futran")
    ns = SimpleNamespace(client=client, db=db, futran=f)
    ns.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    ns.auditor = make_user(db, f, roles=["auditor"], name="Asha Rao", email="asha@futran.test")
    ns.em = make_user(db, f, roles=["engagement_manager"], name="Eve Manager", email="eve@futran.test")
    ns.legal = make_user(db, f, roles=["legal_reviewer"], name="Jordan Ellis", email="jordan@futran.test")
    ns.legal_outside = make_user(db, f, roles=["legal_reviewer"], name="Lee Other", email="lee@futran.test")
    ns.outsider = make_user(db, f, roles=["auditor"], name="Olu Outside", email="olu@futran.test")
    ns.org = make_org(db, name="Northbank Credit Union", status="active")
    ns.caico = make_user(db, ns.org, roles=["caico"], name="Ines Maier", email="ines@northbank.example")
    ns.client_admin = make_user(db, ns.org, roles=["client_admin"], name="Sam Okafor", email="sam@northbank.example")
    ns.other = make_org(db, name="Other Client", status="active")
    ns.other_caico = make_user(db, ns.other, roles=["caico"], name="Otto Other", email="otto@other.example")
    e = Engagement(organization_id=ns.org.id, client_id=ns.org.id, name="EU AI Act readiness", type="eu_ai_act_readiness", status="in_progress", stage=4,
                   audit_ref="FSL-AI-AUD-2026-950")
    plain = Engagement(organization_id=ns.org.id, client_id=ns.org.id, name="Initial assessment", type="initial_assessment", status="in_progress", stage=4,
                       audit_ref="FSL-AI-AUD-2026-951")
    db.add_all([e, plain])
    db.flush()
    for u, role in ((ns.auditor, "auditor"), (ns.em, "engagement_manager"), (ns.legal, "legal_reviewer")):
        db.add(EngagementTeam(organization_id=ns.org.id, engagement_id=e.id, user_id=u.id, role=role))
    ns.credit = RegisterSystem(organization_id=ns.org.id, reference="AIS-001", name="Credit decision model", type="in_house_model", sourcing="in_house",
                               decision_impact="consequential", stage="live", run_location={"country": "DE"})
    ns.hiring = RegisterSystem(organization_id=ns.org.id, reference="AIS-002", name="Hiring screening", type="vendor_app", sourcing="vendor",
                               decision_impact="consequential", stage="live", data_locations=[{"country": "FR"}, {"country": "US", "region": "US-NY"}])
    ns.chatbot = RegisterSystem(organization_id=ns.org.id, reference="AIS-003", name="Member chatbot", type="genai_chat_tool", sourcing="vendor", stage="live")
    ns.foreign = RegisterSystem(organization_id=ns.other.id, reference="AIS-001", name="Other's model", type="in_house_model", sourcing="in_house", stage="live")
    db.add_all([ns.credit, ns.hiring, ns.chatbot, ns.foreign])
    db.commit()
    ns.engagement, ns.plain = e, plain
    ns.as_ = lambda user: login_as(client, db, user)
    return ns
