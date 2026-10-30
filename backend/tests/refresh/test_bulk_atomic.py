"""Bulk decisions on M3 (§25.3 step 6): a decision that is refused is reported and the others go on, but an
unexpected failure later in the request undoes the decisions already made in it (nothing half-applied)."""
import pytest

from app.regmaster import changes
from app.regmaster.models import ProposedChange
from tests.factories import login_as


def test_failure_after_the_first_item_rolls_back_the_whole_request(client, db, lit, reg, monkeypatch):
    law = reg["law"]
    a = changes.propose(db, actor_id=lit["admin"].id, regulation_id=law.id, field_path="law.cure_period", new_value="30 days", summary="Cure period", origin="admin_edit")
    b = changes.propose(db, actor_id=lit["admin"].id, regulation_id=law.id, field_path="law.penalty_text", new_value="Up to $1,000", summary="Penalty", origin="admin_edit")
    db.commit()
    import app.refresh.router as router

    real, calls = router.decide, []

    def flaky(*args, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("database went away")
        return real(*args, **kw)

    monkeypatch.setattr(router, "decide", flaky)
    login_as(client, db, lit["chief"])
    with pytest.raises(RuntimeError):
        client.post("/api/v1/reg/changes/bulk", json={"ids": [a.id, b.id], "action": "hold", "note": "Wait for the rules"})
    db.expire_all()
    assert db.get(ProposedChange, a.id).status == "pending"
    assert db.get(ProposedChange, b.id).status == "pending"


def test_refused_items_are_reported_and_the_others_are_kept(client, db, lit, reg):
    law = reg["law"]
    a = changes.propose(db, actor_id=lit["admin"].id, regulation_id=law.id, field_path="law.cure_period", new_value="30 days", summary="Cure period", origin="admin_edit")
    b = changes.propose(db, actor_id=lit["admin"].id, regulation_id=law.id, field_path="law.penalty_text", new_value="Up to $1,000", summary="Penalty", origin="admin_edit")
    b.status = "rejected"
    db.commit()
    login_as(client, db, lit["chief"])
    r = client.post("/api/v1/reg/changes/bulk", json={"ids": [a.id, b.id], "action": "hold", "note": "Wait"})
    assert [x["ok"] for x in r.json()["results"]] == [True, False]
    db.expire_all()
    assert db.get(ProposedChange, a.id).status == "held"
