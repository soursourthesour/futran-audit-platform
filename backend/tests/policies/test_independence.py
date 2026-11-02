"""Independence rule (spec §21 F7, §21.1): the Futran team that wrote or tailored a client's policy cannot be Lead Auditor
on a later engagement for that client."""
import pytest
from sqlalchemy import select

from app.core.errors import Conflict
from app.engagements.models import Engagement, EngagementTeam
from app.sales.models import Opportunity
from tests.factories import login_as

API = "/api/v1"


@pytest.fixture
def tailored(client, db, world):
    login_as(client, db, world["caico"])
    p = client.post(f"{API}/policies", json={"template_code": "acceptable_use", "commitment_id": world["commitment"].id}).json()
    r = client.post(f"{API}/policies/{p['id']}/futran-review", json={"note": "Please tailor it to our HR tools."})
    assert r.status_code == 200 and r.json()["futran_review_requested_at"]
    o = db.scalar(select(Opportunity).where(Opportunity.trigger == "policy_review"))
    assert o is not None and o.organization_id == world["org"].id and o.service_kind == "advisory" and o.needs_ca_approval
    assert client.post(f"{API}/policies/{p['id']}/futran-review", json={}).status_code == 409
    login_as(client, db, world["chief"])
    listed = client.get(f"{API}/futran/policies").json()
    assert [x["id"] for x in listed["policies"]] == [p["id"]] and listed["policies"][0]["client_name"] == "ABC Corp"
    r = client.put(f"{API}/futran/policies/{p['id']}/team", json={"user_ids": [world["chief"].id, world["aud"].id]})
    assert r.status_code == 200 and {m["name"] for m in r.json()["futran_team"]} == {"Cara Chief", "Alex Auditor"}
    return p


def test_only_the_chief_auditor_records_the_team(client, db, world, tailored):
    login_as(client, db, world["sales"])
    assert client.put(f"{API}/futran/policies/{tailored['id']}/team", json={"user_ids": []}).status_code in (403, 404)
    login_as(client, db, world["caico"])
    assert client.put(f"{API}/futran/policies/{tailored['id']}/team", json={"user_ids": []}).status_code == 404
    login_as(client, db, world["chief"])
    r = client.put(f"{API}/futran/policies/{tailored['id']}/team", json={"user_ids": [world["caico"].id]})
    assert r.status_code == 422


def test_author_cannot_be_lead_auditor_on_a_later_engagement(client, db, world, tailored):
    from app.engagements.team import check_lead_independence

    with pytest.raises(Conflict) as exc:
        check_lead_independence(db, world["org"].id, world["chief"].id)
    assert "Cara Chief" in exc.value.detail and "AI acceptable use policy" in exc.value.detail and "different Lead Auditor" in exc.value.detail
    check_lead_independence(db, world["org"].id, world["chief2"].id)  # someone else is fine
    check_lead_independence(db, world["other"].id, world["chief"].id)  # and the author may lead another client's audit


def test_wizard_team_refuses_the_author_as_lead_but_allows_another_role(client, db, world, tailored):
    from app.engagements.wizard import _save_team

    e = Engagement(organization_id=world["org"].id, client_id=world["org"].id, name="ABC Corp annual review", status="draft", stage=1, created_by=world["chief2"].id)
    db.add(e)
    db.commit()
    errors = _save_team(db, world["chief2"], e, [{"user_id": world["chief"].id, "role": "chief_auditor"}, {"user_id": world["chief2"].id, "role": "auditor"}])
    assert [x["field"] for x in errors] == ["scope.team.0.user_id"]
    assert "cannot be Lead Auditor" in errors[0]["message"]
    roles = {(t.user_id, t.role) for t in db.scalars(select(EngagementTeam).where(EngagementTeam.engagement_id == e.id, EngagementTeam.deleted_at.is_(None)))}
    assert (world["chief"].id, "chief_auditor") not in roles and (world["chief2"].id, "auditor") in roles
    # the same person may still serve on the team in a role that does not lead the audit
    errors = _save_team(db, world["chief2"], e, [{"user_id": world["chief"].id, "role": "auditor"}, {"user_id": world["chief2"].id, "role": "chief_auditor"}])
    assert errors == []
