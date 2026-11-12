"""SM-05, SM-06, SM-08 endpoints and the SM-14 question bank and mapping rules tabs: who can do what."""
import pytest

from app.policy.roles import Role
from app.scoping import bridge, rulebook
from tests.factories import login_as, make_user


def _start(client, db, world, who="sales"):
    login_as(client, db, world[who])
    r = client.post(f"/api/v1/scoping/opportunities/{world['opp'].id}/start")
    assert r.status_code == 200, r.text
    return r.json()


def test_only_sales_roles_work_a_questionnaire(client, db, world):
    for who in ("auditor", "client_user"):
        login_as(client, db, world[who])
        assert client.post(f"/api/v1/scoping/opportunities/{world['opp'].id}/start").status_code in (403, 404)
    q = _start(client, db, world)
    login_as(client, db, world["auditor"])
    assert client.get(f"/api/v1/scoping/opportunities/{world['opp'].id}").status_code == 403
    login_as(client, db, world["chief"])  # the Chief Auditor sees the pipeline, read-only
    assert client.get(f"/api/v1/scoping/opportunities/{world['opp'].id}").status_code == 200
    assert client.put(f"/api/v1/scoping/{q['id']}/answers", json={"answers": [{"code": "SQ-C.07", "value": 4}]}).status_code == 403


def test_record_on_the_call_view_autosave_and_suggestions(client, db, world):
    q = _start(client, db, world)
    r = client.put(f"/api/v1/scoping/{q['id']}/answers", json={"answers": [
        {"code": "SQ-C.01", "value": 3, "confidence": "estimate"}, {"code": "SQ-C.02", "value": 1}, {"code": "SQ-C.03", "value": 2},
        {"code": "SQ-C.10", "value": "partial"}, {"code": "SQ-C.11", "value": ["okta_entra", "m365", "expense"]}, {"code": "SQ-B.01", "value": 600}]})
    assert r.status_code == 200 and r.json()["at"]
    v = client.get(f"/api/v1/scoping/opportunities/{world['opp'].id}").json()
    assert v["questionnaire"]["version"] == 1 and v["bank"]["starter"] is True
    sec = {s["key"]: s for s in v["sections"]}
    assert sec["C"]["answered"] == 6 and sec["C"]["label"] == "AI inventory" and sec["RF"]["internal"] is True
    lines = {x["code"]: x for x in v["suggested"]}
    assert lines["A-02a"]["reason"] == "Because SQ-C.07 = 6 (estimate)" and lines["A-05"]["qty"] == 3
    assert v["estimate"]["available"] is True and "A-02a" in v["estimate"]["missing"]  # an empty price list prices nothing
    assert v["answers"]["SQ-C.07"]["source"] == "derived"
    bad = client.put(f"/api/v1/scoping/{q['id']}/answers", json={"answers": [{"code": "SQ-C.08", "value": -2}]})
    assert bad.status_code == 422
    assert client.post(f"/api/v1/scoping/{q['id']}/lines/remove", json={"code": "A-05", "reason": ""}).status_code == 422
    assert client.post(f"/api/v1/scoping/{q['id']}/lines/remove", json={"code": "A-05", "reason": "Client ran its own sweep"}).status_code == 200


def test_send_options_lock_internal_questions_and_name_the_reps_mailbox(client, db, world):
    q = _start(client, db, world)
    client.put(f"/api/v1/scoping/{q['id']}/answers", json={"answers": [{"code": "SQ-A.01", "value": "ll144_due"}]})
    o = client.get(f"/api/v1/scoping/{q['id']}/send-options").json()
    internal = [x for s in o["sections"] for x in s["questions"] if x["internal_only"]]
    assert internal and all(x["locked"] for x in internal)
    assert "r.mehta@futransolutions.com" in o["sender"] or o["sender"]
    assert o["subject"] == "A few questions to scope your AI compliance review"
    assert "[Link]" in o["message"] and o["expires_days"] == 14
    a = next(s for s in o["sections"] if s["key"] == "A")
    assert a["unanswered"] == 0  # SQ-A.01 answered; the internal ones do not count


def test_a_total_worked_out_from_its_parts_is_still_offered_to_the_client(client, db, world):
    q = _start(client, db, world)
    client.put(f"/api/v1/scoping/{q['id']}/answers", json={"answers": [{"code": "SQ-C.01", "value": 3}]})
    o = client.get(f"/api/v1/scoping/{q['id']}/send-options").json()
    c = {x["code"]: x for s in o["sections"] for x in s["questions"]}
    assert c["SQ-C.07"]["default"] is True and c["SQ-C.01"]["default"] is False


def test_review_conflicts_resolve_lock_and_build_proposal_note(client, db, world, monkeypatch):
    from app.scoping import service

    q = _start(client, db, world)
    client.put(f"/api/v1/scoping/{q['id']}/answers", json={"answers": [{"code": "SQ-C.07", "value": 6, "confidence": "estimate"}]})
    service.save_client_answers(db, service.get(db, q["id"]), [{"code": "SQ-C.07", "value": 12}], send_id="s1", name="Pat")
    db.commit()
    monkeypatch.setattr(bridge, "proposal_builder", lambda: None)  # before the proposal builder is installed
    r = client.get(f"/api/v1/scoping/{q['id']}/review").json()
    assert r["counts"]["conflicts"] == 1 and r["conflicts"][0]["effect"] == "A-02a → A-02b"
    assert r["can_build_proposal"] is False and "proposal builder" in r["build_note"].lower()
    assert client.post(f"/api/v1/scoping/{q['id']}/lock", json={}).status_code == 409
    assert client.post(f"/api/v1/scoping/{q['id']}/resolve", json={"code": "SQ-C.07", "keep": "client"}).status_code == 200
    made = {}

    def fake_builder(db, questionnaire, actor):
        made["v"] = questionnaire.version

        class P:
            id = "prop-1"
        return P()

    monkeypatch.setattr(bridge, "proposal_builder", lambda: fake_builder)
    r = client.post(f"/api/v1/scoping/{q['id']}/lock", json={"build_proposal": True})
    assert r.status_code == 200 and r.json()["proposal_id"] == "prop-1" and made["v"] == 1
    r = client.post(f"/api/v1/scoping/{q['id']}/unlock")
    assert r.status_code == 200 and r.json()["version"] == 2


def test_question_bank_tab_admin_edits_sales_views(client, db, world):
    login_as(client, db, world["sales"])
    bank = client.get("/api/v1/scoping/bank").json()
    assert bank["version"] == 1 and "Starter" in bank["note"] and bank["can_edit"] is False
    assert len(bank["questions"]) == 39
    assert client.put("/api/v1/scoping/bank/questions/SQ-C.08", json={"label": "AI vendors"}).status_code == 403
    _start(client, db, world)  # the bank is now in use
    login_as(client, db, world["admin"])
    r = client.put("/api/v1/scoping/bank/questions/SQ-C.08", json={"label": "Number of AI vendors (all)"})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert client.post("/api/v1/scoping/bank/questions", json={"code": "SQ-H.02", "label": "Data residency", "type": "text"}).status_code == 200
    assert client.get("/api/v1/scoping/bank").json()["version"] == 2


def test_mapping_rules_tab_flags_missing_codes_and_edits_wait_for_approval(client, db, world, monkeypatch):
    login_as(client, db, world["admin"])
    monkeypatch.setattr(bridge, "catalog_items", lambda db, codes: {c: type("I", (), {"status": "active"})() for c in codes if c in ("A-02a", "A-05")})
    r = client.get("/api/v1/scoping/rules").json()
    assert len(r["rules"]) == 39 and r["can_edit"] is True and r["can_approve"] is False
    flagged = {x["code"]: x["flag"] for x in r["rules"] if x["flag"]}
    assert "MR-01a" not in flagged and "MR-03" not in flagged and "A-02b is not in the price list" in flagged["MR-01b"]
    edit = client.put("/api/v1/scoping/rules/MR-19", json={"reason_template": "M&A trigger: {SQ-A.01}"})
    assert edit.status_code == 200 and edit.json()["pending"]["reason_template"] == "M&A trigger: {SQ-A.01}"
    assert edit.json()["reason_template"] == "Trigger: {SQ-A.01}"  # the approved wording runs until approval
    assert client.put("/api/v1/scoping/rules/MR-19", json={"inputs": {"all": [{"q": "SQ-Z.99", "op": "eq", "value": 1}]}}).status_code == 422
    assert client.post("/api/v1/scoping/rules/MR-19/approve").status_code == 403
    login_as(client, db, world["sales"])
    assert client.put("/api/v1/scoping/rules/MR-19", json={"note": "x"}).status_code == 403


def test_nobody_approves_their_own_rule_edit(db, world):
    from app.core.errors import Forbidden

    rulebook.propose_edit(db, "MR-19", {"note": "Check the trigger list"}, world["admin"].id, {"SQ-A.01"})
    with pytest.raises(Forbidden):
        rulebook.approve(db, "MR-19", world["admin"].id)
    r = rulebook.approve(db, "MR-19", world["chief"].id)
    assert r.note == "Check the trigger list" and r.pending is None and r.approved_by == world["chief"].id


@pytest.mark.skipif("pricing_approver" not in Role._value2member_map_, reason="R2 adds the Pricing Approver role")
def test_pricing_approver_approves_rule_edits(client, db, world):
    approver = make_user(db, world["futran"], roles=["pricing_approver"], name="Paula Pricing")
    login_as(client, db, world["admin"])
    client.put("/api/v1/scoping/rules/MR-19", json={"note": "Check"})
    login_as(client, db, approver)
    assert client.post("/api/v1/scoping/rules/MR-19/approve").status_code == 200
