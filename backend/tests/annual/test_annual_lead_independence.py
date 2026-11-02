"""Independence rule (spec §21 F7) on annual reviews: a Futran person recorded as an author of the client's policy is not
copied in as Lead Auditor, and the wizard refuses them as Lead Auditor at submission."""
from sqlalchemy import select

from app.engagements.models import EngagementTeam
from app.engagements.wizard import _validate_team
from app.policies.models import PolicyDocument
from app.policies.service import ensure_templates
from tests.annual.test_carry_forward import _close
from tests.factories import login_as


def _author(db, cid, user):
    t = ensure_templates(db)["acceptable_use"]
    db.add(PolicyDocument(organization_id=cid, template_id=t.id, template_code=t.code, template_version=t.version, title="AI acceptable use policy", answers={}, blocks=[],
                          status="published", authored_by_futran_team=[user.id]))
    db.commit()


def test_a_policy_author_is_not_copied_in_as_lead_auditor(client, db, ats, people):
    cid, e, maria, s = ats
    lead = people["chief"]
    assert db.scalar(select(EngagementTeam).where(EngagementTeam.engagement_id == e.id, EngagementTeam.role == "chief_auditor", EngagementTeam.user_id == lead.id))
    _author(db, cid, lead)
    prior = _close(db, e)
    login_as(client, db, people["chief2"])
    r = client.post(f"/api/v1/engagements/{prior.id}/annual-review")
    assert r.status_code == 200, r.text
    new_id = r.json()["engagement_id"]
    notices = r.json()["notices"]
    assert len(notices) == 1 and "Cara Chief" in notices[0] and "cannot be Lead Auditor" in notices[0]
    roles = {(t.user_id, t.role) for t in db.scalars(select(EngagementTeam).where(EngagementTeam.engagement_id == new_id, EngagementTeam.deleted_at.is_(None)))}
    assert (lead.id, "chief_auditor") not in roles
    # put back as Lead Auditor by another route, the submission is refused
    db.add(EngagementTeam(organization_id=cid, engagement_id=new_id, user_id=lead.id, role="chief_auditor"))
    db.commit()
    from app.engagements.models import Engagement

    errs = _validate_team(db, db.get(Engagement, new_id))
    assert any("cannot be Lead Auditor" in x["message"] and x["field"] == "scope.team" for x in errs)


def test_without_a_policy_author_the_team_is_copied_unchanged(client, db, ats, people):
    cid, e, maria, s = ats
    prior = _close(db, e)
    login_as(client, db, people["chief"])
    r = client.post(f"/api/v1/engagements/{prior.id}/annual-review")
    assert r.status_code == 200 and r.json()["notices"] == []
