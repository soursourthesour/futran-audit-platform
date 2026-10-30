"""Security review: an approved offer stays tied to what was approved, and no stage move skips the Chief Auditor's
approval for a current audit client (§27.5)."""
import pytest

from app.engagements.models import Engagement
from app.sales.service import open_from_trigger
from tests.factories import login_as


@pytest.fixture
def audit_client(db, lit):
    e = Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC 2026 audit", status="in_progress", stage=5)
    db.add(e)
    db.commit()
    return e


def _approved(client, db, lit):
    o = open_from_trigger(db, lit["abc"].id, "case", "case-1", service="Bias audit", why_now="Mobley v. Workday", service_kind="bias_audit")
    db.commit()
    login_as(client, db, lit["chief"])
    assert client.post(f"/api/v1/opportunities/{o.id}/approve", json={"decision": "approve", "note": "No conflict"}).status_code == 200
    login_as(client, db, lit["sales"])
    return o


def test_changing_the_service_of_an_approved_offer_needs_a_new_approval(client, db, lit, audit_client):
    o = _approved(client, db, lit)
    r = client.patch(f"/api/v1/opportunities/{o.id}", json={"service": "Remediation of the bias audit findings"})
    assert r.status_code == 200, r.text
    assert r.json()["ca_decision"] is None and r.json()["can_send_offer"] is False and r.json()["approval"] == "Needed"
    assert client.post(f"/api/v1/opportunities/{o.id}/send-proposal", json={"summary": "Proposal"}).status_code == 409
    assert client.patch(f"/api/v1/opportunities/{o.id}", json={"stage": "won"}).status_code == 409


def test_a_stage_move_cannot_skip_the_chief_auditors_approval(client, db, lit, audit_client):
    o = open_from_trigger(db, lit["abc"].id, "case", "case-2", service="Bias audit", why_now="Case")
    db.commit()
    login_as(client, db, lit["sales"])
    for stage in ("won", "proposal"):
        r = client.patch(f"/api/v1/opportunities/{o.id}", json={"stage": stage})
        assert r.status_code == 409, (stage, r.text)
    r = client.post("/api/v1/opportunities/bulk", json={"ids": [o.id], "stage": "won"})
    assert r.status_code == 200 and r.json()["changed"] == 0 and r.json()["skipped"] == 1
    db.refresh(o)
    assert o.stage == "new"
    assert client.patch(f"/api/v1/opportunities/{o.id}", json={"stage": "lost"}).status_code == 200  # closing it is always allowed


def test_a_client_that_becomes_an_audit_client_needs_approval_before_won(client, db, lit):
    o = open_from_trigger(db, lit["nw"].id, "case", "case-3", service="Readiness review", why_now="Case", service_kind="readiness")
    db.commit()
    assert o.needs_ca_approval is False
    db.add(Engagement(organization_id=lit["nw"].id, client_id=lit["nw"].id, name="Northwind audit", status="in_progress", stage=2))
    db.commit()
    login_as(client, db, lit["sales"])
    r = client.patch(f"/api/v1/opportunities/{o.id}", json={"stage": "won"})
    assert r.status_code == 409, r.text
