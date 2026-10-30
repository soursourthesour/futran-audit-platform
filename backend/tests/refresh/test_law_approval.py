"""§25.3 step 7: approving a law change writes the next LawVersion (regulatory master), then client alerts wait for
the Chief Auditor and Sales gets an opportunity."""
import json

from sqlalchemy import select

from app.clientalerts.models import AlertSend
from app.laws.models import Regulation
from app.refresh.claude import FakeRefreshClient
from app.refresh.pipeline import execute_run, start_run
from app.regmaster.models import LawVersion, ProposedChange
from app.sales.models import Opportunity
from app.staffalerts.models import StaffAlert
from tests.factories import login_as
from tests.refresh.conftest import change


def _propose(db, lit, settings, items):
    run = start_run(db, kind="law", actor=lit["chief"], jurisdiction_codes=["US-IL"], settings=settings)
    execute_run(db, settings, run, FakeRefreshClient({"US-IL": {"changes": items}}))
    db.commit()
    return run, list(db.scalars(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id)))


def test_approve_writes_version_2_and_queues_the_client_alert(client, db, lit, reg, settings):
    run, (pc,) = _propose(db, lit, settings, [change(reg["law"])])
    login_as(client, db, lit["chief"])
    r = client.post(f"/api/v1/reg/changes/{pc.id}/decide", json={"action": "approve", "note": "Public act confirms the date"})
    assert r.status_code == 200, r.text
    db.expire_all()
    law = db.get(Regulation, reg["law"].id)
    v = db.get(LawVersion, law.current_version_id)
    assert v.version_no == 2 and v.effective_on.isoformat() == "2027-01-01" and v.approved_by == lit["chief"].id
    pc = db.get(ProposedChange, pc.id)
    assert pc.status == "approved" and pc.applied_version_id == v.id
    sends = list(db.scalars(select(AlertSend)))
    assert [s.organization_id for s in sends] == [lit["abc"].id] and sends[0].status == "waiting_approval"
    assert sends[0].todo_items and sends[0].todo_items[0]["code"] == "IL-01"  # to-dos come from the new version's requirements
    assert db.scalar(select(Opportunity).where(Opportunity.trigger == "law_change", Opportunity.organization_id == lit["abc"].id)) is not None
    assert all(a.resolved_at for a in db.scalars(select(StaffAlert).where(StaffAlert.refresh_run_id == run.id)))


def test_edit_and_approve_takes_the_reviewers_value(client, db, lit, reg, settings):
    run, (pc,) = _propose(db, lit, settings, [change(reg["law"])])
    login_as(client, db, lit["chief"])
    r = client.post(f"/api/v1/reg/changes/{pc.id}/decide", json={"action": "edit_approve", "new_value": "2027-07-01"})
    assert r.status_code == 200, r.text
    db.expire_all()
    v = db.get(LawVersion, db.get(Regulation, reg["law"].id).current_version_id)
    assert v.effective_on.isoformat() == "2027-07-01" and db.get(ProposedChange, pc.id).status == "edited_approved"


def test_new_law_needs_second_review_then_creates_the_law(client, db, lit, reg, settings):
    new = change(reg["law"], change_type="new_law", regulation_id=None, field_path="new_law", old_value=None,
                 new_value=json.dumps({"jurisdiction_code": "US-IL", "short_name": "HB 0000 AI Notice Act (demo)", "type": "statute"}), summary="New Illinois law.")
    run, (pc,) = _propose(db, lit, settings, [new])
    login_as(client, db, lit["chief"])
    assert client.post(f"/api/v1/reg/changes/{pc.id}/decide", json={"action": "approve"}).status_code == 409
    login_as(client, db, lit["qa"])
    assert client.post(f"/api/v1/reg/changes/{pc.id}/second-review", json={"outcome": "concur", "note": "Signed act on ilga.gov"}).status_code == 200
    login_as(client, db, lit["chief"])
    r = client.post(f"/api/v1/reg/changes/{pc.id}/decide", json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert db.scalar(select(Regulation).where(Regulation.short_name == "HB 0000 AI Notice Act (demo)")) is not None


def test_turning_off_letter_updates_clears_the_flag(client, db, lit, reg, settings):
    from app.regmaster.models import ChangeImpact

    run, (pc,) = _propose(db, lit, settings, [change(reg["law"])])
    for imp in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == pc.id)):
        imp.letter_update_needed = True
    db.commit()
    login_as(client, db, lit["chief"])
    client.post(f"/api/v1/reg/changes/{pc.id}/decide", json={"action": "approve", "update_letters": False, "notify_clients": False})
    db.expire_all()
    assert not any(i.letter_update_needed for i in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == pc.id)))
    assert db.query(AlertSend).count() == 0
