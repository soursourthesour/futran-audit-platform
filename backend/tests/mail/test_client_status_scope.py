"""Y06: an auditor reads a client's email connection status only on an engagement they work on. For a client still in
set-up (draft, waiting for approval or returned) that means the person who created it or edited it, or its team."""
import pytest

from app.engagements.models import Engagement, EngagementTeam
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def d(db):
    f = make_org(db, type="futran", name="Futran Solutions")
    c = make_org(db, type="client", name="Draft Co")
    w = {
        "c": c,
        "author": make_user(db, f, roles=["auditor"], name="Al Author", email="al@futran.test"),
        "editor": make_user(db, f, roles=["auditor"], name="Ed Editor", email="ed@futran.test"),
        "teammate": make_user(db, f, roles=["auditor"], name="Tia Team", email="tia@futran.test"),
        "stranger": make_user(db, f, roles=["auditor"], name="Sid Stranger", email="sid@futran.test"),
        "chief": make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test"),
    }
    db.flush()
    e = Engagement(organization_id=c.id, client_id=c.id, name="AI audit", status="draft", stage=1, created_by=w["author"].id,
                   wizard_state={"editors": [w["editor"].id]})
    db.add(e)
    db.flush()
    db.add(EngagementTeam(organization_id=c.id, engagement_id=e.id, user_id=w["teammate"].id, role="auditor"))
    db.commit()
    return w | {"e": e}


def _status(client, db, u, cid):
    login_as(client, db, u)
    return client.get(f"/api/v1/mail/clients/{cid}/status").status_code


@pytest.mark.parametrize("status", ["draft", "pending_approval", "returned"])
def test_an_auditor_not_on_the_draft_gets_not_found(client, db, d, status):
    d["e"].status = status
    db.commit()
    assert _status(client, db, d["stranger"], d["c"].id) == 404


@pytest.mark.parametrize("who", ["author", "editor", "teammate", "chief"])
def test_the_people_setting_the_client_up_see_it(client, db, d, who):
    assert _status(client, db, d[who], d["c"].id) == 200
