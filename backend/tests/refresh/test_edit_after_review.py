"""§25.3 step 6: a low-confidence or new-law change needs a second review of the value that is approved. If the
Chief Auditor edits it after the second reviewer concurred, the edited value goes back for a second review."""
from app.litigation.models import Case
from app.notifications.models import Notification
from app.refresh.models import RefreshProposalMeta
from app.regmaster.models import ProposedChange
from tests.factories import login_as
from tests.refresh.test_review import _decide, case_change  # noqa: F401


def _concur(client, db, lit, pc, note="Docket confirms it."):
    login_as(client, db, lit["qa"])
    r = client.post(f"/api/v1/reg/changes/{pc.id}/second-review", json={"outcome": "concur", "note": note})
    assert r.status_code == 200, r.text


def test_edit_after_concurrence_goes_back_for_a_second_review(client, db, lit, case_change):
    case, pc, _run = case_change
    _concur(client, db, lit, pc)
    login_as(client, db, lit["chief"])
    r = _decide(client, pc, "edit_approve", new_value="stayed", note="Stayed, not trial")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "pending" and out["second_review"]["outcome"] is None and out["pending_edit"] == "stayed"
    db.expire_all()
    assert db.get(Case, case.id).stage == "discovery"  # nothing applied
    assert db.query(Notification).filter_by(user_id=lit["qa"].id, kind="second_review").count() >= 1
    # approving now is refused until the edited value is reviewed
    assert _decide(client, pc, "approve").status_code == 409
    _concur(client, db, lit, pc, "Stayed pending appeal: confirmed")
    login_as(client, db, lit["chief"])
    r = _decide(client, pc, "approve")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(ProposedChange, pc.id).status == "edited_approved" and db.get(Case, case.id).stage == "stayed"
    assert db.get(RefreshProposalMeta, pc.id).edited_value == "stayed"


def test_edit_to_the_reviewed_value_is_approved_at_once(client, db, lit, case_change):
    case, pc, _run = case_change
    _concur(client, db, lit, pc)
    login_as(client, db, lit["chief"])
    r = _decide(client, pc, "edit_approve", new_value="trial")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Case, case.id).stage == "trial"
