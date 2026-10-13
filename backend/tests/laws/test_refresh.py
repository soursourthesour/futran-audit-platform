import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.laws.importer import parse_workbook
from app.laws.models import LawRefreshRun, MatrixVersion, Regulation, RegulationProposal
from app.laws.publish import current_regulations, publish
from app.laws.refresh import accept_proposals, run_refresh
from app.reference.jurisdictions import seed_iso
from app.reference.models import Jurisdiction
from tests.factories import login_as, make_org, make_user

WORKBOOK = Path(__file__).resolve().parents[2] / "seeds" / "law_matrix.xlsx"


class StubClaude:
    def __init__(self, reply_for):
        self.reply_for = reply_for
        self.prompts = []

    def research(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply_for(prompt)


@pytest.fixture
def world(db):
    seed_iso(db)
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")
    publish(db, parse_workbook(WORKBOOK), admin, {})
    db.commit()
    il = db.scalar(select(Jurisdiction).where(Jurisdiction.code == "US-IL"))
    il_laws = [r for r in current_regulations(db) if r.jurisdiction_id == il.id]
    return admin, il, il_laws


def _reply(il_laws):
    target = il_laws[0]
    return "Here are the changes.\n```json\n" + json.dumps([
        {"change_type": "update", "regulation_id": target.id, "fields": {"developments_text": "Amended in 2026 (hypothetical)."}, "rationale": "Amendment signed.", "sources": [{"title": "Illinois General Assembly", "url": "https://www.ilga.gov/"}]},
        {"change_type": "add", "fields": {"short_name": "HB 9999 AI Notice Act", "feature": "employment_hiring", "type": "statute", "obligations_text": "Notice before AI use."}, "rationale": "New law.", "sources": [{"title": "ILGA", "url": "https://www.ilga.gov/hb9999"}]},
        {"change_type": "add", "fields": {"short_name": "No sources law", "feature": "employment_hiring"}, "rationale": "x", "sources": []},
    ]) + "\n```"


def test_refresh_creates_proposals_from_stub(db, world):
    admin, il, il_laws = world
    stub = StubClaude(lambda p: _reply(il_laws))
    run = run_refresh(db, admin, [il.id], stub)
    assert run.status == "completed"
    props = db.scalars(select(RegulationProposal).where(RegulationProposal.run_id == run.id)).all()
    assert {p.change_type for p in props} == {"update", "add"}
    assert all(p.status == "pending" and p.sources for p in props)
    assert "Illinois" in stub.prompts[0] and il_laws[0].short_name in stub.prompts[0]


def test_proposal_sources_required(db, world):
    admin, il, il_laws = world
    run = run_refresh(db, admin, [il.id], StubClaude(lambda p: _reply(il_laws)))
    assert db.query(RegulationProposal).filter_by(run_id=run.id).count() == 2
    assert any("source" in w.lower() for w in run.warnings)


def test_invalid_json_marks_run_failed(db, world):
    admin, il, _ = world
    run = run_refresh(db, admin, [il.id], StubClaude(lambda p: "I could not find anything useful."))
    assert run.status == "failed"
    assert "JSON" in run.error


def test_update_for_unknown_regulation_rejected(db, world):
    admin, il, _ = world
    bad = '```json\n[{"change_type": "update", "regulation_id": "not-a-real-id", "fields": {"obligations_text": "x"}, "rationale": "r", "sources": [{"title": "t", "url": "https://x.test"}]}]\n```'
    run = run_refresh(db, admin, [il.id], StubClaude(lambda p: bad))
    assert db.query(RegulationProposal).filter_by(run_id=run.id).count() == 0
    assert run.warnings


def test_accept_creates_new_version_with_claude_origin(db, world):
    admin, il, il_laws = world
    run = run_refresh(db, admin, [il.id], StubClaude(lambda p: _reply(il_laws)))
    props = db.scalars(select(RegulationProposal).where(RegulationProposal.run_id == run.id)).all()
    upd = next(p for p in props if p.change_type == "update")
    add = next(p for p in props if p.change_type == "add")
    v = accept_proposals(db, admin, accept=[upd.id], reject=[add.id])
    assert v.origin == "claude" and v.status == "published"
    old = db.get(Regulation, upd.regulation_id)
    assert old.superseded_by_id
    assert db.get(Regulation, old.superseded_by_id).developments_text == "Amended in 2026 (hypothetical)."
    assert db.get(Regulation, old.superseded_by_id).origin == "claude"
    assert upd.status == "accepted" and add.status == "rejected"
    assert db.query(Regulation).filter_by(short_name="HB 9999 AI Notice Act").count() == 0


def test_refresh_without_key_409(client, db, world):
    admin, il, _ = world
    login_as(client, db, admin)
    r = client.post("/api/v1/admin/laws/refresh", json={"jurisdiction_codes": ["US-IL"]})
    assert r.status_code == 409
    assert r.json()["detail"] == "Add an Anthropic API key in settings to use law updates."


def test_refresh_api_flow_with_stub(client, db, world):
    admin, il, il_laws = world
    client.app.state.settings = client.app.state.settings.model_copy(update={"anthropic_api_key": "test-key"})
    client.app.state.claude_factory = lambda s: StubClaude(lambda p: _reply(il_laws))
    login_as(client, db, admin)
    r = client.post("/api/v1/admin/laws/refresh", json={"jurisdiction_codes": ["US-IL"]})
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    detail = client.get(f"/api/v1/admin/laws/refresh/{run_id}").json()
    assert detail["status"] == "completed"
    upd = next(p for p in detail["proposals"] if p["change_type"] == "update")
    assert upd["current"]["short_name"] == il_laws[0].short_name
    out = client.post("/api/v1/admin/laws/proposals/decide", json={"accept": [upd["id"]], "reject": []})
    assert out.status_code == 200 and out.json()["version_id"]
    db.expire_all()
    assert db.query(MatrixVersion).filter_by(origin="claude").count() == 1
    assert db.query(LawRefreshRun).count() == 1
