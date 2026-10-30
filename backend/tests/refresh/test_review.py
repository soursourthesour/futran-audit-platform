"""§25.3 steps 6–7: the review queue — approve, edit and approve, hold, reject, legal review, second reviewer."""
import json

import pytest
from sqlalchemy import select

from app.clientalerts.models import AlertSend
from app.litigation.models import Case
from app.litigation.service import match_case
from app.refresh.claude import FakeRefreshClient
from app.refresh.models import RefreshProposalMeta
from app.refresh.pipeline import execute_run, start_run
from app.regmaster.models import ProposedChange
from app.sales.models import Opportunity
from app.staffalerts.models import StaffAlert
from tests.factories import login_as
from tests.wsd_world import HIRING_CASE


@pytest.fixture
def case_change(db, lit, settings):
    """A litigation run proposing a stage change to Mobley (low confidence: the source is off the allowlist)."""
    from app.reference.models import Jurisdiction
    from app.regmaster.models import Source

    us = db.scalar(select(Jurisdiction).where(Jurisdiction.code == "US"))
    db.add(Source(jurisdiction_id=us.id, name="U.S. District Court, N.D. Cal.", url="https://cand.uscourts.gov/", domain="uscourts.gov", kind="official"))
    case = Case(name=HIRING_CASE["name"], area="Hiring discrimination", stage="discovery", jurisdiction_id=us.id, match_rule=HIRING_CASE["match_rule"],
                talking_points_client="List every hiring tool that ranks or filters applicants.", version=1, timeline=[])
    db.add(case)
    db.flush()
    match_case(db, case)

    def reply(url, conf="high"):
        return {"changes": [{"change_type": "case_update", "case_id": case.id, "field_path": "case.stage", "old_value": "discovery", "new_value": "trial",
                             "summary": "Trial date set.", "source_url": url, "source_quote": "The case is set for jury trial.", "confidence": conf}]}

    run = start_run(db, kind="litigation", actor=lit["chief"], scope_mode="chosen", jurisdiction_codes=["US"], settings=settings)
    execute_run(db, settings, run, FakeRefreshClient({"litigation:US": reply("https://news.example/mobley")}))
    db.commit()
    pc = db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id))
    return case, pc, run


def _decide(client, pc, action, **kw):
    return client.post(f"/api/v1/reg/changes/{pc.id}/decide", json={"action": action, **kw})


def test_low_confidence_needs_a_second_reviewer_before_approval(client, db, lit, case_change):
    case, pc, run = case_change
    assert pc.confidence == "low"
    login_as(client, db, lit["chief"])
    r = _decide(client, pc, "approve")
    assert r.status_code == 409 and "second reviewer" in r.json()["detail"]
    login_as(client, db, lit["qa"])
    assert _decide(client, pc, "approve").status_code == 403  # QA reviews, never approves
    r = client.post(f"/api/v1/reg/changes/{pc.id}/second-review", json={"outcome": "concur", "note": "Docket confirms the trial date."})
    assert r.status_code == 200, r.text
    login_as(client, db, lit["chief"])
    r = _decide(client, pc, "approve", note="Confirmed on the docket")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(ProposedChange, pc.id).status == "approved"
    c = db.get(Case, case.id)
    assert c.stage == "trial" and c.version == 2 and c.timeline[-1]["stage"] == "trial"


def test_approval_queues_client_briefings_and_opportunities_and_resolves_the_alert(client, db, lit, case_change):
    case, pc, run = case_change
    login_as(client, db, lit["qa"])
    client.post(f"/api/v1/reg/changes/{pc.id}/second-review", json={"outcome": "concur", "note": "ok"})
    login_as(client, db, lit["chief"])
    assert _decide(client, pc, "approve").status_code == 200
    sends = list(db.scalars(select(AlertSend)))
    assert {s.organization_id for s in sends} == {lit["abc"].id, lit["nw"].id} and all(s.status == "waiting_approval" for s in sends)
    opps = list(db.scalars(select(Opportunity).where(Opportunity.trigger == "case")))
    assert {o.organization_id for o in opps} == {lit["abc"].id, lit["nw"].id}
    assert all(a.resolved_at for a in db.scalars(select(StaffAlert).where(StaffAlert.refresh_run_id == run.id)))


def test_notify_clients_can_be_turned_off(client, db, lit, case_change):
    case, pc, run = case_change
    login_as(client, db, lit["qa"])
    client.post(f"/api/v1/reg/changes/{pc.id}/second-review", json={"outcome": "concur", "note": "ok"})
    login_as(client, db, lit["chief"])
    assert _decide(client, pc, "approve", notify_clients=False).status_code == 200
    assert db.query(AlertSend).count() == 0


def test_second_reviewer_cannot_also_approve(client, db, lit, case_change):
    case, pc, run = case_change
    from app.tenancy.service import assign_role

    assign_role(db, lit["chief"], "qa_reviewer")
    db.commit()
    login_as(client, db, lit["chief"])
    client.post(f"/api/v1/reg/changes/{pc.id}/second-review", json={"outcome": "concur", "note": "mine"})
    r = _decide(client, pc, "approve")
    assert r.status_code == 409 and "different person" in r.json()["detail"]


def test_objection_blocks_approval(client, db, lit, case_change):
    case, pc, run = case_change
    login_as(client, db, lit["qa"])
    client.post(f"/api/v1/reg/changes/{pc.id}/second-review", json={"outcome": "object", "note": "News article only."})
    login_as(client, db, lit["chief"])
    assert _decide(client, pc, "approve").status_code == 409
    assert _decide(client, pc, "reject", note="Not on the docket").status_code == 200
    db.expire_all()
    assert db.get(ProposedChange, pc.id).status == "rejected"


def test_legal_review_then_back_to_the_queue(client, db, lit, case_change):
    case, pc, run = case_change
    login_as(client, db, lit["chief"])
    assert _decide(client, pc, "legal_review", note="Check the order").status_code == 200
    db.expire_all()
    assert db.get(ProposedChange, pc.id).status == "legal_review"
    login_as(client, db, lit["qa"])
    client.post(f"/api/v1/reg/changes/{pc.id}/second-review", json={"outcome": "concur", "note": "Order read"})
    db.expire_all()
    assert db.get(ProposedChange, pc.id).status == "pending"


def test_hold_until_adopted_keeps_it_waiting(client, db, lit, case_change):
    case, pc, run = case_change
    login_as(client, db, lit["chief"])
    assert _decide(client, pc, "hold", note="Wait for the order").status_code == 200
    db.expire_all()
    assert db.get(ProposedChange, pc.id).status == "held"
    q = client.get("/api/v1/reg/changes?kind=litigation").json()
    assert q["items"][0]["status"] == "held" and q["counts"]["open"] == 1


def test_edit_then_approve_uses_the_edited_value(client, db, lit, case_change):
    case, pc, run = case_change
    login_as(client, db, lit["qa"])
    client.post(f"/api/v1/reg/changes/{pc.id}/second-review", json={"outcome": "concur", "note": "ok"})
    login_as(client, db, lit["chief"])
    r = _decide(client, pc, "edit_approve", new_value="stayed", note="Stayed pending appeal")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(ProposedChange, pc.id).status == "edited_approved" and db.get(Case, case.id).stage == "stayed"
    assert db.get(RefreshProposalMeta, pc.id).edited_value == "stayed"


def test_queue_shows_old_new_quote_confidence_and_impact(client, db, lit, case_change):
    case, pc, run = case_change
    login_as(client, db, lit["chief"])
    q = client.get("/api/v1/reg/changes?kind=litigation").json()
    it = q["items"][0]
    assert it["old_value"] == "discovery" and it["new_value"] == "trial" and it["source_quote"] == "The case is set for jury trial."
    assert it["confidence"] == "low" and it["off_allowlist"] is True and it["needs_second_review"] is True
    assert it["impact"]["clients"] == 2 and it["subject"] == HIRING_CASE["name"]
    d = client.get(f"/api/v1/reg/changes/{pc.id}").json()
    assert {i["organization_name"] for i in d["impacts"]} == {"ABC Corp", "Northwind Health"}


def test_bulk_hold_and_reject(client, db, lit, case_change):
    case, pc, run = case_change
    login_as(client, db, lit["chief"])
    r = client.post("/api/v1/reg/changes/bulk", json={"ids": [pc.id], "action": "approve"})
    assert r.json()["results"][0]["ok"] is False  # needs a second reviewer
    r = client.post("/api/v1/reg/changes/bulk", json={"ids": [pc.id], "action": "hold", "note": "later"})
    assert r.json()["results"][0]["ok"] is True


def test_only_the_chief_auditor_decides(client, db, lit, case_change):
    case, pc, run = case_change
    for who in ("aud", "sales", "admin"):
        login_as(client, db, lit[who])
        assert _decide(client, pc, "reject").status_code == 403, who


def test_assign_a_second_reviewer_notifies_them(client, db, lit, case_change):
    from app.notifications.models import Notification

    case, pc, run = case_change
    login_as(client, db, lit["chief"])
    assert client.post(f"/api/v1/reg/changes/{pc.id}/assign", json={"user_id": lit["qa"].id}).status_code == 200
    assert db.scalar(select(Notification).where(Notification.user_id == lit["qa"].id, Notification.kind == "second_review")) is not None
    assert client.post(f"/api/v1/reg/changes/{pc.id}/assign", json={"user_id": lit["sales"].id}).status_code == 422
