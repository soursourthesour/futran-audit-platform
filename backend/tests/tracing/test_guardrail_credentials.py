"""Security review (plausible finding, fixed defensively): a live GuardRail sync uses the client organisation's own
GuardRail token, never one platform-wide token, so naming another client's policy imports nothing of theirs."""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.core import clock
from app.tracing import guardrail
from app.tracing.models import TracingOrgSettings
from tests.tracing.conftest import activate


@pytest.fixture
def agent(client, db, trc):
    clock.set_now(datetime(2028, 3, 1, 12, 0))
    activate(client, trc, [trc.agent])
    trc.as_(trc.fin_lead)
    yield f"/api/v1/register/{trc.agent.id}/tracing"
    clock.set_now(None)


@pytest.fixture
def live(app, monkeypatch):
    app.state.settings = app.state.settings.model_copy(update={"guardrail_mode": "live", "guardrail_url": "https://guardrail.example", "guardrail_token": "platform-wide"})
    calls = []

    def events(self, policy_ref, agent, since, now):
        calls.append({"token": self.token, "policy": policy_ref})
        return [{"time": "2028-03-01T11:00:00", "action": "Read a record", "decision": "allowed", "policy": policy_ref, "event_id": "gr-1"}]

    monkeypatch.setattr(guardrail.HttpGuardRail, "events", events)
    return calls


def test_a_live_sync_without_the_organisations_guardrail_token_is_refused(client, db, trc, agent, live):
    r = client.post(f"{agent}/guardrail-sync")
    assert r.status_code == 409 and "GuardRail access token" in r.json()["detail"]
    assert live == []  # the platform-wide token is never used
    assert client.get(agent).json()["guardrail_connected"] is False


def test_a_live_sync_uses_the_organisations_own_token(client, db, trc, agent, live):
    trc.as_(trc.admin)
    r = client.put("/api/v1/tracing/guardrail-token", json={"token": "abc-corp-guardrail-token"})
    assert r.status_code == 200 and r.json() == {"guardrail_token_set": True}
    row = db.scalar(select(TracingOrgSettings).where(TracingOrgSettings.organization_id == trc.org.id))
    assert row.guardrail_token_encrypted and "abc-corp-guardrail-token" not in row.guardrail_token_encrypted
    trc.as_(trc.fin_lead)
    assert client.get(agent).json()["guardrail_connected"] is True
    r = client.post(f"{agent}/guardrail-sync")
    assert r.status_code == 200, r.text
    assert live == [{"token": "abc-corp-guardrail-token", "policy": "Invoices-v1"}]


def test_only_the_client_admin_or_caico_sets_the_guardrail_token(client, db, trc, agent):
    for user in (trc.fin_lead, trc.contrib, trc.chief):
        trc.as_(user)
        assert client.put("/api/v1/tracing/guardrail-token", json={"token": "x" * 20}).status_code in (403, 404)
    trc.as_(trc.caico)
    assert client.put("/api/v1/tracing/guardrail-token", json={"token": "caico-sets-it-0001"}).status_code == 200
    assert client.delete("/api/v1/tracing/guardrail-token").json() == {"guardrail_token_set": False}


def test_test_mode_keeps_the_in_process_fake_without_credentials(client, db, trc, agent):
    r = client.post(f"{agent}/guardrail-sync")
    assert r.status_code == 200 and r.json()["added"] > 0
