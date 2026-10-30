"""The GuardRail action feed behind an adapter (spec §27.3: action traces "fed by GuardRail or the agent's logs").

`adapter(settings)` returns the live HTTP adapter when GUARDRAIL_URL is set, the in-process fake in test mode (tests and the
demo never touch the network), or None when GuardRail is not connected. The live adapter uses the standard library only.
Events have the same fields as a JSON import: time, session, action, tool, data_touched, decision, policy, approver, agent,
event_id.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Protocol

from app.core.errors import Conflict


class GuardRailFeed(Protocol):
    name: str

    def events(self, policy_ref: str, agent: str, since: datetime | None, now: datetime) -> list[dict]: ...


class FakeGuardRail:
    """Deterministic events for a policy: the same hour gives the same event ids, so a repeat sync adds nothing."""

    name = "fake"
    PATTERN = [
        ("Search the knowledge base", "kb.search", "Public product documents", "allowed", None),
        ("Read a record", "records.read", "One customer or supplier record", "allowed", None),
        ("Draft a reply", "mail.draft", "Message text", "allowed", None),
        ("Act above the delegated limit", "erp.approve", "Amount over the policy limit", "blocked", "GuardRail: not delegated"),
        ("Hand over to a person", "handoff.human", "Conversation transcript", "escalated", "Duty officer"),
        ("Create a record", "records.create", "Name, email", "allowed", None),
    ]

    def events(self, policy_ref: str, agent: str, since: datetime | None, now: datetime) -> list[dict]:
        hour = now.replace(minute=0, second=0, microsecond=0)
        out = []
        for n, (action, tool, data, decision, note) in enumerate(self.PATTERN):
            at = hour - timedelta(minutes=9 * (len(self.PATTERN) - n))
            out.append({"time": at.isoformat(), "session": f"S-{hour:%m%d%H}-{n // 2 + 1}", "action": action, "tool": tool, "data_touched": data, "decision": decision,
                        "policy": policy_ref, "approver": note, "agent": agent, "event_id": f"gr-{policy_ref}-{hour:%Y%m%d%H}-{n + 1}"})
        return out


class HttpGuardRail:
    name = "live"

    def __init__(self, url: str, token: str | None):
        self.url, self.token = url.rstrip("/"), token

    def events(self, policy_ref: str, agent: str, since: datetime | None, now: datetime) -> list[dict]:
        q = urllib.parse.urlencode({"since": since.isoformat()} if since else {})
        req = urllib.request.Request(f"{self.url}/policies/{urllib.parse.quote(policy_ref, safe='')}/events?{q}", headers={"Accept": "application/json", **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 (configured URL only)
                body = json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # network, HTTP or JSON error: say so, change nothing
            raise Conflict(f"GuardRail did not answer ({exc.__class__.__name__}). Nothing was imported; try again later.") from exc
        return body.get("events", []) if isinstance(body, dict) else body


def mode(settings) -> str:
    """fake, live or off."""
    m = (getattr(settings, "guardrail_mode", "auto") or "auto").lower()
    url = getattr(settings, "guardrail_url", None)
    if m == "auto":
        m = "live" if url else ("fake" if settings.test_mode else "off")
    if m == "live" and not url:
        return "off"
    return m if m in ("fake", "live") else "off"


def adapter(settings, token: str | None = None) -> GuardRailFeed | None:
    """The feed for one organisation. Live mode needs that organisation's own GuardRail token (`token`): the
    platform-wide GUARDRAIL_TOKEN is never used for a client's sync, so a policy name typed on one client's system
    cannot pull another client's events."""
    m = mode(settings)
    if m == "fake":
        return FakeGuardRail()
    if m == "live" and token:
        return HttpGuardRail(settings.guardrail_url, token)
    return None
