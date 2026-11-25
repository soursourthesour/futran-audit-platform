"""BUG-09: Review offers 'Correct with a reason' only while the server would accept the correction."""
from app.engagements.models import Engagement
from app.signoffs.service import CORRECTABLE_UNTIL
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401
from tests.signoffs.test_signoffs import _approved_dept, _u, rev  # noqa: F401


def _dept_block(client, cid, dept_id):
    return next(d for d in client.get(f"/api/v1/clients/{cid}/review").json()["departments"] if d["id"] == dept_id)


def test_correction_is_offered_only_until_the_stage_limit(client, db, rev):
    cid, e, maria, hr, copilot, chatgpt = rev
    so = _approved_dept(client, db, cid, hr, copilot)
    login_as(client, db, _u(db, "tom@abc.test"))
    assert _dept_block(client, cid, hr.id)["can_correct"] is True

    db.get(Engagement, e.id).stage = CORRECTABLE_UNTIL[2] + 1
    db.commit()
    assert _dept_block(client, cid, hr.id)["can_correct"] is False
    r = client.post(f"/api/v1/signoffs/{so['id']}/correct", json={"reason": "A use case was left out."})
    assert r.status_code == 409 and "can no longer be corrected" in r.text


def test_correction_is_not_offered_once_the_engagement_has_closed(client, db, rev):
    cid, e, maria, hr, copilot, chatgpt = rev
    _approved_dept(client, db, cid, hr, copilot)
    login_as(client, db, _u(db, "tom@abc.test"))
    db.get(Engagement, e.id).status = "completed"
    db.commit()
    assert _dept_block(client, cid, hr.id)["can_correct"] is False
