"""The wave 3 WS-L demo step (app/demo/wave3_l.py) on top of the full demo seed: comment threads with mentions on an ABC
finding and a question response, an API client with a webhook and a delivery log, the recruiting agent's registration and
a reviewed decision sample, and the SOC 2 register with Futran's own AI systems."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.demo.test_demo_v061 import ABC, world  # noqa: F401  (one demo world per module)


@pytest.fixture
def as_user(world):  # noqa: F811
    from app.tenancy.models import User
    from tests.factories import login_as

    clients = []

    def _as(email: str) -> TestClient:
        c = TestClient(world["app"])
        clients.append(c)
        u = world["db"].scalar(select(User).where(User.email == email))
        assert u is not None, email
        return login_as(c, world["db"], u)

    yield _as
    for c in clients:
        c.close()


def _get(c, path):
    r = c.get(f"/api/v1{path}")
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"
    return r.json()


def test_comment_threads_respect_visibility(world, as_user):  # noqa: F811
    fid = world["ids"]["comment_finding"]
    staff = _get(as_user("auditor1@futran.demo"), f"/comments?object_type=finding&object_id={fid}")["threads"]
    assert {t["visibility"] for t in staff} == {"internal", "shared"} and all(t["replies"] for t in staff)
    assert any(t["mentions"] for t in staff)
    client = _get(as_user(f"maria.lopez@{ABC}"), f"/comments?object_type=finding&object_id={fid}")["threads"]
    assert [t["visibility"] for t in client] == ["shared"]
    rid = world["ids"]["comment_response"]
    assert len(_get(as_user("auditor1@futran.demo"), f"/comments?object_type=response&object_id={rid}")["threads"]) == 2
    assert len(_get(as_user(f"priya.shah@{ABC}"), f"/comments?object_type=response&object_id={rid}")["threads"]) == 1
    bell = _get(as_user(f"maria.lopez@{ABC}"), "/me/notifications?filter=mentions")["items"]
    assert any(n["kind"] == "comment_mention" for n in bell)


def test_api_client_webhook_and_delivery_log(world, as_user):  # noqa: F811
    c = as_user(f"sam.okafor@{ABC}")
    d = _get(c, "/admin/api")
    assert [x["name"] for x in d["clients"]] == ["ServiceNow GRC sync"] and d["clients"][0]["last_used_at"]
    hook = d["webhooks"][0]
    log = _get(c, f"/admin/api/webhooks/{hook['id']}/deliveries")["rows"]
    assert log and log[-1]["event"] == "ping" and log[-1]["status"] == "delivered"
    audit = _get(as_user(f"maria.lopez@{ABC}"), "/admin/api")
    assert audit["can_manage"] is False


def test_agent_registration_and_reviewed_sample(world, as_user):  # noqa: F811
    from app.register.models import RegisterSystem

    db = world["db"]
    s = db.scalar(select(RegisterSystem).where(RegisterSystem.organization_id == world["ids"]["abc"], RegisterSystem.reference == "AIS-007"))
    panel = _get(as_user(f"priya.shah@{ABC}"), f"/register/{s.id}/agent")
    assert panel["registration"]["version"] == 2 and panel["reviews"] and sum(panel["reviews"][0]["summary"].values()) == 8
    assert any(m["total"] for m in panel["trend"])
    agents = _get(as_user("auditor1@futran.demo"), f"/clients/{world['ids']['abc']}/agents")["agents"]
    row = [a for a in agents if a["id"] == s.id][0]
    assert row["samples"][0]["status"] == "complete" and row["samples"][0]["seed"] == 20261102


def test_soc2_register_and_futrans_own_ai(world, as_user):  # noqa: F811
    page = _get(as_user("admin@futran.demo"), "/staff/admin/trust")
    assert page["summary"]["total"] >= 15 and page["summary"]["implemented"] >= 4 and len(page["ai_systems"]) == 5
    assert any(c["owner"] for c in page["controls"])
