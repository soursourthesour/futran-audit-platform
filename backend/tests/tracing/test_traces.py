"""R7 action trace: manual entry, CSV and JSON import, the GuardRail feed (an adapter with an in-process fake) and export."""
import json
from datetime import datetime

import pytest
from sqlalchemy import select

from app.core import clock
from app.tracing.models import ActionTrace, TraceImport
from tests.tracing.conftest import activate

CSV = """time,session,action,tool,data touched,decision,policy,approver or note,agent,event id
2028-03-01T10:02:11,S-88213,Search product knowledge base,kb.search,Public product docs,allowed,Invoices-v1,,invoice-agent@abc,ev-1
2028-03-01T10:05:02,S-88215,Approve payment of 7200 USD,erp.approve,Invoice 5531,blocked,Invoices-v1,GuardRail: over the 5000 USD limit,invoice-agent@abc,ev-2
2028-03-01T10:06:19,S-88216,Pay a new supplier,erp.pay,Supplier bank details,escalated,Invoices-v1,Grace Liu,invoice-agent@abc,ev-3
"""


@pytest.fixture
def now():
    clock.set_now(datetime(2028, 3, 1, 12, 0))
    yield clock.utcnow()
    clock.set_now(None)


@pytest.fixture
def agent(client, db, trc, now):
    activate(client, trc, [trc.agent])
    trc.as_(trc.fin_lead)
    return f"/api/v1/register/{trc.agent.id}/tracing"


def _upload(client, base, name, data: bytes):
    return client.post(f"{base}/traces/import", files={"file": (name, data, "text/csv" if name.endswith(".csv") else "application/json")})


def test_manual_entry_and_validation(client, db, trc, agent):
    r = client.post(f"{agent}/traces", json={"at": "2028-03-01T11:00", "session_id": "S-1", "action": "Approve invoice 5530", "tool": "erp.approve", "decision": "allowed", "agent_identity": "invoice-agent@abc"})
    assert r.status_code == 200, r.text
    t = db.scalar(select(ActionTrace))
    assert t.source == "manual" and t.recorded_by == trc.fin_lead.id and t.organization_id == trc.org.id
    r = client.post(f"{agent}/traces", json={"at": "2028-03-02T11:00", "action": "", "decision": "maybe"})
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} == {"at", "action", "decision"}


def test_csv_import_skips_events_already_held(client, db, trc, agent):
    r = _upload(client, agent, "trace.csv", CSV.encode())
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 3, "skipped": 0}
    rows = {t.external_id: t for t in db.scalars(select(ActionTrace))}
    assert rows["ev-2"].decision == "blocked" and rows["ev-2"].approver == "GuardRail: over the 5000 USD limit" and rows["ev-2"].source == "csv"
    assert rows["ev-3"].at == datetime(2028, 3, 1, 10, 6, 19) and rows["ev-3"].data_touched == "Supplier bank details"
    assert _upload(client, agent, "trace.csv", CSV.encode()).json() == {"added": 0, "skipped": 3}
    imp = db.scalars(select(TraceImport).order_by(TraceImport.at)).all()
    assert [(i.source, i.added, i.skipped, i.filename) for i in imp] == [("csv", 3, 0, "trace.csv"), ("csv", 0, 3, "trace.csv")]


def test_import_is_all_or_nothing(client, db, trc, agent):
    bad = CSV + "not a time,S-9,,x,,perhaps,,,,ev-9\n"
    r = _upload(client, agent, "trace.csv", bad.encode())
    assert r.status_code == 422
    msgs = {e["field"] for e in r.json()["errors"]}
    assert {"row 5: time", "row 5: action", "row 5: decision"} <= msgs
    assert db.scalar(select(ActionTrace)) is None
    assert _upload(client, agent, "trace.txt", b"x").status_code == 422


def test_json_import(client, db, trc, agent):
    events = {"events": [{"time": "2028-03-01T09:00:00Z", "session": "S-7", "action": "Read invoice", "tool": "erp.read", "decision": "allowed", "event_id": "j-1"},
                         {"at": "2028-03-01T09:01:00", "session_id": "S-7", "action": "Approve invoice", "decision": "escalated", "approver": "Grace Liu"}]}
    r = _upload(client, agent, "trace.json", json.dumps(events).encode())
    assert r.status_code == 200 and r.json()["added"] == 2
    assert {t.source for t in db.scalars(select(ActionTrace))} == {"json"}
    r = _upload(client, agent, "trace.json", b"{not json")
    assert r.status_code == 422


def test_guardrail_feed_through_the_fake_adapter(client, db, trc, agent):
    r = client.post(f"{agent}/guardrail-sync")
    assert r.status_code == 200, r.text
    first = r.json()["added"]
    assert first > 0 and r.json()["skipped"] == 0
    assert {t.policy_ref for t in db.scalars(select(ActionTrace))} == {"Invoices-v1"} and {t.source for t in db.scalars(select(ActionTrace))} == {"guardrail"}
    assert client.post(f"{agent}/guardrail-sync").json() == {"added": 0, "skipped": first}
    # a system without a GuardRail policy has nothing to sync
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    r = client.post(f"/api/v1/register/{trc.screening.id}/tracing/guardrail-sync")
    assert r.status_code == 422 and "GuardRail policy" in r.json()["detail"]


def test_guardrail_adapter_off_explains(client, db, trc, agent, app):
    app.state.settings = app.state.settings.model_copy(update={"guardrail_mode": "off"})
    r = client.post(f"{agent}/guardrail-sync")
    assert r.status_code == 409 and "not connected" in r.json()["detail"]


def test_list_filters_and_kpis(client, db, trc, agent):
    _upload(client, agent, "trace.csv", CSV.encode())
    client.post(f"{agent}/traces", json={"at": "2028-02-01T11:00", "action": "Old action", "decision": "allowed"})
    page = client.get(agent).json()
    assert page["kpis"]["actions_24h"] == 3 and page["kpis"]["blocked_24h"] == 1 and page["kpis"]["escalated_24h"] == 1
    assert [t["action"] for t in client.get(f"{agent}/traces", params={"decision": "blocked"}).json()["rows"]] == ["Approve payment of 7200 USD"]
    assert len(client.get(f"{agent}/traces", params={"period": "24h"}).json()["rows"]) == 3
    assert len(client.get(f"{agent}/traces", params={"period": "all"}).json()["rows"]) == 4
    assert client.get(f"{agent}/traces", params={"period": "year"}).status_code == 422


def test_traces_are_append_only(client, db, trc, agent):
    client.post(f"{agent}/traces", json={"at": "2028-03-01T11:00", "action": "x", "decision": "allowed"})
    tid = db.scalar(select(ActionTrace)).id
    assert client.patch(f"{agent}/traces/{tid}", json={"action": "y"}).status_code in (404, 405)  # no such endpoint
    assert client.delete(f"{agent}/traces/{tid}").status_code in (404, 405)
    assert db.get(ActionTrace, tid).action == "x"


def test_raise_incident_from_traces(client, db, trc, agent):
    _upload(client, agent, "trace.csv", CSV.encode())
    blocked = db.scalar(select(ActionTrace).where(ActionTrace.external_id == "ev-2"))
    r = client.post(f"{agent}/incidents", json={"description": "Agent tried to pay over its limit", "found_at": "2028-03-01T10:05", "severity": "medium", "trace_ids": [blocked.id]})
    assert r.status_code == 200 and r.json()["trace_ids"] == [blocked.id]
    r = client.post(f"{agent}/incidents", json={"description": "x", "found_at": "2028-03-01T10:05", "severity": "low", "trace_ids": ["nope"]})
    assert r.status_code == 422


def test_export_csv(client, db, trc, agent):
    _upload(client, agent, "trace.csv", CSV.encode())
    client.post(f"{agent}/incidents", json={"description": "Agent tried to pay over its limit", "found_at": "2028-03-01T10:05", "severity": "medium"})
    r = client.get(f"{agent}/export", params={"what": "traces"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("Time,Session,Action") and len(lines) == 4
    r = client.get(f"{agent}/export", params={"what": "incidents"})
    assert "INC-001" in r.text and "Agent tried to pay over its limit" in r.text


def test_locked_system_takes_no_traces(client, db, trc, now):
    trc.as_(trc.caico)
    base = f"/api/v1/register/{trc.notes.id}/tracing"
    assert client.post(f"{base}/traces", json={"at": "2028-03-01T11:00", "action": "x", "decision": "allowed"}).status_code == 409
    assert _upload(client, base, "t.csv", CSV.encode()).status_code == 409
