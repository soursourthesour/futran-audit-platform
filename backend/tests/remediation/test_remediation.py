"""Task 31: management responses, sign-off 6, remediation and close-out (spec §7 stages 7 and 9, §9.6)."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.engagements.models import Engagement
from app.findings.models import Finding
from app.governance.models import Commitment
from app.notifications.models import Notification
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401
from tests.reports.test_reports import _final, _no_public_summary, _released, ready  # noqa: F401

DUE = (date.today() + timedelta(days=60)).isoformat()


@pytest.fixture
def drafted(client, db, ready, people):
    """The client draft (v1.0) is released: stage 7, one approved finding F-001."""
    cid, e, maria, f = ready
    _no_public_summary(db, e)
    _released(client, db, people, cid)
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 7
    priya = db.scalar(select(User).where(User.email == "priya@abc.test"))
    return cid, e, maria, f, priya


def _respond(client, f, owner_id, **kw):
    body = {"response": "agree", "planned_action": "Move recruiters to company Copilot accounts.", "owner_user_id": owner_id, "due_date": DUE} | kw
    return client.put(f"/api/v1/findings/{f['id']}/response", json=body)


def _items(client, cid):
    r = client.get(f"/api/v1/clients/{cid}/remediation")
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_client_cannot_edit_finding_text(client, db, drafted):
    cid, e, maria, f, priya = drafted
    login_as(client, db, maria)
    assert client.patch(f"/api/v1/findings/{f['id']}", json={"title": "Softer wording"}).status_code == 403
    r = _respond(client, f, priya.id, title="Softer wording", description="Not a problem.")
    assert r.status_code == 200, r.text
    db.expire_all()
    fx = db.get(Finding, f["id"])
    assert fx.title == "Personal AI accounts used with applicant data" and fx.description == "Recruiters use personal accounts."
    bad = _respond(client, f, priya.id, response="maybe", planned_action="", due_date="")
    assert bad.status_code == 422 and {x["field"] for x in bad.json()["errors"]} >= {"response", "planned_action", "due_date"}


def test_client_mark_done_goes_to_awaiting_verification(client, db, drafted, people):
    cid, e, maria, f, priya = drafted
    login_as(client, db, maria)
    _respond(client, f, priya.id)
    item = _items(client, cid)[0]
    assert item["status"] == "open" and item["finding_ref"] == "F-001" and item["owner"] == "Priya Shah"
    login_as(client, db, priya)
    r = client.post(f"/api/v1/remediation/{item['id']}/done", json={"note": "All recruiters moved; licence report attached."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "awaiting_verification"
    assert db.scalar(select(Notification).where(Notification.kind == "remediation_done", Notification.user_id == people["aud"].id)) is not None
    assert client.post(f"/api/v1/remediation/{item['id']}/done", json={}).status_code == 409


def test_only_auditor_verifies_only_chief_closes(client, db, drafted, people):
    cid, e, maria, f, priya = drafted
    login_as(client, db, maria)
    _respond(client, f, priya.id)
    item = _items(client, cid)[0]
    client.post(f"/api/v1/remediation/{item['id']}/done", json={"note": "Done."})
    assert client.post(f"/api/v1/remediation/{item['id']}/verify", json={"note": "x"}).status_code == 403
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/remediation/{item['id']}/close", json={}).status_code == 409  # not verified yet
    assert client.post(f"/api/v1/remediation/{item['id']}/verify", json={"note": "x"}).status_code == 403
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/remediation/{item['id']}/verify", json={"note": ""}).status_code == 422
    r = client.post(f"/api/v1/remediation/{item['id']}/verify", json={"note": "Licence report checked."})
    assert r.status_code == 200 and r.json()["verified_by"] == "Alex Auditor"
    assert client.post(f"/api/v1/remediation/{item['id']}/close", json={}).status_code == 403
    login_as(client, db, people["chief"])
    r = client.post(f"/api/v1/remediation/{item['id']}/reopen", json={"note": "Two recruiters still use personal accounts."})
    assert r.json()["status"] == "reopened" and r.json()["verified_by"] is None
    login_as(client, db, priya)
    client.post(f"/api/v1/remediation/{item['id']}/done", json={"note": "Fixed."})
    login_as(client, db, people["aud"])
    client.post(f"/api/v1/remediation/{item['id']}/verify", json={"note": "Checked again."})
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/remediation/{item['id']}/close", json={}).json()["status"] == "closed"


def test_commitments_appear_in_remediation(client, db, drafted, people):
    cid, e, maria, f, priya = drafted
    c = Commitment(organization_id=cid, engagement_id=e.id, source="governance_document", source_id=e.id, description="Adopt an AI acceptable use policy",
                   target_date=date.today() + timedelta(days=30), owner="Maria Lopez", status="open")
    db.add(c)
    db.commit()
    login_as(client, db, people["aud"])
    rows = _items(client, cid)
    item = next(x for x in rows if x["source"] == "commitment")
    assert item["action"] == "Adopt an AI acceptable use policy" and item["owner"] == "Maria Lopez"
    login_as(client, db, maria)
    client.post(f"/api/v1/remediation/{item['id']}/done", json={"note": "Policy approved by the board."})
    login_as(client, db, people["aud"])
    client.post(f"/api/v1/remediation/{item['id']}/verify", json={"note": "Policy seen."})
    login_as(client, db, people["chief"])
    client.post(f"/api/v1/remediation/{item['id']}/close", json={})
    db.expire_all()
    assert db.get(Commitment, c.id).status == "closed"
    assert len([x for x in _items(client, cid) if x["source"] == "commitment"]) == 1  # listed once, not again on each view


def test_all_closed_completes_engagement(client, db, drafted, people):
    cid, e, maria, f, priya = drafted
    login_as(client, db, priya)
    assert _respond(client, f, priya.id).status_code == 403  # an organization-wide finding: the CAICO answers it
    login_as(client, db, maria)
    assert _respond(client, f, priya.id).status_code == 200
    login_as(client, db, priya)
    r = client.post(f"/api/v1/clients/{cid}/signoffs/6/submit", json={})
    assert r.status_code == 409 and "adequacy" in r.text  # Futran reviews the responses first
    login_as(client, db, people["aud"])
    resp = client.get(f"/api/v1/clients/{cid}/responses").json()["responses"][0]
    assert client.post(f"/api/v1/responses/{resp['id']}/adequacy", json={"adequate": False, "note": ""}).status_code == 422
    assert client.post(f"/api/v1/responses/{resp['id']}/adequacy", json={"adequate": True, "note": "Action addresses the cause."}).status_code == 200
    login_as(client, db, priya)
    so = client.post(f"/api/v1/clients/{cid}/signoffs/6/submit", json={})
    assert so.status_code == 200, so.text
    login_as(client, db, maria)
    assert client.post(f"/api/v1/signoffs/{so.json()['id']}/sign", json={"typed_name": "Maria Lopez"}).json()["status"] == "approved"
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 8
    assert _respond(client, f, priya.id, planned_action="Changed.").status_code == 409  # the plan is accepted
    _final(client, db, people, cid, e)
    from app.reports.models import Report

    final = db.scalar(select(Report).where(Report.engagement_id == e.id, Report.version == "v1.1"))
    assert "Management responses" in final.body_md and "Move recruiters to company Copilot accounts" in final.body_md
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/report/acknowledge", json={"typed_name": "Maria Lopez", "commitment": "plan"})
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 9
    item = _items(client, cid)[0]
    login_as(client, db, priya)
    client.post(f"/api/v1/remediation/{item['id']}/done", json={"note": "Done."})
    login_as(client, db, people["aud"])
    client.post(f"/api/v1/remediation/{item['id']}/verify", json={"note": "Checked."})
    login_as(client, db, people["chief"])
    client.post(f"/api/v1/remediation/{item['id']}/close", json={})
    db.expire_all()
    eng = db.get(Engagement, e.id)
    assert eng.status == "completed" and eng.completed_at is not None


def test_overdue_remediation_in_weekly_digest(client, db, drafted, settings):
    cid, e, maria, f, priya = drafted
    login_as(client, db, maria)
    _respond(client, f, priya.id, due_date=(date.today() + timedelta(days=1)).isoformat())
    from app.notifications.jobs import DIGEST_SOURCES

    items = [i for src in DIGEST_SOURCES for i in src(db, date.today() + timedelta(days=10))]
    assert any(i.kind == "remediation" and i.owner == "Priya Shah" for i in items)
