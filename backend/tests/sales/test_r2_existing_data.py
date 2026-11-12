"""Release 2 R2: opportunities saved before the sales desk (no name, source, BANT, flag or last activity; v0.6 stages)
keep working: the list, record, export, Chief Auditor approval, the automatic triggers and the opportunity scan."""
from datetime import datetime

from sqlalchemy import select, text

from app.engagements.models import Engagement
from app.sales.models import Opportunity
from app.sales.service import open_from_trigger, open_recommended_addon_opportunities
from tests.factories import login_as
from tests.wsd_world import lit  # noqa: F401

API = "/api/v1"


def _legacy(db, org_id: str, stage: str, ref: str) -> str:
    """A row as v0.6 wrote it: only the v0.6 columns, the Release 2 columns left NULL."""
    oid = f"legacy-{ref}"
    db.execute(text("INSERT INTO opportunities (id, organization_id, trigger, trigger_ref, service, service_kind, why_now, value, stage, system_ids, system_types, "
                    "needs_ca_approval, created_at, updated_at) VALUES (:id, :org, 'case', :ref, 'Bias audit', 'bias_audit', 'Mobley v. Workday', 18000, :stage, '[]', '[]', "
                    ":needs, :at, :at)"), {"id": oid, "org": org_id, "ref": ref, "stage": stage, "needs": stage == "proposal", "at": datetime(2026, 9, 1)})
    db.commit()
    return oid


def test_legacy_rows_list_open_export_and_move_on(client, db, lit):
    a = _legacy(db, lit["nw"].id, "contacted", "a")
    b = _legacy(db, lit["nw"].id, "won", "b")
    login_as(client, db, lit["sales"])
    items = {i["id"]: i for i in client.get(f"{API}/opportunities").json()["items"]}
    assert items[a]["stage_label"] == "Contacted" and items[a]["name"] == "Bias audit" and items[a]["bant"] == {} and items[a]["independence_flag"] is False
    assert items[a]["stale"] is True and items[b]["stale"] is False  # won is never stale
    assert client.get(f"{API}/opportunities/{a}").status_code == 200
    assert "Bias audit" in client.get(f"{API}/opportunities/export.csv").text
    assert client.patch(f"{API}/opportunities/{a}", json={"stage": "proposal"}).json()["stage"] == "proposal"
    assert client.get(f"{API}/sales/home").status_code == 200


def test_chief_auditor_approval_still_gates_offers_on_legacy_rows(client, db, lit):
    db.add(Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC audit", status="in_progress", stage=5))
    db.commit()
    oid = _legacy(db, lit["abc"].id, "proposal", "c")
    login_as(client, db, lit["sales"])
    assert client.post(f"{API}/opportunities/{oid}/send-proposal", json={"summary": "x"}).status_code == 409
    assert client.post(f"{API}/opportunities/{oid}/request-approval", json={"note": "Quote asked"}).status_code == 200
    login_as(client, db, lit["chief"])
    assert client.post(f"{API}/opportunities/{oid}/approve", json={"decision": "approve", "note": "ok"}).status_code == 200
    login_as(client, db, lit["sales"])
    assert client.post(f"{API}/opportunities/{oid}/send-proposal", json={"summary": "Proposal"}).status_code == 200


def test_automatic_triggers_dedupe_against_legacy_rows_and_record_the_flag(db, lit):
    _legacy(db, lit["abc"].id, "new", "case-1")
    again = open_from_trigger(db, lit["abc"].id, "case", "case-1", service="Bias audit", why_now="x")
    assert again.id == "legacy-case-1"  # once per client, trigger and reference, as before
    db.add(Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC audit", status="in_progress", stage=5))
    db.flush()
    o = open_from_trigger(db, lit["abc"].id, "case", "case-2", service="Readiness", why_now="x")
    assert o.needs_ca_approval is True and o.independence_flag is True and o.source == "auto_trigger"
    made = open_recommended_addon_opportunities(db)  # the daily tracing trigger still runs
    assert all(m.trigger == "recommended_addon" for m in made)


def test_the_opportunity_scan_runs_with_legacy_rows_present(db, lit):
    from app.sales import scan

    _legacy(db, lit["nw"].id, "contacted", "d")
    scan.run_now(db, lit["admin"])
    db.commit()
    assert scan.last_run(db).status == "completed"
    assert db.scalar(select(Opportunity).where(Opportunity.id == "legacy-d")).stage == "contacted"
