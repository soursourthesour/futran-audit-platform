"""The upgraded refresh endpoints: one pipeline for laws and litigation; earlier runs stay readable."""
from sqlalchemy import select

from app.laws.models import LawRefreshRun, RegulationProposal
from app.refresh.claude import FakeRefreshClient
from app.refresh.models import RefreshRun
from app.regmaster.models import ProposedChange
from tests.factories import login_as
from tests.refresh.conftest import change


def test_run_from_the_screen_uses_the_pipeline(client, db, lit, reg):
    client.app.state.refresh_client_factory = lambda s: FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}})
    login_as(client, db, lit["chief"])
    r = client.post("/api/v1/admin/laws/refresh", json={"kind": "law", "scope_mode": "chosen", "jurisdiction_codes": ["US-IL"]})
    assert r.status_code == 200, r.text
    run = client.get(f"/api/v1/admin/laws/refresh/{r.json()['id']}").json()
    assert run["status"] == "completed" and run["proposals_created"] == 1 and run["legacy"] is False
    assert run["model_id"] == "fake-claude" and run["prompt_version"] and run["cost_usd"] > 0 and run["responses"]
    assert db.query(LawRefreshRun).count() == 0 and db.query(ProposedChange).count() == 1
    q = client.get("/api/v1/reg/changes?kind=law").json()
    assert q["items"][0]["subject"] == reg["law"].short_name and q["items"][0]["old_value"] == "2026-01-01"


def test_without_a_client_the_run_is_refused(client, db, lit, reg):
    login_as(client, db, lit["chief"])
    r = client.post("/api/v1/admin/laws/refresh", json={"kind": "law", "jurisdiction_codes": ["US-IL"]})
    assert r.status_code == 409


def test_earlier_runs_and_proposals_stay_readable(client, db, lit, reg):
    old = LawRefreshRun(jurisdiction_ids=[reg["il"].id], requested_by=lit["admin"].id, status="completed", warnings=[])
    db.add(old)
    db.flush()
    db.add(RegulationProposal(run_id=old.id, jurisdiction_id=reg["il"].id, change_type="add", proposed={"short_name": "Old idea"}, rationale="r", sources=[{"title": "t", "url": "https://ilga.gov"}]))
    db.commit()
    login_as(client, db, lit["chief"])
    runs = client.get("/api/v1/admin/laws/refresh").json()
    assert runs[0]["legacy"] is True and runs[0]["id"] == old.id
    d = client.get(f"/api/v1/admin/laws/refresh/{old.id}").json()
    assert d["proposals"][0]["proposed"]["short_name"] == "Old idea"


def test_litigation_runs_need_the_litigation_permission(client, db, lit, reg):
    client.app.state.refresh_client_factory = lambda s: FakeRefreshClient({})
    login_as(client, db, lit["admin"])
    assert client.post("/api/v1/admin/laws/refresh", json={"kind": "litigation", "scope_mode": "chosen", "jurisdiction_codes": ["US"]}).status_code == 403
    login_as(client, db, lit["chief"])
    r = client.post("/api/v1/admin/laws/refresh", json={"kind": "litigation", "scope_mode": "chosen", "jurisdiction_codes": ["US"]})
    assert r.status_code == 200 and db.get(RefreshRun, r.json()["id"]).kind == "litigation"
    assert client.get("/api/v1/admin/laws/refresh?kind=litigation").json()[0]["kind"] == "litigation"


def test_run_settings_and_schedule(client, db, lit, reg):
    login_as(client, db, lit["chief"])
    s = client.get("/api/v1/admin/laws/refresh-settings/law").json()
    assert s["every_days"] == 14 and s["schedule_enabled"] is False and s["checks"] == ["new_laws", "amendments", "rules_guidance", "enforcement"]  # off until turned on
    r = client.put("/api/v1/admin/laws/refresh-settings/law", json={"schedule_enabled": True, "every_days": 7, "cost_cap_usd": 2.5, "source_set": "with_secondary"})
    assert r.status_code == 200 and r.json()["every_days"] == 7 and r.json()["schedule_enabled"] is True
    assert client.put("/api/v1/admin/laws/refresh-settings/law", json={"every_days": 0}).status_code == 422


def test_sales_and_auditors_do_not_see_the_law_queue(client, db, lit, reg):
    for who in ("sales", "aud"):
        login_as(client, db, lit[who])
        assert client.get("/api/v1/reg/changes?kind=law").status_code == 403
