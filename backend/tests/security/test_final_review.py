"""Final whole-branch review: each finding reproduced before the fix."""
from sqlalchemy import select

from app.core.clock import utcnow
from app.engagements.gates import gate_status
from app.engagements.models import Engagement
from app.systems.models import AISystem
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import _uc, inv  # noqa: F401
from tests.signoffs.test_signoffs import _approved_dept, rev  # noqa: F401


def _u(db, email):
    return db.scalar(select(User).where(User.email == email))


def _stage(db, e, n):
    db.get(Engagement, e.id).stage = n
    db.commit()


# Important 1: fieldwork cannot end, and the inventory cannot change, while sign-offs 2–4 are not approved
def test_f1_stage5_gate_needs_signoffs_2_to_4(client, db, inv, people):
    cid, e, *_ = inv
    _stage(db, e, 5)
    for s in db.scalars(select(AISystem).where(AISystem.engagement_id == e.id)):
        s.deleted_at = utcnow()
    db.commit()
    unmet = gate_status(db, db.get(Engagement, e.id)).unmet
    assert any("Sign-off 4" in u for u in unmet)


def test_f1_inventory_locked_after_fieldwork_whatever_signoff4(client, db, inv, people):
    cid, e, maria, hr, copilot, chatgpt = inv
    _stage(db, e, 6)
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/use-cases", json={"name": "Late", "department_id": hr.id, "tool_ids": [copilot["id"]], "data_categories": ["none"], "decision_impact": "none", "usage": [], "named_users": []})
    assert r.status_code == 409


# Important 2: sign-offs 3 and 4 need every department complete, not only its sign-off 2
def test_f2_signoff3_blocked_by_new_draft_use_case(client, db, rev):
    cid, e, maria, hr, copilot, chatgpt = rev
    _approved_dept(client, db, cid, hr, copilot)
    login_as(client, db, _u(db, "tom@abc.test"))
    _uc(client, cid, hr, [copilot["id"]], name="Added after sign-off 2")
    login_as(client, db, _u(db, "priya@abc.test"))
    r = client.post(f"/api/v1/clients/{cid}/signoffs/3/submit", json={})
    assert r.status_code == 409 and "Added after sign-off 2" in r.text


# Important 3: a client reads its own people's actions and shared milestones, not Futran's internal work
def test_f3_client_audit_log_hides_futran_internal_events(client, db, inv, people):
    cid, e, maria, *_ = inv
    _stage(db, e, 5)
    login_as(client, db, people["aud"])
    client.post(f"/api/v1/clients/{cid}/findings", json={"title": "Secret draft finding", "severity": "high"})
    login_as(client, db, maria)
    rows = client.get("/api/v1/audit-log").json()
    assert rows and not any("Secret draft finding" in (r["summary"] or "") for r in rows)
    assert all("ip" not in r for r in rows)
    assert any("Engagement letter" in (r["summary"] or "") or r["action"].startswith("signoff.") for r in rows)  # shared milestones stay visible


# Minor 5 (upgraded): sign-offs 6 and 7 are not reopened through correction
def test_f5_signoff7_not_correctable():
    from app.signoffs.service import CORRECTABLE_UNTIL

    assert 6 not in CORRECTABLE_UNTIL and 7 not in CORRECTABLE_UNTIL


# Minor 6 (upgraded): behind the proxy the caller's address is the one the proxy appended, not one the caller sent
def test_f6_client_ip_uses_rightmost_forwarded_entry(client, settings):
    from types import SimpleNamespace

    from app.core.ratelimit import client_ip

    settings.trust_proxy_headers = True
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)), headers={"x-forwarded-for": "6.6.6.6, 203.0.113.9"}, client=SimpleNamespace(host="10.0.0.1"))
    assert client_ip(req) == "203.0.113.9"
