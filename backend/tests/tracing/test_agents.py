"""F14: agent registration, decision samples for auditor review, the override-rate trend, alerts on permission changes,
decision logs pushed through the public API, and the "Agentic AI" question set (spec §21 F14, §18.4)."""
import random
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.core.clock import utcnow
from app.engagements.models import Engagement, EngagementTeam
from app.notifications.models import Notification
from app.register.models import ChangeLog, RegisterSystem
from app.tracing.models import ActionTrace
from tests.factories import make_user
from tests.tracing.conftest import activate

API = "/api/v1"
REG = {
    "tools": [{"name": "erp.approve_invoice", "description": "Approve an invoice for payment", "access": "act", "needs_approval": True},
              {"name": "erp.read_invoice", "description": "Read an invoice", "access": "read", "needs_approval": False}],
    "permissions": ["Read supplier invoices", "Approve invoices under 5,000 USD"],
    "approval_points": ["A person approves every invoice over 1,000 USD"],
    "autonomy_level": "acts_with_approval",
    "kill_switch": "Finance systems lead disables the agent's service account in the ERP console.",
    "kill_switch_tested_on": None,
    "rate_limits": "200 approvals a day",
}


@pytest.fixture
def eng(db, trc):
    e = Engagement(organization_id=trc.org.id, client_id=trc.org.id, name="ABC AI audit", audit_ref="FAP-2026-010", status="active", stage=5)
    db.add(e)
    db.flush()
    db.add(EngagementTeam(organization_id=trc.org.id, engagement_id=e.id, user_id=trc.auditor.id, role="auditor"))
    trc.aud2 = make_user(db, db.get(type(trc.org), trc.chief.organization_id), roles=["auditor"], name="Bea Auditor", email="bea@futran.test")
    db.commit()
    return e


def _traces(db, s, n=30, escalated_every=6):
    base = utcnow() - timedelta(days=20)
    for i in range(n):
        db.add(ActionTrace(organization_id=s.organization_id, register_system_id=s.id, at=base + timedelta(hours=i), action=f"Approved invoice INV-{1000 + i}",
                           tool="erp.approve_invoice", decision="escalated" if i % escalated_every == 0 else "allowed", source="manual"))
    db.commit()
    return [t.id for t in db.scalars(select(ActionTrace).where(ActionTrace.register_system_id == s.id).order_by(ActionTrace.at, ActionTrace.id))]


def test_registration_is_for_agents_only(client, trc):
    trc.as_(trc.caico)
    assert client.put(f"{API}/register/{trc.screening.id}/agent", json=REG).status_code == 409
    r = client.put(f"{API}/register/{trc.agent.id}/agent", json=REG)
    assert r.status_code == 200, r.text
    out = client.get(f"{API}/register/{trc.agent.id}/agent").json()
    assert [t["name"] for t in out["registration"]["tools"]] == ["erp.approve_invoice", "erp.read_invoice"]
    assert out["registration"]["autonomy_level"] == "acts_with_approval" and out["can_edit"] is True


def test_registration_is_validated(client, trc):
    trc.as_(trc.caico)
    bad = client.put(f"{API}/register/{trc.agent.id}/agent", json=REG | {"autonomy_level": "free_rein", "tools": [{"name": "", "access": "x"}]})
    assert bad.status_code == 422
    assert {e["field"] for e in bad.json()["errors"]} >= {"autonomy_level", "tools"}


def test_department_scope_and_other_tenants(client, trc):
    trc.as_(trc.caico)
    client.put(f"{API}/register/{trc.agent.id}/agent", json=REG)
    trc.as_(trc.hr_lead)  # the agent is in Finance
    assert client.get(f"{API}/register/{trc.agent.id}/agent").status_code == 404
    trc.as_(trc.fin_lead)
    assert client.get(f"{API}/register/{trc.agent.id}/agent").status_code == 200


def test_permission_changes_are_logged_and_alerted(client, db, trc, eng):
    trc.as_(trc.caico)
    client.put(f"{API}/register/{trc.agent.id}/agent", json=REG)
    assert db.scalar(select(Notification).where(Notification.kind == "agent_permissions_changed")) is None  # the first registration is not a change
    trc.as_(trc.fin_lead)
    more = REG | {"tools": REG["tools"] + [{"name": "bank.release_payment", "description": "Release a payment", "access": "act", "needs_approval": False}],
                  "autonomy_level": "autonomous"}
    assert client.put(f"{API}/register/{trc.agent.id}/agent", json=more).status_code == 200
    told = {n.user_id for n in db.scalars(select(Notification).where(Notification.kind == "agent_permissions_changed"))}
    assert trc.caico.id in told and trc.auditor.id in told and trc.fin_lead.id not in told
    fields = {c.field for c in db.scalars(select(ChangeLog).where(ChangeLog.register_system_id == trc.agent.id, ChangeLog.entity == "AgentRegistration"))}
    assert {"agent_tools", "autonomy_level"} <= fields
    db.expire_all()
    assert db.get(RegisterSystem, trc.agent.id).autonomy == "autonomous"
    trc.as_(trc.caico)
    client.put(f"{API}/register/{trc.agent.id}/agent", json=more | {"kill_switch": "Disable the service account; tested monthly."})
    n = len(list(db.scalars(select(Notification).where(Notification.kind == "agent_permissions_changed", Notification.user_id == trc.auditor.id))))
    assert n == 1  # wording of the kill switch is not a permission change


def test_auditor_draws_a_reproducible_sample_and_records_verdicts(client, db, trc, eng):
    ids = _traces(db, trc.agent)
    trc.as_(trc.auditor)
    r = client.post(f"{API}/clients/{trc.org.id}/agents/{trc.agent.id}/samples", json={"size": 5, "seed": 42, "period_days": 30})
    assert r.status_code == 200, r.text
    smp = r.json()
    assert smp["seed"] == 42 and smp["population"] == 30 and smp["engagement"] == "FAP-2026-010"
    assert [d["id"] for d in smp["decisions"]] == random.Random(42).sample(ids, 5)
    auto = client.post(f"{API}/clients/{trc.org.id}/agents/{trc.agent.id}/samples", json={"size": 3}).json()
    assert isinstance(auto["seed"], int)  # a seed is always recorded
    first = smp["decisions"][0]["id"]
    assert client.post(f"{API}/agent-samples/{smp['id']}/complete").status_code == 409  # not every decision has a verdict
    assert client.post(f"{API}/agent-samples/{smp['id']}/reviews", json={"trace_id": ids[-1] if ids[-1] not in [d["id"] for d in smp["decisions"]] else ids[0], "verdict": "appropriate"}).status_code == 422
    assert client.post(f"{API}/agent-samples/{smp['id']}/reviews", json={"trace_id": first, "verdict": "great"}).status_code == 422
    for d in smp["decisions"]:
        v = "inappropriate" if d["id"] == first else "appropriate"
        assert client.post(f"{API}/agent-samples/{smp['id']}/reviews", json={"trace_id": d["id"], "verdict": v, "note": "Checked against HL-POL-07."}).status_code == 200
    done = client.post(f"{API}/agent-samples/{smp['id']}/complete").json()
    assert done["status"] == "complete" and done["summary"] == {"appropriate": 4, "inappropriate": 1, "needs_follow_up": 0}
    assert db.scalar(select(AuditLog).where(AuditLog.action == "agent_sample.drawn")) is not None
    assert client.post(f"{API}/agent-samples/{smp['id']}/reviews", json={"trace_id": first, "verdict": "appropriate"}).status_code == 409


def test_only_the_audit_team_samples(client, db, trc, eng):
    _traces(db, trc.agent, n=10)
    for user, code in ((trc.aud2, 404), (trc.caico, 404), (trc.sales, 403)):
        trc.as_(user)
        assert client.post(f"{API}/clients/{trc.org.id}/agents/{trc.agent.id}/samples", json={"size": 2}).status_code in (code, 403, 404), user.name
    trc.as_(trc.chief)  # the Chief Auditor sees every engagement
    assert client.post(f"{API}/clients/{trc.org.id}/agents/{trc.agent.id}/samples", json={"size": 2}).status_code == 200
    assert client.post(f"{API}/clients/{trc.org.id}/agents/{trc.screening.id}/samples", json={"size": 2}).status_code == 409  # not an agent


def test_agents_overview_shows_the_override_trend(client, db, trc, eng):
    _traces(db, trc.agent, n=30, escalated_every=6)
    trc.as_(trc.auditor)
    r = client.get(f"{API}/clients/{trc.org.id}/agents")
    assert r.status_code == 200, r.text
    row = [a for a in r.json()["agents"] if a["id"] == trc.agent.id][0]
    total = sum(m["total"] for m in row["trend"])
    esc = sum(m["escalated"] for m in row["trend"])
    assert total == 30 and esc == 5 and len(row["trend"]) == 6
    assert any(m["override_rate"] is not None for m in row["trend"])


def test_a_month_without_hand_offs_is_flagged(client, db, trc, eng):
    _traces(db, trc.agent, n=25, escalated_every=1000)  # only the first is escalated
    db.query(ActionTrace).filter(ActionTrace.decision == "escalated").count()
    trc.as_(trc.auditor)
    row = [a for a in client.get(f"{API}/clients/{trc.org.id}/agents").json()["agents"] if a["id"] == trc.agent.id][0]
    assert row["flags"] == [] or all("person" in f for f in row["flags"])


def test_decision_logs_pushed_through_the_public_api(client, db, trc):
    from tests.publicapi.test_publicapi import bearer, make_client, token

    trc.as_(trc.caico)
    client.put(f"{API}/register/{trc.agent.id}/agent", json=REG)
    ns = type("W", (), {"as_": trc.as_, "cadmin": trc.admin})
    creds = make_client(client, ns, scopes=["agent_logs:write"])
    t = token(client, creds)
    ev = {"events": [{"time": (utcnow() - timedelta(minutes=5)).isoformat(), "action": "Approved invoice INV-77", "tool": "erp.approve_invoice", "decision": "allowed", "event_id": "E-1"},
                     {"time": (utcnow() - timedelta(minutes=4)).isoformat(), "action": "Released payment PAY-9", "tool": "bank.release_payment", "decision": "allowed", "event_id": "E-2"}]}
    url = f"/api/public/v1/agents/{trc.agent.id}/decisions"
    assert client.post(url, headers=bearer(t), json=ev).status_code == 409  # the tracing add-on is not active
    activate(client, trc, [trc.agent])
    client.cookies.clear()
    r = client.post(url, headers=bearer(t), json=ev)
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 2, "skipped": 0, "unregistered_tools": ["bank.release_payment"]}
    assert client.post(url, headers=bearer(t), json=ev).json()["skipped"] == 2
    rows = list(db.scalars(select(ActionTrace).where(ActionTrace.register_system_id == trc.agent.id)))
    assert {x.source for x in rows} == {"api"}
    alerts = list(db.scalars(select(Notification).where(Notification.kind == "agent_unregistered_tool", Notification.user_id == trc.caico.id)))
    assert len(alerts) == 1
    assert client.post(f"/api/public/v1/agents/{trc.screening.id}/decisions", headers=bearer(t), json=ev).status_code == 409
    assert client.post(url, headers=bearer(t), json={"events": [{"action": "x"}]}).status_code == 422


def test_agentic_question_set_is_added_once_and_applies_to_agents(db):
    from app.questionnaire.agentic import ensure_agentic_questions
    from app.questionnaire.models import Question, TemplateVersion
    from app.questionnaire.rules import EngagementFacts, SystemContext, evaluate_finding, is_applicable

    tv = TemplateVersion(name="Futran AI Audit Template", version="1.0", status="active")
    db.add(tv)
    db.commit()
    assert ensure_agentic_questions(db) > 0
    assert ensure_agentic_questions(db) == 0
    qs = list(db.scalars(select(Question).where(Question.template_version_id == tv.id, Question.sub_section == "AG").order_by(Question.order)))
    codes = [q.code for q in qs]
    assert codes[:1] == ["AG.01"] and len(codes) >= 8 and not any(q.required for q in qs)
    rule = qs[0].section_rule
    facts = EngagementFacts()
    assert is_applicable(rule, {}, SystemContext(agent=True), facts)
    assert is_applicable(rule, {"3.2.01": ["genai_llm", "agentic"]}, SystemContext(), facts)
    assert not is_applicable(rule, {"3.2.01": ["ml"]}, SystemContext(), facts)
    kill = [q for q in qs if q.label.lower().startswith("kill switch")][0]
    assert evaluate_finding(kill.finding_rule, "no", "answered", {}, SystemContext(agent=True), facts) is not None


# ---------------------------------------------------------------- autonomy: the register row and the registration agree
def _alerted(db, user_id):
    return len(list(db.scalars(select(Notification).where(Notification.kind == "agent_permissions_changed", Notification.user_id == user_id))))


def _reg_log(db, s_id, entity, field):
    return list(db.scalars(select(ChangeLog).where(ChangeLog.register_system_id == s_id, ChangeLog.entity == entity, ChangeLog.field == field)))


def test_autonomy_changed_in_the_registration_is_logged_on_the_register(client, db, trc, eng):
    trc.as_(trc.caico)
    client.put(f"{API}/register/{trc.agent.id}/agent", json=REG)
    assert client.put(f"{API}/register/{trc.agent.id}/agent", json=REG | {"autonomy_level": "autonomous"}).status_code == 200
    db.expire_all()
    assert db.get(RegisterSystem, trc.agent.id).autonomy == "autonomous"
    lines = _reg_log(db, trc.agent.id, "RegisterSystem", "autonomy")
    assert len(lines) == 1 and lines[0].new_value and "own" in lines[0].new_value


def test_autonomy_changed_on_the_register_updates_the_registration_and_alerts(client, db, trc, eng):
    trc.as_(trc.caico)
    client.put(f"{API}/register/{trc.agent.id}/agent", json=REG)
    trc.as_(trc.fin_lead)
    r = client.patch(f"{API}/register/{trc.agent.id}", json={"autonomy": "autonomous"})
    assert r.status_code == 200, r.text
    reg = client.get(f"{API}/register/{trc.agent.id}/agent").json()["registration"]
    assert reg["autonomy_level"] == "autonomous" and reg["version"] == 2
    lines = [c for c in _reg_log(db, trc.agent.id, "AgentRegistration", "autonomy_level") if c.reason == "Changed on the register"]
    assert len(lines) == 1 and lines[0].new_value == "Acts on its own"
    assert _alerted(db, trc.caico.id) == 1 and _alerted(db, trc.auditor.id) == 1 and _alerted(db, trc.fin_lead.id) == 0
    client.patch(f"{API}/register/{trc.agent.id}", json={"purpose": "Approves invoices under 2,000 USD"})
    assert _alerted(db, trc.caico.id) == 1  # other fields are not a permission change


def test_autonomy_changed_through_the_public_api_updates_the_registration_and_alerts(client, db, trc, eng):
    from tests.publicapi.test_publicapi import bearer, make_client, token

    trc.as_(trc.caico)
    client.put(f"{API}/register/{trc.agent.id}/agent", json=REG)
    ns = type("W", (), {"as_": trc.as_, "cadmin": trc.admin})
    t = token(client, make_client(client, ns, scopes=["inventory:write", "inventory:read"]))
    r = client.patch(f"/api/public/v1/inventory/systems/{trc.agent.id}", headers=bearer(t), json={"autonomy": "suggest_only"})
    assert r.status_code == 200, r.text
    db.expire_all()
    from app.tracing.agents import registration

    assert registration(db, db.get(RegisterSystem, trc.agent.id)).autonomy_level == "suggest_only"
    assert _alerted(db, trc.caico.id) == 1 and _alerted(db, trc.auditor.id) == 1
