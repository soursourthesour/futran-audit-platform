"""R7 incident register with regulator deadline timers (spec §27.3) and its link to the history log (§27.2)."""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.core import clock
from app.notifications.models import Notification
from app.register.models import HistoryEntry, RegisterSystemLaw
from app.tracing.models import Incident, IncidentDeadline
from tests.tracing.conftest import activate, in_scope, incident_lead, law


@pytest.fixture
def now():
    clock.set_now(datetime(2028, 3, 1, 12, 0))
    yield clock.utcnow()
    clock.set_now(None)


def _incident(client, sid, **kw):
    body = {"description": "Screener ranked candidates with career gaps lower", "found_at": "2028-03-01T09:30", "severity": "high", "serious_kind": "none"} | kw
    r = client.post(f"/api/v1/register/{sid}/tracing/incidents", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _codes(inc):
    return sorted(d["rule_code"] for d in inc["deadlines"] if d["status"] == "open")


def test_locked_system_takes_no_incidents(client, db, trc):
    trc.as_(trc.caico)
    page = client.get(f"/api/v1/register/{trc.screening.id}/tracing").json()
    assert page["state"] == "locked" and page["recommended"] is True and page["incidents"] == [] and page["traces"] == []
    r = client.post(f"/api/v1/register/{trc.screening.id}/tracing/incidents", json={"description": "x", "found_at": "2026-10-01T09:00", "severity": "low"})
    assert r.status_code == 409 and "Unlock" in r.json()["detail"]


def test_serious_incident_in_eu_scope_gets_provider_and_authority_deadlines(client, db, trc, now):
    in_scope(db, trc.org, "eu")
    incident_lead(db, trc.org, trc.dpo)
    activate(client, trc, [trc.screening])
    trc.as_(trc.hr_lead)
    inc = _incident(client, trc.screening.id, serious_kind="health", people_affected=23, cause="Gap penalty", owner_id=trc.hr_lead.id)
    assert inc["code"] == "INC-001" and inc["reportable"] is True and inc["status"] == "open"
    assert _codes(inc) == ["eu_art26_provider", "eu_art73_15d"]
    msa = next(d for d in inc["deadlines"] if d["rule_code"] == "eu_art73_15d")
    assert msa["due_at"] == "2028-03-16T09:30:00" and msa["binding"] is True and msa["statutory"] is True
    assert msa["citation"] == "EU AI Act Art. 73(2), with Art. 26(5)" and "15 days" in msa["quote"] and msa["source_url"].startswith("https://")
    assert inc["deadline_at"] == "2028-03-02T09:30:00"  # the earliest open one: tell the provider
    # the history log gets the incident, linked both ways
    he = db.get(HistoryEntry, inc["history_entry_id"])
    assert he.type == "incident" and he.severity == "high" and he.details["people_affected"] == 23 and he.details["reportable"] is True
    assert he.details["law"] == "EU AI Act" and he.details["deadline"] == "2028-03-02"
    # the AI Incident Response Lead, the CAICO and the owner are told at once, by email too
    told = {n.user_id for n in db.scalars(select(Notification).where(Notification.kind == "incident_deadline"))}
    assert told == {trc.dpo.id, trc.caico.id, trc.hr_lead.id}
    assert db.scalar(select(AuditLog).where(AuditLog.action == "incident.created")) is not None


def test_law_linked_to_the_system_also_counts(client, db, trc, now):
    eu = law(db, "EU", "2024/1689")
    db.add(RegisterSystemLaw(organization_id=trc.org.id, register_system_id=trc.screening.id, regulation_id=eu.id))
    db.commit()
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    inc = _incident(client, trc.screening.id, serious_kind="death")
    assert _codes(inc) == ["eu_art26_provider", "eu_art73_10d"]
    page = client.get(f"/api/v1/register/{trc.screening.id}/tracing").json()
    assert page["law_families"] == ["eu_ai_act"]


def test_no_law_in_scope_means_no_regulator_deadlines(client, db, trc, now):
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    inc = _incident(client, trc.screening.id, serious_kind="death", cyber_incident=True, risk_to_rights=True)
    assert inc["deadlines"] == [] and inc["reportable"] is False


def test_cert_in_six_hours_where_indian_law_applies(client, db, trc, now):
    in_scope(db, trc.org, "dpdp")
    activate(client, trc, [trc.agent])
    trc.as_(trc.caico)
    inc = _incident(client, trc.agent.id, cyber_incident=True, found_at="2028-03-01T08:00")
    assert _codes(inc) == ["certin_6h"] and inc["deadlines"][0]["due_at"] == "2028-03-01T14:00:00"


def test_colorado_cure_period_from_an_ag_notice(client, db, trc, now):
    in_scope(db, trc.org, "co")
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    inc = _incident(client, trc.screening.id)
    assert inc["deadlines"] == []
    r = client.patch(f"/api/v1/register/{trc.screening.id}/tracing/incidents/{inc['id']}", json={"ag_notice_received_on": "2028-02-20"})
    assert r.status_code == 200, r.text
    assert _codes(r.json()) == ["co_ag_cure_60d"] and r.json()["deadlines"][0]["due_at"] == "2028-04-20T23:59:00"


def test_reclassifying_moves_the_deadlines(client, db, trc, now):
    in_scope(db, trc.org, "eu")
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    inc = _incident(client, trc.screening.id, serious_kind="health")
    r = client.patch(f"/api/v1/register/{trc.screening.id}/tracing/incidents/{inc['id']}", json={"serious_kind": "death", "found_at": "2028-03-01T06:00"})
    got = r.json()
    assert _codes(got) == ["eu_art26_provider", "eu_art73_10d"]
    withdrawn = [d for d in got["deadlines"] if d["status"] == "withdrawn"]
    assert [d["rule_code"] for d in withdrawn] == ["eu_art73_15d"]
    assert next(d for d in got["deadlines"] if d["rule_code"] == "eu_art73_10d")["due_at"] == "2028-03-11T06:00:00"
    assert next(d for d in got["deadlines"] if d["rule_code"] == "eu_art26_provider")["due_at"] == "2028-03-02T06:00:00"
    # back to not serious: the open deadlines are withdrawn, none deleted
    got = client.patch(f"/api/v1/register/{trc.screening.id}/tracing/incidents/{inc['id']}", json={"serious_kind": "none"}).json()
    assert _codes(got) == [] and db.scalar(select(IncidentDeadline).where(IncidentDeadline.rule_code == "eu_art73_15d")) is not None


def test_recording_notices_and_closing(client, db, trc, now):
    in_scope(db, trc.org, "eu")
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    inc = _incident(client, trc.screening.id, serious_kind="health", containment="Feature switched off")
    base = f"/api/v1/register/{trc.screening.id}/tracing"
    dl = {d["rule_code"]: d for d in inc["deadlines"]}
    # closing waits until every binding notice is recorded or marked not applicable
    r = client.post(f"{base}/incidents/{inc['id']}/close", json={"closed_on": "2028-03-01"})
    assert r.status_code == 409 and "notice" in r.json()["detail"]
    r = client.post(f"{base}/deadlines/{dl['eu_art26_provider']['id']}", json={"action": "done", "done_at": "2028-03-01T11:00", "reference": "Vendor ticket 4411"})
    assert r.status_code == 200, r.text
    assert r.json()["provider_notified_at"] == "2028-03-01T11:00:00"
    assert client.post(f"{base}/deadlines/{dl['eu_art73_15d']['id']}", json={"action": "not_applicable"}).status_code == 422
    r = client.post(f"{base}/deadlines/{dl['eu_art73_15d']['id']}", json={"action": "not_applicable", "reason": "Not a high-risk system under Annex III."})
    assert r.status_code == 200 and r.json()["reported_at"] is None
    r = client.post(f"{base}/incidents/{inc['id']}/close", json={"closed_on": "2028-03-01", "fix": "Vendor removed the gap penalty."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed" and r.json()["closed_on"] == "2028-03-01"
    he = db.get(HistoryEntry, inc["history_entry_id"])
    assert he.details["closed_on"] == "2028-03-01" and he.details["fix"] == "Vendor removed the gap penalty." and he.details["provider_told"] is True


def test_report_done_counts_as_reported(client, db, trc, now):
    in_scope(db, trc.org, "eu")
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    inc = _incident(client, trc.screening.id, serious_kind="critical_infrastructure")
    msa = next(d for d in inc["deadlines"] if d["rule_code"] == "eu_art73_2d")
    got = client.post(f"/api/v1/register/{trc.screening.id}/tracing/deadlines/{msa['id']}", json={"action": "done", "done_at": "2028-03-01T11:00", "reference": "MSA-2028-17"}).json()
    assert got["reported_at"] == "2028-03-01T11:00:00"
    got = client.post(f"/api/v1/register/{trc.screening.id}/tracing/deadlines/{msa['id']}", json={"action": "reopen"}).json()
    assert got["reported_at"] is None


def test_link_an_existing_history_entry(client, db, trc, now):
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    e = client.post(f"/api/v1/register/{trc.screening.id}/history", json={"type": "incident", "occurred_on": "2028-02-10", "summary": "Complaint from an applicant", "severity": "medium"}).json()
    other = client.post(f"/api/v1/register/{trc.screening.id}/history", json={"type": "approval", "occurred_on": "2028-02-11", "summary": "Approved", "details": {"approver": "HR"}}).json()
    r = client.post(f"/api/v1/register/{trc.screening.id}/tracing/incidents", json={"description": "Complaint from an applicant", "found_at": "2028-02-10T10:00", "severity": "medium", "history_entry_id": other["id"]})
    assert r.status_code == 422
    inc = _incident(client, trc.screening.id, history_entry_id=e["id"], found_at="2028-02-10T10:00")
    assert inc["history_entry_id"] == e["id"]
    assert db.scalar(select(HistoryEntry).where(HistoryEntry.type == "incident").where(HistoryEntry.register_system_id == trc.screening.id)).id == e["id"]
    # an entry is linked to one incident only
    r = client.post(f"/api/v1/register/{trc.screening.id}/tracing/incidents", json={"description": "Again", "found_at": "2028-02-10T10:00", "severity": "medium", "history_entry_id": e["id"]})
    assert r.status_code == 422


def test_validation(client, db, trc, now):
    activate(client, trc, [trc.screening])
    trc.as_(trc.caico)
    r = client.post(f"/api/v1/register/{trc.screening.id}/tracing/incidents", json={"description": " ", "found_at": "2028-04-01T09:00", "severity": "dire", "serious_kind": "bad", "people_affected": -1})
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} == {"description", "found_at", "severity", "serious_kind", "people_affected"}


def test_department_scope_and_the_incident_lead(client, db, trc, now):
    activate(client, trc, [trc.screening, trc.agent])
    trc.as_(trc.hr_lead)
    _incident(client, trc.screening.id)
    assert client.get(f"/api/v1/register/{trc.agent.id}/tracing").status_code == 404
    trc.as_(trc.contrib)
    assert client.get(f"/api/v1/register/{trc.screening.id}/tracing").status_code in (403, 404)
    # a contributor named AI Incident Response Lead works on incidents for every system
    incident_lead(db, trc.org, trc.contrib)
    trc.as_(trc.contrib)
    page = client.get(f"/api/v1/register/{trc.agent.id}/tracing").json()
    assert page["can_manage_incidents"] is True and page["can_record_traces"] is False
    _incident(client, trc.agent.id)
    trc.as_(trc.admin)  # the Client Admin buys the add-on but does not run it
    assert client.get(f"/api/v1/register/{trc.screening.id}/tracing").status_code == 403
    trc.as_(trc.chief)
    assert client.get(f"/api/v1/register/{trc.screening.id}/tracing").status_code == 404


def test_kpis_and_bulk_owner(client, db, trc, now):
    in_scope(db, trc.org, "dpdp")
    activate(client, trc, [trc.agent])
    trc.as_(trc.caico)
    a = _incident(client, trc.agent.id, cyber_incident=True, found_at="2028-03-01T01:00")  # due 07:00, now is 12:00
    b = _incident(client, trc.agent.id, description="Second")
    page = client.get(f"/api/v1/register/{trc.agent.id}/tracing").json()
    assert page["kpis"]["open_incidents"] == 2 and page["kpis"]["deadlines_missed"] == 1
    assert next(i for i in page["incidents"] if i["id"] == a["id"])["deadlines"][0]["overdue"] is True
    r = client.post(f"/api/v1/register/{trc.agent.id}/tracing/incidents/bulk", json={"ids": [a["id"], b["id"]], "owner_id": trc.fin_lead.id})
    assert r.status_code == 200 and r.json()["updated"] == 2
    assert {i.owner_id for i in db.scalars(select(Incident))} == {trc.fin_lead.id}
    r = client.post(f"/api/v1/register/{trc.agent.id}/tracing/incidents/bulk", json={"ids": [a["id"]], "owner_id": trc.chief.id})
    assert r.status_code == 422
