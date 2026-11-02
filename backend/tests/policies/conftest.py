"""A client with an engagement whose governance request promises an AI acceptable use policy (a "Will create" commitment)."""
from datetime import date, timedelta

import pytest

from app.engagements.models import Engagement
from app.governance.models import Commitment, GovernanceItem, GovernanceRequest
from app.mail.models import DirectoryPerson
from tests.factories import make_department, make_org, make_user


@pytest.fixture
def world(db, settings, tmp_path, client):
    settings.file_store = f"local:{tmp_path}"
    client.app.state.settings = settings
    futran = make_org(db, type="futran")
    org = make_org(db, name="ABC Corp")
    other = make_org(db, name="Other Co")
    hr = make_department(db, org, name="HR")
    fin = make_department(db, org, name="Finance")
    w = {
        "org": org, "other": other, "futran": futran, "hr": hr, "fin": fin,
        "caico": make_user(db, org, roles=["caico"], name="Maria Lopez", email="maria@abc.test"),
        "admin": make_user(db, org, roles=["client_admin"], name="Sam Okafor", email="sam@abc.test"),
        "dpo": make_user(db, org, roles=["dpo"], name="Daniel Kim", email="daniel@abc.test"),
        "contrib": make_user(db, org, roles=[("contributor", "department", hr.id)], name="Tom Reyes", email="tom@abc.test"),
        "other_caico": make_user(db, other, roles=["caico"], name="Olga Other", email="olga@other.test"),
        "chief": make_user(db, futran, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test"),
        "chief2": make_user(db, futran, roles=["chief_auditor"], name="Dan Chief", email="dan@futran.test"),
        "aud": make_user(db, futran, roles=["auditor"], name="Alex Auditor", email="alex@futran.test"),
        "sales": make_user(db, futran, roles=["sales_team"], name="Sam Seller", email="sales@futran.test"),
    }
    e = Engagement(organization_id=org.id, client_id=org.id, name="ABC Corp AI governance audit", audit_ref="FSL-AI-AUD-2026-001", status="in_progress", stage=4,
                   period_start=date(2026, 1, 1), period_end=date(2026, 6, 30))
    db.add(e)
    db.flush()
    req = GovernanceRequest(organization_id=org.id, engagement_id=e.id, status="submitted", items_selected=["GD-04"])
    db.add(req)
    db.flush()
    item = GovernanceItem(organization_id=org.id, request_id=req.id, engagement_id=e.id, catalog_code="GD-04", kind="document", title="AI acceptable use policy",
                          status="planned", target_date=date.today() + timedelta(days=45), interim_owner="Maria Lopez")
    db.add(item)
    db.flush()
    c = Commitment(organization_id=org.id, engagement_id=e.id, source="governance_document", source_id=item.id, description="Create AI acceptable use policy",
                   target_date=item.target_date, owner="Maria Lopez", status="open")
    db.add(c)
    for name, email, dept in (("Hannah Brooks", "hannah@abc.test", hr), ("Aisha Rahman", "aisha@abc.test", fin), ("Peter Novak", "peter@abc.test", fin)):
        db.add(DirectoryPerson(organization_id=org.id, email=email, name=name, source="manual", status="active", department_id=dept.id))
    db.commit()
    w |= {"engagement": e, "commitment": c, "item": item}
    return w
