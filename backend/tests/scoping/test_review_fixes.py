"""Fresh-review fixes: switching a rule on or off needs approval; bad rules are refused at save and never break scoping;
forwarded links never outlive the link they came from; a second pending edit keeps the first."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.clock import utcnow
from app.core.errors import Invalid
from app.scoping import bank, bridge, rulebook, sending, service
from app.scoping.models import MappingRule, QuestionnaireSend
from tests.factories import login_as


def _bank(db):
    return {q.code: q.type for q in bank.questions(db, include_inactive=True)}


def _partial_inventory(db, world):
    q = service.start(db, world["opp"], world["sales"])
    service.save_answers(db, q, [{"code": "SQ-C.10", "value": "partial"}], actor=world["sales"])
    return q


# ---- 1. switching a rule off or on is a rule change: pending until the Pricing Approver approves
def test_admin_switching_a_rule_off_waits_for_approval(client, db, world):
    q = _partial_inventory(db, world)
    db.commit()
    login_as(client, db, world["admin"])
    r = client.post("/api/v1/scoping/rules/MR-03/active", json={"active": False})
    assert r.status_code == 200 and r.json()["active"] is True and r.json()["pending"]["active"] is False
    assert "A-05" in [x["code"] for x in service.suggest_lines(db, q.id)]  # still proposing until approved
    with pytest.raises(Exception):
        rulebook.approve(db, "MR-03", world["admin"].id)  # not by the person who asked
    rulebook.approve(db, "MR-03", world["chief"].id)
    assert "A-05" not in [x["code"] for x in service.suggest_lines(db, q.id)]


# ---- 2. bad rules: refused at save; and an approved bad rule is skipped and flagged, never a 500
@pytest.mark.parametrize("inputs,qty", [
    ({"all": [{"q": "SQ-C.07", "op": "gte", "value": "ten"}]}, {"const": 1}),
    ({"all": [{"q": "SQ-C.07", "op": "nearly", "value": 3}]}, {"const": 1}),
    ({"all": [{"q": "SQ-C.07", "op": "between", "value": [1]}]}, {"const": 1}),
    ({"all": [{"q": "SQ-C.10", "op": "gte", "value": 2}]}, {"const": 1}),  # a numeric test on a one-choice question
    ({"all": [{"q": "SQ-C.07", "op": "gte", "value": 1}]}, {"answer": "SQ-C.07", "add": "one"}),
    ({"all": [{"q": "SQ-C.07", "op": "gte", "value": 1}]}, {"double": "SQ-C.07"}),
    ({"all": "SQ-C.07"}, {"const": 1}),
])
def test_badly_written_rules_are_refused_at_save(db, world, inputs, qty):
    with pytest.raises(Invalid):
        rulebook.propose_edit(db, "MR-19", {"inputs": inputs, "qty_formula": qty}, world["admin"].id, _bank(db))


def test_an_approved_rule_that_cannot_run_is_skipped_and_flagged(client, db, world):
    q = service.start(db, world["opp"], world["sales"])
    service.save_answers(db, q, [{"code": "SQ-C.07", "value": 6}], actor=world["sales"])
    bad = db.scalar(select(MappingRule).where(MappingRule.code == "MR-01b"))
    bad.inputs = {"all": [{"q": "SQ-C.07", "op": "gte", "value": "ten"}]}  # e.g. written before validation existed
    db.commit()
    lines = service.suggest_lines(db, q.id)
    assert "A-02a" in [x["code"] for x in lines]
    assert [e["rule_code"] for e in service.rule_errors(db, q)] == ["MR-01b"]
    login_as(client, db, world["sales"])
    v = client.get(f"/api/v1/scoping/opportunities/{world['opp'].id}")
    assert v.status_code == 200 and "Rule MR-01b could not be applied" in v.json()["rule_errors"][0]["message"]
    assert client.get(f"/api/v1/scoping/{q.id}/review").status_code == 200
    assert client.post(f"/api/v1/scoping/{q.id}/lock", json={}).status_code == 200
    login_as(client, db, world["admin"])
    rows = {r["code"]: r for r in client.get("/api/v1/scoping/rules").json()["rules"]}
    assert "could not be applied" in rows["MR-01b"]["flag"]


# ---- 3. forwarded links
def _send(db, settings, world):
    q = service.start(db, world["opp"], world["sales"])
    s = sending.send(db, settings, q, world["sales"], contact={"name": "Pat", "email": "pat@acme.example"}, question_codes=["SQ-C.07"])
    return q, s


def test_revoking_a_link_revokes_the_links_forwarded_from_it(db, world, settings):
    q, s = _send(db, settings, world)
    f = sending.forward(db, settings, s, "Tom", "tom@acme.example")
    sending.revoke(db, s)
    assert f.revoked_at is not None and f.status == "revoked"


def test_a_forwarded_link_expires_no_later_than_its_original(db, world, settings):
    q, s = _send(db, settings, world)
    s.expires_at = utcnow() + timedelta(days=2)
    f = sending.forward(db, settings, s, "Tom", "tom@acme.example")
    assert f.expires_at <= s.expires_at


# ---- 4. a second pending edit keeps the first; a pending line code is checked against the price list
def test_a_second_pending_edit_keeps_the_first(db, world):
    rulebook.propose_edit(db, "MR-19", {"note": "First"}, world["admin"].id, _bank(db))
    r = rulebook.propose_edit(db, "MR-19", {"reason_template": "M&A: {SQ-A.01}"}, world["admin"].id, _bank(db))
    assert r.pending["note"] == "First" and r.pending["reason_template"] == "M&A: {SQ-A.01}"


def test_a_pending_line_code_missing_from_the_price_list_is_flagged(db, world, monkeypatch):
    monkeypatch.setattr(bridge, "catalog_items", lambda db, codes: {c: type("I", (), {"status": "active"})() for c in codes if c in ("X-05",)})
    rulebook.propose_edit(db, "MR-19", {"line_code": "X-99"}, world["admin"].id, _bank(db))
    assert "X-99" in rulebook.flags(db)["MR-19"]
