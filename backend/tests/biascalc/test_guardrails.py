"""GenAI guardrail tests (spec §21 F11, Phase 4): Futran's prompt set against a client's chatbot, fake adapter by default.
No test here touches the network."""
from sqlalchemy import select

from app.biascalc import guardrails
from app.biascalc.models import GuardrailTestRun
from tests.factories import login_as


def test_the_prompt_set_covers_the_five_categories_and_every_prompt_can_fail():
    ps = guardrails.prompt_set()
    assert ps["version"]
    assert {p["category"] for p in ps["prompts"]} == {"prompt_injection", "jailbreak", "data_leakage", "harmful_output", "pii_echo"}
    assert all(p["fail_if_contains"] for p in ps["prompts"])
    assert len({p["id"] for p in ps["prompts"]}) == len(ps["prompts"])


def test_a_response_fails_when_it_contains_a_marker_regardless_of_case():
    p = {"id": "x", "fail_if_contains": ["CANARY-7731"]}
    assert guardrails.evaluate(p, "I can't help with that.")[0] is True
    assert guardrails.evaluate(p, "Sure: canary-7731")[0] is False


def test_the_fake_adapter_runs_and_the_result_is_a_suggestion(client, db, ats, people):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/systems/{s.id}/guardrail-tests", json={"endpoint_label": "Careers chatbot (sandbox)"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["adapter"] == "fake" and out["status"] == "suggested"
    assert out["passed_count"] + out["failed_count"] == len(guardrails.prompt_set()["prompts"])
    assert out["failed_count"] == len(guardrails.FAKE_FAILS)
    assert out["suggestion"] == {"question": "8.1.05", "answer": "yes", "checklist": "8.4", "text": f"Prompt set {out['prompt_set_version']}: {out['passed_count']} passed, {out['failed_count']} failed."}
    row = db.get(GuardrailTestRun, out["id"])
    assert row.organization_id == cid and row.run_by == people["aud"].id


def test_live_runs_need_the_setting_and_the_clients_written_permission(client, db, ats, people, monkeypatch):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/systems/{s.id}/guardrail-tests", json={"live": True, "endpoint_url": "https://chat.example/api"})
    assert r.status_code == 409 and "GUARDRAIL_TESTS_LIVE" in r.json()["detail"]
    client.app.state.settings = client.app.state.settings.model_copy(update={"guardrail_tests_live": True})
    called = []
    monkeypatch.setattr(guardrails, "LiveAdapter", lambda *a, **k: called.append(1))
    r = client.post(f"/api/v1/systems/{s.id}/guardrail-tests", json={"live": True, "endpoint_url": "https://chat.example/api"})
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} == {"permission_note", "permission_file_id"}
    assert called == [] and db.scalar(select(GuardrailTestRun)) is None


def test_accepting_records_the_answer_and_rejecting_needs_a_reason(client, db, ats, people):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    a = client.post(f"/api/v1/systems/{s.id}/guardrail-tests", json={}).json()["id"]
    assert client.post(f"/api/v1/guardrail-tests/{a}/decision", json={"decision": "reject"}).status_code == 422
    r = client.post(f"/api/v1/guardrail-tests/{a}/decision", json={"decision": "accept", "note": "Reviewed the two failures with the vendor."})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert client.post(f"/api/v1/guardrail-tests/{a}/decision", json={"decision": "reject", "note": "x"}).status_code == 409
    login_as(client, db, maria)
    assert client.post(f"/api/v1/systems/{s.id}/guardrail-tests", json={}).status_code in (403, 404)
