"""F17 webhooks: HMAC-SHA256 signatures, no private network targets, retries with backoff, a delivery log, and the three
events (sign-off completed, remediation overdue, new regulatory update). Tests never touch the network."""
import hashlib
import hmac
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.clock import utcnow
from app.publicapi import netguard, webhooks
from app.publicapi.models import Webhook, WebhookDelivery
from app.signoffs.models import SignOff
from tests.comments.conftest import w  # noqa: F401

API = "/api/v1"
PUBLIC_IP = "93.184.215.14"


@pytest.fixture(autouse=True)
def live_mode(settings, client):
    """Webhooks in live mode (the sender is still injected, and names resolve from the table below)."""
    settings.webhook_mode = "live"
    client.app.state.settings = settings


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """Names resolve from this table only; nothing reaches a real resolver."""
    table = {"hooks.abccorp.example": [PUBLIC_IP], "grc.xyz.example": [PUBLIC_IP], "rebind.example": ["10.1.2.3"], "mixed.example": [PUBLIC_IP, "127.0.0.1"]}

    def resolve(host):
        if host not in table:
            raise netguard.Unresolvable(host)
        return table[host]

    monkeypatch.setattr(netguard, "resolve_host", resolve)
    return table


class Recorder:
    def __init__(self, status=200):
        self.status, self.calls = status, []

    def __call__(self, url, body, headers, timeout):
        self.calls.append({"url": url, "body": body, "headers": headers})
        return self.status if not callable(self.status) else self.status()


def add_hook(client, w, url="https://hooks.abccorp.example/futran", events=("signoff.completed", "remediation.overdue", "regulatory_update.published")):
    w.as_(w.cadmin)
    return client.post(f"{API}/admin/api/webhooks", json={"url": url, "events": list(events)})


@pytest.mark.parametrize("url", [
    "http://hooks.abccorp.example/x",  # not https
    "https://localhost/x", "https://127.0.0.1/x", "https://[::1]/x", "https://0.0.0.0/x",
    "https://10.0.0.5/x", "https://172.16.4.1/x", "https://192.168.1.10/x", "https://169.254.169.254/latest/meta-data",
    "https://[fe80::1]/x", "https://[fd00::1]/x", "https://100.64.0.1/x",
    "https://rebind.example/x", "https://mixed.example/x", "https://unknown-host.example/x",
    "https://user:pass@hooks.abccorp.example/x", "https://hooks.abccorp.example:22/x",
])
def test_private_and_unsafe_targets_are_refused(client, w, url):
    r = add_hook(client, w, url=url)
    assert r.status_code == 422, (url, r.text)


def test_signing_secret_is_shown_once_and_not_stored_in_clear(client, db, w):
    r = add_hook(client, w)
    assert r.status_code == 200, r.text
    secret = r.json()["signing_secret"]
    row = db.get(Webhook, r.json()["webhook"]["id"])
    assert secret not in str([getattr(row, c.key) for c in row.__table__.columns])
    assert secret not in client.get(f"{API}/admin/api").text
    w.as_(w.caico)
    assert client.post(f"{API}/admin/api/webhooks", json={"url": "https://hooks.abccorp.example/y", "events": ["signoff.completed"]}).status_code == 403


def test_delivery_is_signed_with_hmac_sha256(client, db, w, settings):
    hook = add_hook(client, w).json()
    rec = Recorder()
    webhooks.enqueue(db, w.org.id, "signoff.completed", {"engagement": "FAP-2026-001", "sign_off": 5}, event_key="test-1")
    assert webhooks.deliver_due(db, settings, utcnow(), sender=rec) == 1
    call = rec.calls[0]
    ts = call["headers"]["X-Futran-Timestamp"]
    expected = hmac.new(hook["signing_secret"].encode(), f"{ts}.".encode() + call["body"], hashlib.sha256).hexdigest()
    assert call["headers"]["X-Futran-Signature"] == f"t={ts},v1={expected}"
    payload = json.loads(call["body"])
    assert payload["event"] == "signoff.completed" and payload["data"]["sign_off"] == 5 and payload["id"]
    d = db.scalar(select(WebhookDelivery).where(WebhookDelivery.webhook_id == hook["webhook"]["id"]))
    assert d.status == "delivered" and d.attempts == 1 and d.last_status_code == 200


def test_failures_retry_with_backoff_then_stop(client, db, w, settings):
    add_hook(client, w)
    rec = Recorder(status=503)
    webhooks.enqueue(db, w.org.id, "signoff.completed", {"sign_off": 7}, event_key="test-2")
    now = utcnow()
    webhooks.deliver_due(db, settings, now, sender=rec)
    d = db.scalar(select(WebhookDelivery))
    assert d.status == "retrying" and d.attempts == 1 and d.next_attempt_at > now
    first_gap = d.next_attempt_at - now
    assert webhooks.deliver_due(db, settings, now, sender=rec) == 0  # not due yet
    for _ in range(webhooks.MAX_ATTEMPTS):
        webhooks.deliver_due(db, settings, d.next_attempt_at or now, sender=rec)
        if d.status == "failed":
            break
    assert d.status == "failed" and d.attempts == webhooks.MAX_ATTEMPTS
    assert len(rec.calls) == webhooks.MAX_ATTEMPTS
    assert webhooks.BACKOFF[1] > webhooks.BACKOFF[0] == first_gap


def test_a_host_that_turns_private_at_send_time_is_blocked(client, db, w, settings, fake_dns):
    add_hook(client, w)
    fake_dns["hooks.abccorp.example"] = ["192.168.0.10"]
    rec = Recorder()
    webhooks.enqueue(db, w.org.id, "signoff.completed", {}, event_key="test-3")
    webhooks.deliver_due(db, settings, utcnow(), sender=rec)
    d = db.scalar(select(WebhookDelivery))
    assert rec.calls == [] and d.status == "blocked" and "private" in d.last_error


def test_events_go_only_to_the_own_organizations_subscribed_hooks(client, db, w, settings):
    add_hook(client, w, events=["remediation.overdue"])
    w.as_(w.x_admin)
    client.post(f"{API}/admin/api/webhooks", json={"url": "https://grc.xyz.example/hook", "events": ["signoff.completed", "remediation.overdue"]})
    webhooks.enqueue(db, w.org.id, "signoff.completed", {}, event_key="a")
    assert db.scalar(select(WebhookDelivery)) is None  # ABC's hook does not take sign-off events
    webhooks.enqueue(db, w.org.id, "remediation.overdue", {}, event_key="b")
    rows = list(db.scalars(select(WebhookDelivery)))
    assert len(rows) == 1 and rows[0].organization_id == w.org.id


def test_signoff_completed_and_remediation_overdue_are_raised_once(client, db, w, settings):
    add_hook(client, w)
    so = SignOff(organization_id=w.org.id, engagement_id=w.e.id, number=5, title="Findings approved", required_approver_roles=["chief_auditor"], status="approved",
                 approved_at=utcnow())
    db.add(so)
    w.item.due_date = date.today() - timedelta(days=1)
    db.commit()
    webhooks.run_event_scan(db, settings, utcnow())
    webhooks.run_event_scan(db, settings, utcnow())
    events = sorted(d.event for d in db.scalars(select(WebhookDelivery)))
    assert events == ["remediation.overdue", "signoff.completed"]
    body = {d.event: d.payload for d in db.scalars(select(WebhookDelivery))}
    assert body["signoff.completed"]["data"]["sign_off"] == 5 and body["signoff.completed"]["data"]["engagement"] == "FAP-2026-001"
    assert body["remediation.overdue"]["data"]["finding_ref"] == "F-001"


def test_events_from_before_the_hook_existed_are_not_replayed(client, db, w, settings):
    so = SignOff(organization_id=w.org.id, engagement_id=w.e.id, number=3, title="Inventory confirmed", required_approver_roles=["caico"], status="approved",
                 approved_at=utcnow() - timedelta(days=30))
    db.add(so)
    db.commit()
    add_hook(client, w)
    webhooks.run_event_scan(db, settings, utcnow())
    assert db.scalar(select(WebhookDelivery).where(WebhookDelivery.event == "signoff.completed")) is None


def test_test_ping_and_delivery_log_on_the_admin_screen(client, db, w, settings):
    hook = add_hook(client, w).json()["webhook"]
    client.app.state.webhook_sender = Recorder()
    r = client.post(f"{API}/admin/api/webhooks/{hook['id']}/test")
    assert r.status_code == 200 and r.json()["status"] == "delivered"
    log = client.get(f"{API}/admin/api/webhooks/{hook['id']}/deliveries").json()["rows"]
    assert log[0]["event"] == "ping" and log[0]["status"] == "delivered"
    w.as_(w.x_admin)
    assert client.get(f"{API}/admin/api/webhooks/{hook['id']}/deliveries").status_code == 404


def test_fake_mode_accepts_reserved_example_names_without_dns_and_sends_nothing(client, db, w, settings, monkeypatch):
    settings.webhook_mode = "fake"
    client.app.state.settings = settings

    def no_dns(host):
        raise AssertionError(f"DNS lookup for {host}")

    monkeypatch.setattr(netguard, "resolve_host", no_dns)
    assert add_hook(client, w, url="https://grc.abccorp.example/futran").status_code == 200
    for bad in ("https://localhost/x", "https://10.0.0.5/x", "http://grc.abccorp.example/x"):
        assert add_hook(client, w, url=bad).status_code == 422, bad
    webhooks.enqueue(db, w.org.id, "signoff.completed", {}, event_key="fake-1")
    webhooks.deliver_due(db, settings, utcnow())  # the fake sender: nothing leaves the process
    assert db.scalar(select(WebhookDelivery)).status == "delivered"
    settings.webhook_mode = "live"  # switched to live later: the name no longer passes
    monkeypatch.setattr(netguard, "resolve_host", lambda h: (_ for _ in ()).throw(netguard.Unresolvable(h)))
    webhooks.enqueue(db, w.org.id, "signoff.completed", {}, event_key="fake-2")
    webhooks.deliver_due(db, settings, utcnow())
    assert db.scalar(select(WebhookDelivery).where(WebhookDelivery.event_key == "fake-2")).status == "blocked"


def test_published_regulatory_updates_raise_a_webhook_once(client, db, w, settings):
    from tests.publicapi.test_publicapi import _update

    add_hook(client, w, events=["regulatory_update.published"])
    u = _update(db, w.org)
    _update(db, w.other, ref="RU-009", title="Only for XYZ")
    webhooks.run_event_scan(db, settings, utcnow())
    webhooks.run_event_scan(db, settings, utcnow())
    rows = list(db.scalars(select(WebhookDelivery)))
    assert len(rows) == 1 and rows[0].payload["data"]["id"] == u.id and rows[0].organization_id == w.org.id
