"""Independence rule I-3 (and I-2's recorded separate team), spec §4.7: the Futran person who holds the client's
Fractional AI Governance Officer role, or who the Chief Auditor recorded as the separate delivery team, can't be added
to that client's audit team in any role."""
import pytest

from app.core.errors import Conflict
from app.engagements import team
from tests.factories import make_org, make_user


@pytest.fixture
def world(db, monkeypatch):
    from app.engagements.models import Engagement

    f = make_org(db, type="futran")
    officer = make_user(db, f, roles=["auditor"], name="Olu Officer", email="olu@futran.test")
    other = make_user(db, f, roles=["auditor"], name="Ann Auditor", email="ann@futran.test")
    chief = make_user(db, f, roles=["chief_auditor"], name="Cy Chief", email="cy@futran.test")
    client = make_org(db, name="Harbor Health Group", status="active")
    e = Engagement(organization_id=client.id, client_id=client.id, name="Harbor audit", status="draft", stage=1)
    db.add(e)
    db.flush()
    from app.commercial import handoff

    monkeypatch.setattr(handoff, "separate_team_user_ids", lambda db, client_id: {officer.id} if client_id == client.id else set())
    return client, e, officer, other, chief


def test_check_refuses_the_separate_team(db, world):
    client, _, officer, other, _ = world
    with pytest.raises(Conflict) as exc:
        team.check_separate_team(db, client.id, officer.id)
    assert "Olu Officer" in exc.value.detail and "audit team" in exc.value.detail
    team.check_separate_team(db, client.id, other.id)  # anyone else is fine


def test_wizard_team_save_and_validation_refuse_them(db, world):
    from app.engagements import wizard
    from app.engagements.models import EngagementTeam

    client, e, officer, other, chief = world
    errors = wizard._save_team(db, chief, e, [{"user_id": officer.id, "role": "auditor", "conflict_confirmed": True},
                                              {"user_id": other.id, "role": "auditor", "conflict_confirmed": True}])
    assert any("Olu Officer" in x["message"] for x in errors)
    db.add(EngagementTeam(organization_id=client.id, engagement_id=e.id, user_id=officer.id, role="auditor"))  # saved some other way
    db.flush()
    assert any("Olu Officer" in x["message"] for x in wizard._validate_team(db, e))
