"""R8: unlock the tracing add-on. The client picks systems, plan, approver and trial; the Executive Sponsor approves;
Futran Sales gets an Opportunity (spec §27.3, §27.5)."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.mail.models import OutboxMessage
from app.notifications.models import Notification
from app.sales.models import Opportunity, OpportunityActivity
from app.tracing.models import AddonSubscription
from tests.tracing.conftest import activate


def _page(client):
    r = client.get("/api/v1/addons/tracing")
    assert r.status_code == 200, r.text
    return r.json()


def test_unlock_page_ticks_recommended_systems_and_lists_sponsors(client, db, trc):
    trc.as_(trc.caico)
    page = _page(client)
    rows = {s["name"]: s for s in page["systems"]}
    assert rows["Résumé screening"]["recommended"] and "Tier 3" in rows["Résumé screening"]["reasons"]
    assert rows["Invoice approval agent"]["recommended"] and "an AI agent that takes actions" in rows["Invoice approval agent"]["reasons"]
    assert not rows["Meeting notes"]["recommended"]
    assert rows["Résumé screening"]["department"] == "Human Resources" and rows["Résumé screening"]["tier"] == 3 and rows["Résumé screening"]["status"] == "locked"
    assert page["sponsors"] == [{"id": trc.sponsor.id, "name": "Robert Chen", "job_title": None}]
    assert page["can_request"] is True and page["can_approve"] is False
    assert [p["value"] for p in page["plans"]] == ["per_system", "tier_2_3", "enterprise"]


def test_request_notifies_the_sponsor_and_opens_an_opportunity(client, db, trc):
    trc.as_(trc.caico)
    r = client.post("/api/v1/addons/tracing/requests", json={"system_ids": [trc.screening.id, trc.agent.id], "plan": "per_system", "trial": True,
                                                             "approver_id": trc.sponsor.id, "note": "Need incident deadlines before the agent goes live."})
    assert r.status_code == 200, r.text
    sub = db.get(AddonSubscription, r.json()["id"])
    assert sub.status == "requested" and sub.requested_by == trc.caico.id and sub.approver_id == trc.sponsor.id and sub.trial is True
    assert set(sub.ai_system_ids) == {trc.screening.id, trc.agent.id}
    # an approval task for the sponsor, in the app and by email
    n = db.scalar(select(Notification).where(Notification.user_id == trc.sponsor.id))
    assert n.kind == "addon_approval" and n.link == "/addons" and "2 systems" in n.title
    assert any("robert@abc.test" in m.to for m in db.scalars(select(OutboxMessage)))
    # an Opportunity for Futran Sales and the Chief Auditor; Sales sees system types, not the systems' records
    o = db.scalar(select(Opportunity).where(Opportunity.organization_id == trc.org.id))
    assert o.trigger == "unlock_request" and o.trigger_ref == sub.id and o.addon_status == "requested" and o.service_kind == "addon"
    assert set(o.system_types) == {"vendor_app", "agent"} and sub.opportunity_id == o.id
    told = {n.user_id for n in db.scalars(select(Notification).where(Notification.kind == "addon_opportunity"))}
    assert told == {trc.sales.id, trc.chief.id}
    assert db.scalar(select(AuditLog).where(AuditLog.action == "addon.requested")) is not None
    # the systems show as requested; asking again for the same system is refused
    rows = {s["name"]: s for s in _page(client)["systems"]}
    assert rows["Résumé screening"]["status"] == "requested"
    r = client.post("/api/v1/addons/tracing/requests", json={"system_ids": [trc.screening.id], "plan": "per_system", "trial": False, "approver_id": trc.sponsor.id})
    assert r.status_code == 409


def test_request_validation(client, db, trc):
    trc.as_(trc.caico)
    r = client.post("/api/v1/addons/tracing/requests", json={"system_ids": [], "plan": "gold", "trial": False, "approver_id": trc.caico.id})
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} == {"system_ids", "plan", "approver_id"}


def test_who_may_request_and_approve(client, db, trc):
    body = {"system_ids": [trc.screening.id], "plan": "per_system", "trial": False, "approver_id": trc.sponsor.id}
    for u in (trc.hr_lead, trc.dpo, trc.sponsor, trc.contrib):
        trc.as_(u)
        assert client.post("/api/v1/addons/tracing/requests", json=body).status_code == 403, u.name
    trc.as_(trc.chief)
    assert client.post("/api/v1/addons/tracing/requests", json=body).status_code == 404  # a client screen
    trc.as_(trc.admin)
    r = client.post("/api/v1/addons/tracing/requests", json=body)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    for u in (trc.caico, trc.admin, trc.hr_lead):
        trc.as_(u)
        assert client.post(f"/api/v1/addons/requests/{sid}/decide", json={"approve": True}).status_code == 403, u.name
    trc.as_(trc.sponsor)
    page = _page(client)
    assert page["can_approve"] is True and page["requests"][0]["status"] == "requested"


def test_requester_cannot_approve_their_own_request(client, db, trc):
    from app.tenancy.service import assign_role

    assign_role(db, trc.caico, "exec_sponsor")
    db.commit()
    trc.as_(trc.caico)
    sid = client.post("/api/v1/addons/tracing/requests", json={"system_ids": [trc.screening.id], "plan": "per_system", "trial": False, "approver_id": trc.sponsor.id}).json()["id"]
    r = client.post(f"/api/v1/addons/requests/{sid}/decide", json={"approve": True})
    assert r.status_code == 403 and "another" in r.json()["detail"]


def test_sponsor_approval_activates_and_unlocks_the_chosen_systems(client, db, trc):
    from app.core.clock import today

    sub = activate(client, trc, [trc.screening])
    assert sub["status"] == "active" and sub["trial_ends_on"] == (today().fromordinal(today().toordinal() + 30)).isoformat()
    row = db.get(AddonSubscription, sub["id"])
    assert row.approved_by == trc.sponsor.id and row.activated_at is not None
    trc.as_(trc.caico)
    assert client.get(f"/api/v1/register/{trc.screening.id}/tracing").json()["state"] == "active"
    assert client.get(f"/api/v1/register/{trc.notes.id}/tracing").json()["state"] == "locked"
    # the register record's tracing summary follows the subscription
    assert client.get(f"/api/v1/register/{trc.screening.id}").json()["history"]["tracing"]["locked"] is False
    assert client.get(f"/api/v1/register/{trc.notes.id}").json()["history"]["tracing"]["locked"] is True
    n = db.scalar(select(Notification).where(Notification.user_id == trc.caico.id, Notification.kind == "addon_decided"))
    assert "approved" in n.title
    acts = [a.kind for a in db.scalars(select(OpportunityActivity).where(OpportunityActivity.opportunity_id == row.opportunity_id))]
    assert "approved_by_client" in acts


def test_decline_needs_a_reason_and_keeps_the_tab_locked(client, db, trc):
    trc.as_(trc.caico)
    sid = client.post("/api/v1/addons/tracing/requests", json={"system_ids": [trc.screening.id], "plan": "per_system", "trial": False, "approver_id": trc.sponsor.id}).json()["id"]
    trc.as_(trc.sponsor)
    assert client.post(f"/api/v1/addons/requests/{sid}/decide", json={"approve": False}).status_code == 422
    r = client.post(f"/api/v1/addons/requests/{sid}/decide", json={"approve": False, "comment": "Not in this year's budget."})
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert client.post(f"/api/v1/addons/requests/{sid}/decide", json={"approve": True}).status_code == 409
    trc.as_(trc.caico)
    assert client.get(f"/api/v1/register/{trc.screening.id}/tracing").json()["state"] == "locked"


def test_tier_2_3_plan_covers_new_tier_2_and_3_systems(client, db, trc):
    from app.register.models import RegisterSystem

    activate(client, trc, [trc.screening], plan="tier_2_3")
    later = RegisterSystem(organization_id=trc.org.id, reference="AIS-009", name="Credit limit scoring", type="in_house_model", sourcing="in_house", department_id=trc.fin.id, risk_tier=2, stage="proposed")
    db.add(later)
    db.commit()
    trc.as_(trc.caico)
    assert client.get(f"/api/v1/register/{trc.agent.id}/tracing").json()["state"] == "active"
    assert client.get(f"/api/v1/register/{later.id}/tracing").json()["state"] == "active"
    assert client.get(f"/api/v1/register/{trc.notes.id}/tracing").json()["state"] == "locked"


def test_cancel_locks_the_tab_again(client, db, trc):
    sub = activate(client, trc, [trc.screening], plan="enterprise")
    trc.as_(trc.caico)
    assert client.get(f"/api/v1/register/{trc.notes.id}/tracing").json()["state"] == "active"
    trc.as_(trc.hr_lead)
    assert client.post(f"/api/v1/addons/requests/{sub['id']}/cancel", json={"reason": "x"}).status_code == 403
    trc.as_(trc.sponsor)
    assert client.post(f"/api/v1/addons/requests/{sub['id']}/cancel", json={}).status_code == 422
    r = client.post(f"/api/v1/addons/requests/{sub['id']}/cancel", json={"reason": "Moving to the vendor's own logging."})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    trc.as_(trc.caico)
    assert client.get(f"/api/v1/register/{trc.screening.id}/tracing").json()["state"] == "locked"


def test_other_clients_requests_are_invisible(client, db, trc):
    from tests.factories import make_org, make_user

    other = make_org(db, name="Northwind")
    sponsor2 = make_user(db, other, roles=["exec_sponsor"], name="Nora North", email="nora@nw.test")
    db.commit()
    trc.as_(trc.caico)
    sid = client.post("/api/v1/addons/tracing/requests", json={"system_ids": [trc.screening.id], "plan": "per_system", "trial": False, "approver_id": trc.sponsor.id}).json()["id"]
    trc.as_(sponsor2)
    assert client.post(f"/api/v1/addons/requests/{sid}/decide", json={"approve": True}).status_code == 404
    assert client.get("/api/v1/addons/tracing").json()["requests"] == []
    # nor can a client ask for another client's systems
    trc.as_(trc.caico)
    from app.register.models import RegisterSystem

    theirs = RegisterSystem(organization_id=other.id, reference="AIS-001", name="Theirs", type="agent", sourcing="vendor", stage="live")
    db.add(theirs)
    db.commit()
    r = client.post("/api/v1/addons/tracing/requests", json={"system_ids": [theirs.id], "plan": "per_system", "trial": False, "approver_id": trc.sponsor.id})
    assert r.status_code == 422


def test_the_opportunity_follows_the_sponsors_decision(client, db, trc):
    """Sales sees where the add-on stands, not a request that was decided long ago."""
    sub = activate(client, trc, [trc.screening])
    o = db.get(Opportunity, db.get(AddonSubscription, sub["id"]).opportunity_id)
    db.refresh(o)
    assert o.addon_status == "active" and "waiting" not in o.why_now.lower() and "approved" in o.why_now.lower()
    trc.as_(trc.sponsor)
    assert client.post(f"/api/v1/addons/requests/{sub['id']}/cancel", json={"reason": "Moving to the vendor's own logging."}).status_code == 200
    db.refresh(o)
    assert o.addon_status == "cancelled" and "cancelled" in o.why_now.lower()


def test_a_declined_request_shows_as_declined_on_the_opportunity(client, db, trc):
    trc.as_(trc.caico)
    sid = client.post("/api/v1/addons/tracing/requests", json={"system_ids": [trc.screening.id], "plan": "per_system", "trial": False, "approver_id": trc.sponsor.id}).json()["id"]
    trc.as_(trc.sponsor)
    assert client.post(f"/api/v1/addons/requests/{sid}/decide", json={"approve": False, "comment": "Not in this year's budget."}).status_code == 200
    o = db.get(Opportunity, db.get(AddonSubscription, sid).opportunity_id)
    db.refresh(o)
    assert o.addon_status == "declined" and "declined" in o.why_now.lower()
