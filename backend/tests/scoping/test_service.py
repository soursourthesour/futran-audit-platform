"""Spec §4.4 rules: answers keep source and confidence, client answers never overwrite the rep's, unknowns add A-05
with an assumption, lock before use, unlock makes a new version; §4.5: removing a proposed line needs a reason."""
import pytest
from sqlalchemy import select

from app.core.errors import Conflict, Invalid
from app.sales.models import OpportunityActivity
from app.scoping import bridge, service
from app.scoping.models import ScopingAnswer, ScopingQuestionnaire


def rep(db, q, world, **answers):
    service.save_answers(db, q, [{"code": c, **(v if isinstance(v, dict) else {"value": v})} for c, v in answers.items()], actor=world["sales"])


def test_starting_a_questionnaire_moves_the_opportunity_to_scoping_once(db, world):
    q = service.start(db, world["opp"], world["sales"])
    again = service.start(db, world["opp"], world["sales"])
    assert again.id == q.id and q.version == 1 and q.status == "draft" and q.bank_version == 1
    assert q.prospect_id == world["acme"].id
    assert world["opp"].stage == "scoping"
    acts = list(db.scalars(select(OpportunityActivity).where(OpportunityActivity.opportunity_id == world["opp"].id)))
    assert sorted(a.summary for a in acts) == ["Scoping questionnaire started (recorded on the call).", "Stage moved to Scoping."]


def test_total_ai_systems_is_the_sum_of_the_counts_until_overridden(db, world):
    q = service.start(db, world["opp"], world["sales"])
    rep(db, q, world, **{"SQ-C.01": {"value": 3, "confidence": "estimate"}, "SQ-C.02": 1, "SQ-C.03": 2})
    eff = service.effective_answers(db, q)
    assert eff["SQ-C.07"].value == 6 and eff["SQ-C.07"].confidence == "estimate"
    rep(db, q, world, **{"SQ-C.07": 9})
    assert service.effective_answers(db, q)["SQ-C.07"].value == 9
    a = db.scalar(select(ScopingAnswer).where(ScopingAnswer.question_code == "SQ-C.07"))
    assert a.source == "rep" and a.answered_by == world["sales"].id and a.slot == "rep"


def test_client_answer_never_overwrites_the_rep_and_shows_as_a_conflict_until_resolved(db, world):
    q = service.start(db, world["opp"], world["sales"])
    rep(db, q, world, **{"SQ-C.07": {"value": 6, "confidence": "estimate"}})
    service.save_client_answers(db, q, [{"code": "SQ-C.07", "value": 12}], send_id="send-1", name="Pat Champion")
    assert service.effective_answers(db, q)["SQ-C.07"].value == 6  # the rep's value stands
    conflicts = service.conflicts(db, q)
    assert [(c["code"], c["rep"]["value"], c["client"]["value"]) for c in conflicts] == [("SQ-C.07", 6, 12)]
    with pytest.raises(Conflict):
        service.lock(db, q.id, world["sales"])
    service.resolve(db, q, "SQ-C.07", "client", None, world["sales"])
    a = service.effective_answers(db, q)["SQ-C.07"]
    assert a.value == 12 and a.source == "rep_confirmed_client" and service.conflicts(db, q) == []
    # the client changes the answer again: a new conflict
    service.save_client_answers(db, q, [{"code": "SQ-C.07", "value": 14}], send_id="send-1", name="Pat Champion")
    assert [c["code"] for c in service.conflicts(db, q)] == ["SQ-C.07"]
    service.resolve(db, q, "SQ-C.07", "other", 13, world["sales"])
    assert service.effective_answers(db, q)["SQ-C.07"].value == 13 and service.conflicts(db, q) == []
    # a client answer to a question the rep left blank is used as it is
    service.save_client_answers(db, q, [{"code": "SQ-B.01", "value": 600}], send_id="send-1", name="Pat Champion")
    assert service.effective_answers(db, q)["SQ-B.01"].source == "client"


def test_client_cannot_answer_internal_questions(db, world):
    q = service.start(db, world["opp"], world["sales"])
    service.save_client_answers(db, q, [{"code": "SQ-A.02", "value": "$1m"}, {"code": "SQ-B.01", "value": 40}], send_id="s", name="P", allowed={"SQ-A.02", "SQ-B.01"})
    eff = service.effective_answers(db, q)
    assert "SQ-A.02" not in eff and eff["SQ-B.01"].value == 40


def test_suggested_lines_with_reasons_and_removal_needs_a_reason(db, world):
    q = service.start(db, world["opp"], world["sales"])
    rep(db, q, world, **{"SQ-C.07": {"value": 6, "confidence": "estimate"}, "SQ-B.01": 600, "SQ-C.10": "partial",
                         "SQ-C.11": ["okta_entra", "m365", "expense"], "SQ-C.12": ["m365_copilot"]})
    lines = {x["code"]: x for x in service.suggest_lines(db, q.id)}
    assert set(lines) == {"A-02a", "A-05", "A-06b", "X-04"}
    assert lines["A-02a"] == {"code": "A-02a", "qty": 1, "reason": "Because SQ-C.07 = 6 (estimate)", "rule_code": "MR-01a", "removed_reason": None}
    with pytest.raises(Invalid):
        service.remove_line(db, q, "X-04", "  ", world["sales"])
    service.remove_line(db, q, "X-04", "Client already has a Copilot partner", world["sales"])
    lines = {x["code"]: x for x in service.suggest_lines(db, q.id)}
    assert lines["X-04"]["removed_reason"] == "Client already has a Copilot partner"
    assert q.removed_lines[0]["rule_code"] == "MR-17" and q.removed_lines[0]["by"] == world["sales"].id
    service.restore_line(db, q, "X-04", world["sales"])
    assert {x["code"]: x for x in service.suggest_lines(db, q.id)}["X-04"]["removed_reason"] is None


def test_unknown_ai_system_count_adds_a05_and_a_proposal_assumption(db, world):
    q = service.start(db, world["opp"], world["sales"])
    rep(db, q, world, **{"SQ-C.07": {"value": None, "confidence": "unknown"}, "SQ-C.08": {"value": None, "confidence": "unknown"}})
    assert [x["code"] for x in service.suggest_lines(db, q.id)] == ["A-05"]
    texts = [a["text"] for a in service.assumptions(db, q)]
    assert any("discovery sweep (A-05)" in t for t in texts)
    assert "Vendor review priced per vendor once the inventory is complete." in texts


def test_lock_then_unlock_makes_a_new_version_and_the_old_one_stays_locked(db, world):
    q = service.start(db, world["opp"], world["sales"])
    rep(db, q, world, **{"SQ-C.07": 6})
    locked = service.lock(db, q.id, world["sales"])
    assert locked.status == "locked" and locked.locked_by == world["sales"].id and locked.locked_at is not None
    with pytest.raises(Conflict):
        rep(db, q, world, **{"SQ-C.07": 7})
    v2 = service.unlock(db, q.id, world["sales"])
    assert v2.version == 2 and v2.previous_id == q.id and v2.status == "draft"
    assert db.get(ScopingQuestionnaire, q.id).status == "locked"
    assert service.effective_answers(db, v2)["SQ-C.07"].value == 6
    assert service.current(db, world["opp"].id).id == v2.id


def test_running_estimate_reads_catalog_list_prices(db, world, monkeypatch):
    q = service.start(db, world["opp"], world["sales"])
    rep(db, q, world, **{"SQ-C.07": 6, "SQ-B.01": 600, "SQ-F.01": "monitor"})
    assert service.estimate(db, q)["available"] is False

    class Item:
        def __init__(self, price, billing, periods=1, basis="$"):
            self.list_price, self.billing, self.periods_per_year, self.basis, self.included_quantities = price, billing, periods, basis, None
            self.sellable_status, self.status, self.name = "available", "active", "x"

    monkeypatch.setattr(bridge, "catalog_items", lambda db, codes: {"A-02a": Item(15000, "One-time"), "M-01a": Item(12000, "Annual")})
    est = service.estimate(db, q)
    assert est["available"] is True and est["one_time"] == 15000 and est["recurring_y1"] == 12000
    assert est["missing"] == ["A-06b"]
