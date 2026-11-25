"""BUG-05: the Chief Auditor adds a team member (for example a QA Reviewer) to a running engagement, with the same
conflict-of-interest confirmation and independence checks the new-client wizard uses."""
import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.engagements.models import Engagement, EngagementTeam
from app.tenancy.models import Organization
from tests.factories import login_as, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401


@pytest.fixture
def running(db, inv, people):
    cid, e, *_ = inv
    futran = db.get(Organization, people["chief"].organization_id)
    people["qa"] = make_user(db, futran, roles=["qa_reviewer"], name="Quinn Reviewer", email="quinn@futran.test")
    people["admin"] = make_user(db, futran, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    db.get(Engagement, e.id).stage = 5
    db.commit()
    assert db.get(Engagement, e.id).status in ("initiated", "in_progress")
    return cid, db.get(Engagement, e.id)


def _add(client, cid, user, role="qa_reviewer", confirmed=True):
    return client.post(f"/api/v1/clients/{cid}/team", json={"user_id": user.id, "role": role, "conflict_confirmed": confirmed})


def test_chief_auditor_adds_a_qa_reviewer_so_their_own_finding_can_be_submitted(client, db, running, people):
    cid, e = running
    login_as(client, db, people["chief"])
    f = client.post(f"/api/v1/clients/{cid}/findings", json={"title": "Chief's finding", "severity": "medium", "description": "x", "recommended_remediation": "y"}).json()
    r = client.post(f"/api/v1/findings/{f['id']}/submit")
    assert r.status_code == 409 and "QA Reviewer" in r.json()["detail"]

    r = _add(client, cid, people["qa"])
    assert r.status_code == 200, r.text
    assert any(p["name"] == "Quinn Reviewer" and p["roles"] == ["qa_reviewer"] for p in r.json()["team"])
    row = db.scalar(select(EngagementTeam).where(EngagementTeam.engagement_id == e.id, EngagementTeam.user_id == people["qa"].id))
    assert row.role == "qa_reviewer" and row.conflict_confirmed_at is not None and row.conflict_confirmed_roles == ["qa_reviewer"]
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.engagement_id == e.id)))
    assert {"team.member_added", "team.conflict_confirmed"} <= actions

    r = client.post(f"/api/v1/findings/{f['id']}/submit")
    assert r.status_code == 200 and r.json()["review_role"] == "qa_reviewer"
    assert any(m["name"] == "Quinn Reviewer" for m in client.get(f"/api/v1/clients/{cid}").json()["team"])


def test_only_the_chief_auditor_may_add(client, db, running, people):
    cid, _ = running
    login_as(client, db, people["aud"])
    assert _add(client, cid, people["qa"]).status_code == 403
    login_as(client, db, people["admin"])
    assert _add(client, cid, people["qa"]).status_code in (403, 404)


def test_the_conflict_of_interest_confirmation_is_required(client, db, running, people):
    cid, _ = running
    login_as(client, db, people["chief"])
    r = _add(client, cid, people["qa"], confirmed=False)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "conflict_confirmed"


@pytest.mark.parametrize("who,role,field", [
    ("aud2", "qa_reviewer", "user_id"),   # not a QA Reviewer or Chief Auditor
    ("admin", "auditor", "user_id"),      # administrators are never on an audit team
    ("qa", "chief_auditor", "role"),      # the Lead Auditor is not changed here
    ("qa", "partner", "role"),            # not a team role
])
def test_people_and_roles_the_wizard_would_refuse(client, db, running, people, who, role, field):
    cid, _ = running
    login_as(client, db, people["chief"])
    r = _add(client, cid, people[who], role=role)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == field, r.text


def test_the_chief_auditor_cannot_be_the_qa_reviewer_of_their_own_engagement(client, db, running, people):
    cid, _ = running
    login_as(client, db, people["chief"])
    r = _add(client, cid, people["chief"])
    assert r.status_code == 422 and "Chief Auditor" in r.json()["errors"][0]["message"]


def test_someone_already_in_that_role_is_refused(client, db, running, people):
    cid, _ = running
    login_as(client, db, people["chief"])
    assert _add(client, cid, people["qa"]).status_code == 200
    assert _add(client, cid, people["qa"]).status_code == 409


def test_the_separate_delivery_team_is_refused(client, db, running, people, monkeypatch):
    from app.commercial import handoff

    cid, _ = running
    monkeypatch.setattr(handoff, "separate_team_user_ids", lambda db, client_id: {people["qa"].id})
    login_as(client, db, people["chief"])
    r = _add(client, cid, people["qa"])
    assert r.status_code == 409 and "cannot be on its audit team" in r.json()["detail"]


def test_a_draft_or_closed_engagement_is_refused(client, db, running, people):
    cid, e = running
    login_as(client, db, people["chief"])
    for status in ("draft", "completed"):
        e.status = status
        db.commit()
        assert _add(client, cid, people["qa"]).status_code == 409


def test_a_client_user_cannot_add(client, db, running, people, inv):
    cid, _, maria, *_ = inv
    login_as(client, db, maria)
    assert _add(client, cid, people["qa"]).status_code in (403, 404)
