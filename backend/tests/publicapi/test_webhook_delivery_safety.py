"""Webhook delivery hardening: the connection goes to the address that was checked (no DNS rebinding), the delivery log
shows plain reasons rather than exception text, and test sends are rate limited. Tests never touch the network."""
import socket

import pytest
from sqlalchemy import select

from app.core.clock import utcnow
from app.publicapi import netguard, webhooks
from app.publicapi.models import Webhook, WebhookDelivery
from tests.comments.conftest import w  # noqa: F401
from tests.factories import make_org

API = "/api/v1"
PUBLIC_IP = "93.184.215.14"
REBIND = "rebind.attacker.example.com"


class Rebinding:
    """socket.getaddrinfo for one name: public on the first lookup, loopback on every later one."""

    def __init__(self, monkeypatch, public_lookups=1):
        self.lookups, self.connects, self.public_lookups = 0, [], public_lookups
        real = socket.getaddrinfo

        def getaddrinfo(host, port, *a, **k):
            if host == REBIND:
                self.lookups += 1
                ip = PUBLIC_IP if self.lookups <= self.public_lookups else "127.0.0.1"
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
            if host == PUBLIC_IP or host == "127.0.0.1":
                return real(host, port, *a, **k)
            raise socket.gaierror(f"no lookups in tests: {host}")

        def create_connection(address, *a, **k):  # what the real one does: resolve, then connect; here it never connects
            host, port = address[0], address[1]
            ip = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4][0]
            self.connects.append((ip, port))
            raise ConnectionRefusedError(f"[Errno 111] Connection refused ({ip})")

        for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.delenv(var, raising=False)  # a direct connection, as on the laptop
        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
        monkeypatch.setattr(socket, "create_connection", create_connection)


def _hook(db, settings, url=f"https://{REBIND}:8443/hook"):
    org = make_org(db)
    ref, enc = webhooks.seal_secret(settings, "whsec_test")
    h = Webhook(organization_id=org.id, url=url, events=["signoff.completed"], secret_encrypted=enc, secret_ref=ref, status="active")
    db.add(h)
    db.flush()
    return org, h


def test_a_name_that_rebinds_to_loopback_between_check_and_send_is_never_connected(db, settings, monkeypatch):
    settings.webhook_mode = "live"
    net = Rebinding(monkeypatch)
    org, _ = _hook(db, settings)
    webhooks.enqueue(db, org.id, "signoff.completed", {}, event_key="rebind-1")
    webhooks.deliver_due(db, settings, utcnow(), sender=webhooks.http_sender)
    assert all(ip == PUBLIC_IP for ip, _ in net.connects), net.connects
    d = db.scalar(select(WebhookDelivery))
    assert d.status in ("blocked", "retrying")


def test_the_sender_connects_to_the_checked_address_with_the_original_host_name(monkeypatch):
    net = Rebinding(monkeypatch)
    with pytest.raises(Exception):
        webhooks.http_sender(f"https://{REBIND}:8443/hook", b"{}", {}, 2.0)
    assert net.connects == [(PUBLIC_IP, 8443)]  # one lookup, then the pinned address: no second lookup reaches loopback
    assert net.lookups == 1

    import httpx

    net.lookups, seen = 0, {}

    def handle(self, request):
        seen["host"], seen["header"], seen["sni"] = request.url.host, request.headers["host"], request.extensions.get("sni_hostname")
        return httpx.Response(204)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    assert webhooks.http_sender(f"https://{REBIND}:8443/hook", b"{}", {}, 2.0) == 204
    assert seen == {"host": PUBLIC_IP, "header": f"{REBIND}:8443", "sni": REBIND}  # the certificate is checked for the name


def test_the_sender_refuses_when_the_name_now_points_inside_the_network(monkeypatch):
    net = Rebinding(monkeypatch, public_lookups=0)
    with pytest.raises(netguard.Unsafe):
        webhooks.http_sender(f"https://{REBIND}/hook", b"{}", {}, 2.0)
    assert net.connects == []


# ---------------------------------------------------------------- what the admin screen shows
@pytest.fixture
def live(settings, client, monkeypatch):
    settings.webhook_mode = "live"
    client.app.state.settings = settings
    monkeypatch.setattr(netguard, "resolve_host", lambda host: [PUBLIC_IP] if host == "hooks.abccorp.example" else (_ for _ in ()).throw(netguard.Unresolvable(host)))


def _add(client, w):
    w.as_(w.cadmin)
    r = client.post(f"{API}/admin/api/webhooks", json={"url": "https://hooks.abccorp.example/futran", "events": ["signoff.completed"]})
    assert r.status_code == 200, r.text
    return r.json()["webhook"]["id"]


def _raise(exc):
    def send(url, body, headers, timeout):
        raise exc
    return send


@pytest.mark.parametrize(("sender", "reason"), [
    (_raise(ConnectionRefusedError("[Errno 111] Connection refused to 10.20.30.40:8443")), "Could not connect."),
    (_raise(TimeoutError("timed out reading from 10.20.30.40")), "Timed out."),
    (lambda *a: 503, "Receiver returned 5xx."),
    (lambda *a: 404, "Receiver returned 4xx."),
    (lambda *a: 302, "Receiver returned a redirect. Redirects are not followed."),
])
def test_test_send_and_delivery_log_show_a_plain_reason_only(client, db, w, live, sender, reason):
    hook_id = _add(client, w)
    client.app.state.webhook_sender = sender
    r = client.post(f"{API}/admin/api/webhooks/{hook_id}/test")
    assert r.status_code == 200, r.text
    assert r.json()["last_error"] == reason
    log = client.get(f"{API}/admin/api/webhooks/{hook_id}/deliveries").json()["rows"]
    assert log[0]["last_error"] == reason
    assert "10.20.30.40" not in r.text and "Errno" not in r.text


def test_test_sends_are_rate_limited(client, db, w, live):
    hook_id = _add(client, w)
    client.app.state.webhook_sender = lambda *a: 200
    codes = [client.post(f"{API}/admin/api/webhooks/{hook_id}/test").status_code for _ in range(webhooks.TEST_SENDS_PER_MINUTE + 1)]
    assert codes[:-1] == [200] * webhooks.TEST_SENDS_PER_MINUTE and codes[-1] == 429
