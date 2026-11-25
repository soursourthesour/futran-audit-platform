"""Y05: the Chief Auditor does not approve an offer they own or opened (spec §6 rule 2); another Chief Auditor does."""
from app.audit_log.models import AuditLog
from app.sales.models import Opportunity
from app.sales.service import open_from_trigger
from tests.factories import login_as

SOD = "You prepared this item, so you cannot approve it. Another approver must sign it off."


def _offer(db, lit, **who):
    o = open_from_trigger(db, lit["abc"].id, "case", "case-1", service="Bias audit", why_now="Mobley v. Workday", service_kind="bias_audit")
    for k, v in who.items():
        setattr(o, k, v)
    db.commit()
    return o


def _approve(client, o):
    return client.post(f"/api/v1/opportunities/{o.id}/approve", json={"decision": "approve", "note": "No conflict"})


def test_the_owner_cannot_approve_their_own_offer(client, db, lit):
    o = _offer(db, lit, owner_id=lit["chief"].id)
    login_as(client, db, lit["chief"])
    r = _approve(client, o)
    assert r.status_code == 403 and r.json()["detail"] == SOD
    db.expire_all()
    assert db.get(Opportunity, o.id).ca_decision is None
    assert db.query(AuditLog).filter_by(object_id=o.id, action="opportunity.approved").count() == 0
    login_as(client, db, lit["chief2"])
    assert _approve(client, o).status_code == 200


def test_whoever_opened_the_offer_cannot_approve_it(client, db, lit):
    o = _offer(db, lit, owner_id=lit["sales"].id, created_by=lit["chief"].id)
    login_as(client, db, lit["chief"])
    assert _approve(client, o).status_code == 403


def test_the_owner_may_still_decline_their_own_offer(client, db, lit):
    o = _offer(db, lit, owner_id=lit["chief"].id)
    login_as(client, db, lit["chief"])
    r = client.post(f"/api/v1/opportunities/{o.id}/approve", json={"decision": "decline", "note": "Fieldwork under way"})
    assert r.status_code == 200 and r.json()["ca_decision"] == "declined"
