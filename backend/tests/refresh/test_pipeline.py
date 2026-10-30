"""§25.3 M3 pipeline: per-jurisdiction structured calls, schema validation, allowlist, de-duplication, cost cap and log."""
import json

from sqlalchemy import select

from app.refresh.claude import FakeRefreshClient
from app.refresh.models import RefreshProposalMeta, RefreshRun
from app.refresh.pipeline import PROMPT_VERSIONS, SCHEMAS, execute_run, start_run
from app.regmaster.models import ChangeImpact, ProposedChange
from app.staffalerts.models import StaffAlert
from tests.refresh.conftest import change


def _run(db, lit, settings, client, codes=("US-IL",), kind="law", **kw):
    run = start_run(db, kind=kind, actor=lit["chief"], jurisdiction_codes=list(codes), settings=settings, **kw)
    execute_run(db, settings, run, client)
    db.commit()
    return run


def test_a_run_proposes_validated_changes_and_keeps_its_record(db, lit, reg, settings):
    fake = FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}})
    run = _run(db, lit, settings, fake)
    assert run.status == "completed" and run.proposals_created == 1
    assert run.model_id == "fake-claude" and run.prompt_version == PROMPT_VERSIONS["law"]
    assert run.input_tokens == 12000 and run.output_tokens == 1500 and run.searches == 3
    assert round(run.cost_usd, 4) == round(12000 * 3 / 1e6 + 1500 * 15 / 1e6 + 3 * 0.01, 4)
    assert run.responses[0]["jurisdiction"] == "US-IL" and run.responses[0]["accepted"] == 1 and run.responses[0]["reply"]
    pc = db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id))
    assert pc.origin == "claude_refresh" and pc.status == "pending" and pc.confidence == "high"
    assert pc.base_version_id == reg["law"].current_version_id and pc.jurisdiction_id == reg["il"].id
    assert pc.old_value == "2026-01-01"  # read from the record, not taken from Claude
    # the prompt carries the approved records, the allowlist and the prompt version
    call = fake.calls[0]
    assert reg["law"].short_name in call["prompt"] and "ilga.gov" in call["prompt"] and PROMPT_VERSIONS["law"] in call["prompt"]
    assert call["allowed_domains"] == ["dhr.illinois.gov", "ilga.gov"]  # official sources only by default


def test_the_schema_is_structured_output_only():
    s = SCHEMAS["law"]
    item = s["properties"]["changes"]["items"]
    assert s["additionalProperties"] is False and item["additionalProperties"] is False
    assert set(item["required"]) >= {"field_path", "old_value", "new_value", "summary", "source_url", "source_quote", "confidence"}


def test_off_allowlist_source_is_forced_to_low_confidence(db, lit, reg, settings):
    fake = FakeRefreshClient({"US-IL": {"changes": [change(reg["law"], source_url="https://lawfirm.example/alert/il-ai")]}})
    run = _run(db, lit, settings, fake)
    pc = db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id))
    meta = db.get(RefreshProposalMeta, pc.id)
    assert pc.confidence == "low" and meta.off_allowlist and meta.claude_confidence == "high" and meta.needs_second_review


def test_secondary_sources_count_when_the_run_includes_them(db, lit, reg, settings):
    fake = FakeRefreshClient({"US-IL": {"changes": [change(reg["law"], source_url="https://lawfirm.example/alert/il-ai")]}})
    run = _run(db, lit, settings, fake, source_set="with_secondary")
    pc = db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id))
    assert pc.confidence == "high" and "lawfirm.example" in fake.calls[0]["allowed_domains"]


def test_items_without_quote_unknown_field_or_foreign_law_are_skipped(db, lit, reg, settings):
    other = next(r for r in __import__("app.laws.publish", fromlist=["x"]).current_regulations(db) if r.jurisdiction_id != reg["il"].id)
    items = [change(reg["law"], source_quote=""), change(reg["law"], field_path="law.colour"), change(other)]
    run = _run(db, lit, settings, FakeRefreshClient({"US-IL": {"changes": items}}))
    assert run.proposals_created == 0
    text = " ".join(run.warnings)
    assert "no source quote" in text and "does not exist" in text and "not in this jurisdiction" in text


def test_free_text_reply_is_rejected_and_the_run_goes_on(db, lit, reg, settings):
    fake = FakeRefreshClient({"US-IL": "I found that Illinois changed its law.", "US-CA": {"changes": []}})
    run = _run(db, lit, settings, fake, codes=("US-IL", "US-CA"))
    assert run.status == "completed" and len(fake.calls) == 2
    assert any("schema" in w for w in run.warnings)
    assert run.responses[0]["outcome"] == "rejected"


def test_duplicates_across_runs_are_merged(db, lit, reg, settings):
    fake = FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}})
    first = _run(db, lit, settings, fake)
    second = _run(db, lit, settings, fake)
    assert second.proposals_created == 0 and second.proposals_merged == 1
    rows = list(db.scalars(select(ProposedChange)))
    assert len(rows) == 1
    meta = db.get(RefreshProposalMeta, rows[0].id)
    assert meta.seen_count == 2 and meta.run_ids == [first.id, second.id]


def test_rejected_change_is_not_proposed_again(db, lit, reg, settings):
    fake = FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}})
    _run(db, lit, settings, fake)
    db.scalar(select(ProposedChange)).status = "rejected"
    db.commit()
    again = _run(db, lit, settings, fake)
    assert again.proposals_created == 0 and db.query(ProposedChange).count() == 1
    assert any("rejected" in w for w in again.warnings)


def test_cost_cap_stops_the_run(db, lit, reg, settings):
    fake = FakeRefreshClient({})
    run = _run(db, lit, settings, fake, codes=("US-IL", "US-CA", "US-NY"), cost_cap_usd=0.05)
    assert len(fake.calls) == 1 and run.status == "capped"
    assert any("cost cap" in w.lower() for w in run.warnings)


def test_impact_is_computed_and_the_chief_auditor_is_alerted(db, lit, reg, settings):
    run = _run(db, lit, settings, FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}}))
    pc = db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id))
    impacts = list(db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == pc.id)))
    assert [i.organization_id for i in impacts] == [lit["abc"].id]
    alerts = list(db.scalars(select(StaffAlert).where(StaffAlert.refresh_run_id == run.id, StaffAlert.is_copy.is_(False))))
    assert {a.user_id for a in alerts} == {lit["chief"].id, lit["chief2"].id}
    assert alerts[0].summary["clients_affected"] == 1


def test_new_law_needs_a_second_reviewer(db, lit, reg, settings):
    new = change(reg["law"], change_type="new_law", regulation_id=None, field_path="new_law", old_value=None,
                 new_value=json.dumps({"jurisdiction_code": "US-IL", "short_name": "HB 0000 AI Notice Act", "type": "statute"}),
                 summary="New Illinois AI notice law.")
    run = _run(db, lit, settings, FakeRefreshClient({"US-IL": {"changes": [new]}}))
    pc = db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id))
    assert pc.change_type == "new_law" and pc.new_value["short_name"] == "HB 0000 AI Notice Act"
    assert db.get(RefreshProposalMeta, pc.id).needs_second_review


def test_client_geographies_scope_uses_where_clients_operate(db, lit, reg, settings):
    from app.regmaster.models import ClientGeography

    db.add(ClientGeography(organization_id=lit["abc"].id, jurisdiction_id=reg["il"].id, basis="office"))
    db.commit()
    run = start_run(db, kind="law", actor=lit["chief"], scope_mode="client_geographies", settings=settings)
    assert run.jurisdiction_ids == [reg["il"].id]


def test_a_failure_is_recorded_not_half_applied(db, lit, reg, settings):
    class Boom(FakeRefreshClient):
        def propose(self, **kw):
            raise RuntimeError("network down")

    run = _run(db, lit, settings, Boom())
    assert run.status == "failed" and "network down" in run.error
    assert db.query(ProposedChange).count() == 0
