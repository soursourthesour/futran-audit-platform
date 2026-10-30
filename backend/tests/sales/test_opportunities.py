"""§27.5 opportunities: automatic triggers, Chief Auditor approval for current audit clients, independence rule."""
import pytest
from sqlalchemy import select

from app.engagements.models import Engagement
from app.findings.models import Finding
from app.notifications.models import Notification
from app.sales.models import Opportunity, OpportunityActivity
from app.sales.service import IndependenceError, open_from_trigger
from tests.factories import login_as


@pytest.fixture
def audit_client(db, lit):
    """ABC Corp is a current audit client (engagement in progress); Northwind is not."""
    e = Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC 2026 audit", status="in_progress", stage=5)
    db.add(e)
    db.commit()
    return e


def test_trigger_creates_one_opportunity_and_flags_current_audit_clients(db, lit, audit_client):
    o1 = open_from_trigger(db, lit["abc"].id, "case", "case-1", service="Bias audit including age, hiring tools", why_now="Mobley v. Workday", system_ids=[lit["screening"].id])
    again = open_from_trigger(db, lit["abc"].id, "case", "case-1", service="Bias audit including age, hiring tools", why_now="Mobley v. Workday")
    o2 = open_from_trigger(db, lit["nw"].id, "case", "case-1", service="Bias audit", why_now="Mobley v. Workday")
    assert again.id == o1.id
    assert db.scalar(select(Opportunity).where(Opportunity.organization_id == lit["abc"].id)).id == o1.id
    assert o1.needs_ca_approval is True and o2.needs_ca_approval is False
    assert o1.stage == "new" and o1.system_types == ["vendor_app"]


def test_completed_engagement_is_not_a_current_audit_client(db, lit, audit_client):
    audit_client.status = "completed"
    db.commit()
    o = open_from_trigger(db, lit["abc"].id, "effective_date", "law-1", service="Readiness review", why_now="Deadline in 60 days")
    assert o.needs_ca_approval is False


def test_independence_rule_blocks_remediation_of_own_findings(db, lit, audit_client):
    db.add(Finding(organization_id=lit["abc"].id, engagement_id=audit_client.id, ref="F-001", title="No bias audit in the past year", severity="high", status="approved"))
    db.commit()
    with pytest.raises(IndependenceError):
        open_from_trigger(db, lit["abc"].id, "recommended_addon", "x", service="Fix the bias-audit finding", service_kind="remediation", why_now="Finding")
    # a different service, or a client Futran is not auditing, is fine
    assert open_from_trigger(db, lit["abc"].id, "recommended_addon", "y", service="Tracing module", service_kind="addon", why_now="Agents live").id
    assert open_from_trigger(db, lit["nw"].id, "recommended_addon", "x", service="Remediation support", service_kind="remediation", why_now="Request").id


def test_sales_cannot_send_an_offer_to_an_audit_client_until_the_chief_auditor_approves(client, db, lit, audit_client):
    o = open_from_trigger(db, lit["abc"].id, "case", "case-1", service="Bias audit", why_now="Mobley v. Workday")
    db.commit()
    login_as(client, db, lit["sales"])
    r = client.post(f"/api/v1/opportunities/{o.id}/send-proposal", json={"summary": "Proposal for an age-inclusive bias audit"})
    assert r.status_code == 409
    assert client.post(f"/api/v1/opportunities/{o.id}/approve", json={"decision": "approve"}).status_code == 403
    assert client.post(f"/api/v1/opportunities/{o.id}/request-approval", json={"note": "Client asked for a quote"}).status_code == 200
    assert db.scalar(select(Notification).where(Notification.user_id == lit["chief"].id, Notification.kind == "opportunity_approval")) is not None
    login_as(client, db, lit["chief"])
    r = client.post(f"/api/v1/opportunities/{o.id}/approve", json={"decision": "approve", "note": "No conflict with fieldwork"})
    assert r.status_code == 200 and r.json()["ca_approved_by_name"] == "Cara Chief"
    login_as(client, db, lit["sales"])
    r = client.post(f"/api/v1/opportunities/{o.id}/send-proposal", json={"summary": "Proposal for an age-inclusive bias audit"})
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "proposal"
    kinds = [a.kind for a in db.scalars(select(OpportunityActivity).where(OpportunityActivity.opportunity_id == o.id).order_by(OpportunityActivity.at))]
    assert kinds == ["approval_requested", "approved", "proposal"]


def test_declined_offer_cannot_be_sent(client, db, lit, audit_client):
    o = open_from_trigger(db, lit["abc"].id, "case", "c", service="Bias audit", why_now="Case")
    db.commit()
    login_as(client, db, lit["chief"])
    assert client.post(f"/api/v1/opportunities/{o.id}/approve", json={"decision": "decline", "note": "Fieldwork under way"}).status_code == 200
    login_as(client, db, lit["sales"])
    assert client.post(f"/api/v1/opportunities/{o.id}/send-proposal", json={"summary": "x"}).status_code == 409


def test_sales_logs_calls_and_outcomes_and_sees_trigger_and_system_type_only(client, db, lit):
    o = open_from_trigger(db, lit["nw"].id, "case", "c", service="Bias audit", why_now="Mobley v. Workday", system_ids=[lit["nw_ats"].id])
    db.commit()
    login_as(client, db, lit["sales"])
    assert client.post(f"/api/v1/opportunities/{o.id}/activities", json={"kind": "call", "summary": "Spoke to the CAICO; call booked 4 Nov"}).status_code == 200
    assert client.post(f"/api/v1/opportunities/{o.id}/activities", json={"kind": "gossip", "summary": "x"}).status_code == 422
    r = client.patch(f"/api/v1/opportunities/{o.id}", json={"stage": "won", "value": 18000, "next_step": "Kick-off 12 Nov"})
    assert r.status_code == 200 and r.json()["stage"] == "won" and r.json()["closed_at"]
    item = client.get("/api/v1/opportunities").json()["items"][0]
    assert item["client_name"] == "Northwind Health" and item["trigger"] == "case" and item["trigger_label"] == "Litigation"
    assert item["system_types"] == ["Vendor AI app"]
    assert not any("finding" in k for k in item)
    detail = client.get(f"/api/v1/opportunities/{o.id}").json()
    assert [a["kind"] for a in detail["activities"]][:2] == ["stage", "call"]  # newest first


def test_sales_adds_an_opportunity_and_kpis_count_it(client, db, lit, audit_client):
    login_as(client, db, lit["sales"])
    r = client.post("/api/v1/opportunities", json={"organization_id": lit["abc"].id, "service": "EU AI Act readiness review", "service_kind": "readiness", "why_now": "High-risk duties date", "value": 24000})
    assert r.status_code == 200, r.text
    assert r.json()["needs_ca_approval"] is True and r.json()["owner_id"] == lit["sales"].id
    k = client.get("/api/v1/opportunities").json()["kpis"]
    assert k["open"] == 1 and k["waiting_approval"] == 1 and k["pipeline_value"] == 24000


def test_bulk_owner_and_stage(client, db, lit):
    a = open_from_trigger(db, lit["nw"].id, "case", "a", service="A", why_now="a")
    b = open_from_trigger(db, lit["nw"].id, "case", "b", service="B", why_now="b")
    db.commit()
    login_as(client, db, lit["chief"])
    r = client.post("/api/v1/opportunities/bulk", json={"ids": [a.id, b.id], "owner_id": lit["sales"].id, "stage": "contacted"})
    assert r.status_code == 200 and r.json()["changed"] == 2
    db.expire_all()
    assert {o.owner_id for o in db.scalars(select(Opportunity))} == {lit["sales"].id}


def test_owner_must_be_sales_or_chief_auditor(client, db, lit):
    a = open_from_trigger(db, lit["nw"].id, "case", "a", service="A", why_now="a")
    db.commit()
    login_as(client, db, lit["chief"])
    assert client.patch(f"/api/v1/opportunities/{a.id}", json={"owner_id": lit["aud"].id}).status_code == 422


def test_auditors_and_clients_do_not_see_opportunities(client, db, lit):
    login_as(client, db, lit["aud"])
    assert client.get("/api/v1/opportunities").status_code == 403
    login_as(client, db, lit["maria"])
    assert client.get("/api/v1/opportunities").status_code in (403, 404)


def test_effective_date_within_90_days_opens_an_opportunity_once(db, lit):
    from datetime import date, timedelta

    from app.laws.publish import current_regulations
    from app.regmaster.models import ClientLawApplicability, LawVersion
    from app.sales.service import open_effective_date_opportunities

    reg = current_regulations(db)[0]
    v = LawVersion(regulation_id=reg.id, version_no=9, compliance_on=date(2027, 1, 1))
    db.add(v)
    db.flush()
    reg.current_version_id = v.id
    db.add(ClientLawApplicability(organization_id=lit["abc"].id, regulation_id=reg.id, law_version_id=v.id, in_scope=True))
    db.commit()
    assert open_effective_date_opportunities(db, date(2027, 1, 1) - timedelta(days=91)) == []
    made = open_effective_date_opportunities(db, date(2027, 1, 1) - timedelta(days=60))
    assert [(o.organization_id, o.trigger) for o in made] == [(lit["abc"].id, "effective_date")]
    assert reg.short_name in made[0].why_now
    assert open_effective_date_opportunities(db, date(2027, 1, 1) - timedelta(days=59)) == []


def test_recommended_tracing_addon_opens_one_opportunity_per_client(db, lit):
    from app.sales.service import open_recommended_addon_opportunities

    lit["screening"].risk_tier = 3
    lit["chatbot"].type, lit["chatbot"].autonomy = "agent", "autonomous"
    db.commit()
    made = open_recommended_addon_opportunities(db)
    assert len(made) == 1
    o = made[0]
    assert o.organization_id == lit["abc"].id and o.trigger == "recommended_addon" and o.addon_status == "recommended"
    assert set(o.system_ids) == {lit["screening"].id, lit["chatbot"].id} and "2 systems" in o.service
    assert open_recommended_addon_opportunities(db) == []  # once per client
