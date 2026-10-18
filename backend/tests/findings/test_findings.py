"""Task 29: findings review (spec §6 rules, §18.6), QA routing and sign-off 5."""
import pytest
from sqlalchemy import select

from app.engagements.models import Engagement, EngagementTeam
from app.findings.models import Finding
from app.notifications.models import Notification
from app.signoffs.service import current
from app.systems.models import AISystem
from tests.factories import approve_client_review, login_as, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401


@pytest.fixture
def qa(db, inv, people):
    cid, e, *_ = inv
    futran = people["chief"].organization_id
    from app.tenancy.models import Organization

    q = make_user(db, db.get(Organization, futran), roles=["qa_reviewer"], name="Quinn Reviewer", email="quinn@futran.test")
    db.add(EngagementTeam(organization_id=cid, engagement_id=e.id, user_id=q.id, role="qa_reviewer", conflict_confirmed_at=None))
    db.get(Engagement, e.id).stage = 5
    db.commit()
    return q


def _new(client, cid, title="Personal AI accounts used with client data", severity="medium"):
    r = client.post(f"/api/v1/clients/{cid}/findings", json={"title": title, "severity": severity, "description": "Condition, criteria, cause, effect.", "recommended_remediation": "Move to company accounts."})
    assert r.status_code == 200, r.text
    return r.json()


def test_finding_ref_sequence(client, db, inv, qa, people):
    cid, e, *_ = inv
    login_as(client, db, people["aud"])
    refs = [_new(client, cid, f"Finding {i}")["ref"] for i in range(3)]
    assert refs == ["F-001", "F-002", "F-003"]
    f2 = db.scalar(select(Finding).where(Finding.ref == "F-002"))
    assert client.post(f"/api/v1/findings/{f2.id}/dismiss", json={"reason": "Duplicate of F-001."}).status_code == 200
    assert _new(client, cid, "Another")["ref"] == "F-004"  # numbers are never reused


def test_author_cannot_approve(client, db, inv, qa, people):
    cid, e, *_ = inv
    login_as(client, db, people["chief"])
    f = _new(client, cid, "Chief's own")
    login_as(client, db, people["aud"])
    g = _new(client, cid)
    assert client.post(f"/api/v1/findings/{g['id']}/submit").json()["status"] == "submitted"
    assert client.post(f"/api/v1/findings/{g['id']}/approve", json={}).status_code == 403  # an auditor, and the author
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/findings/{f['id']}/submit").json()["review_role"] == "qa_reviewer"
    assert client.post(f"/api/v1/findings/{f['id']}/approve", json={}).status_code == 403  # own finding
    assert client.post(f"/api/v1/findings/{g['id']}/return", json={"comment": ""}).status_code == 422
    r = client.post(f"/api/v1/findings/{g['id']}/return", json={"comment": "Add the evidence reference."})
    assert r.json()["status"] == "returned"
    assert db.scalar(select(Notification).where(Notification.kind == "finding_returned", Notification.user_id == people["aud"].id)) is not None
    login_as(client, db, people["aud"])
    assert client.patch(f"/api/v1/findings/{g['id']}", json={"description": "Now with evidence: E-12."}).status_code == 200
    client.post(f"/api/v1/findings/{g['id']}/submit")
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/findings/{g['id']}/approve", json={"comment": "Fine."}).json()["status"] == "approved"
    assert client.patch(f"/api/v1/findings/{g['id']}", json={"title": "x"}).status_code == 409  # approved is final


def test_chief_auditor_finding_routes_to_qa(client, db, inv, qa, people):
    cid, e, *_ = inv
    login_as(client, db, people["chief"])
    f = _new(client, cid, "No bias audit within the past year", "critical")
    out = client.post(f"/api/v1/findings/{f['id']}/submit").json()
    assert out["review_role"] == "qa_reviewer"
    login_as(client, db, qa)
    assert client.post(f"/api/v1/findings/{f['id']}/approve", json={}).json()["status"] == "approved"
    # a Critical finding tells the Lead Auditor at once
    login_as(client, db, people["aud"])
    c = _new(client, cid, "PHI without a BAA", "critical")
    client.post(f"/api/v1/findings/{c['id']}/submit")
    assert db.scalar(select(Notification).where(Notification.kind == "critical_finding", Notification.user_id == people["chief"].id)) is not None
    # without a QA Reviewer on the team, the Chief Auditor cannot submit their own finding
    db.execute(EngagementTeam.__table__.delete().where(EngagementTeam.role == "qa_reviewer"))
    db.commit()
    login_as(client, db, people["chief"])
    g = _new(client, cid, "Chief again")
    r = client.post(f"/api/v1/findings/{g['id']}/submit")
    assert r.status_code == 409 and "QA Reviewer" in r.json()["detail"]


def test_client_never_sees_draft_findings(client, db, inv, qa, people):
    cid, e, maria, *_ = inv
    login_as(client, db, people["aud"])
    d = _new(client, cid, "Draft one")
    s = _new(client, cid, "Submitted one")
    client.post(f"/api/v1/findings/{s['id']}/submit")
    login_as(client, db, people["chief"])
    client.post(f"/api/v1/findings/{s['id']}/approve", json={})
    login_as(client, db, maria)
    assert client.get(f"/api/v1/clients/{cid}/findings").status_code == 403  # before the draft report
    db.get(Engagement, e.id).stage = 7
    db.commit()
    rows = client.get(f"/api/v1/clients/{cid}/findings").json()["findings"]
    assert [r["title"] for r in rows] == ["Submitted one"] and "author" not in rows[0]
    assert client.patch(f"/api/v1/findings/{d['id']}", json={"title": "x"}).status_code in (403, 404)


def test_signoff5_requires_all_approved_and_locks_scores(client, db, inv, qa, people):
    cid, e, *_ = inv
    approve_client_review(db, e)
    login_as(client, db, people["aud"])
    f = _new(client, cid)
    client.post(f"/api/v1/findings/{f['id']}/submit")
    db.get(Engagement, e.id).stage = 6
    db.commit()
    r = client.post(f"/api/v1/clients/{cid}/signoffs/5/submit", json={})
    assert r.status_code == 409 and any("F-001" in m["message"] for m in r.json()["errors"])
    login_as(client, db, people["chief"])
    client.post(f"/api/v1/findings/{f['id']}/approve", json={})
    login_as(client, db, people["aud"])
    so = client.post(f"/api/v1/clients/{cid}/signoffs/5/submit", json={})
    assert so.status_code == 200, so.text
    assert [p["role"] for p in so.json()["parties"]] == ["chief_auditor"]
    login_as(client, db, people["chief"])
    r = client.post(f"/api/v1/signoffs/{so.json()['id']}/sign", json={"typed_name": people["chief"].name})
    assert r.json()["status"] == "approved"
    db.expire_all()
    assert all(s.status == "locked" for s in db.scalars(select(AISystem).where(AISystem.engagement_id == e.id)))
    assert current(db, db.get(Engagement, e.id), 5).status == "approved"
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/clients/{cid}/findings", json={"title": "Late", "severity": "low"}).status_code == 409
