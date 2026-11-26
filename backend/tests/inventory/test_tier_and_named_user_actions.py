"""Y02: the inventory steps go through the matrix's own actions.

The proposed tier is computed from the use case's answers (spec §11), so nobody types it in. The client proposes it to
Futran when the Department Compliance Lead or CAICO approves the submitted use case (spec §6 rule 3), so that approval
also needs PROPOSE_TIER. Naming the people who use a Tier 2-3 use case needs RECORD_NAMED_USERS, checked only when the
list of named users changes, so other edits to a use case work as before.
"""
import pytest
from sqlalchemy import select

from app.inventory import router as inv_router
from app.policy.actions import Action
from app.policy.matrix import MATRIX
from app.policy.roles import Role
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import _uc, inv  # noqa: F401

LEE = {"person_name": "Lee Park", "email": "lee@abc.test", "role_name": "Recruiter", "oversight_role": ""}


@pytest.fixture
def spy(monkeypatch):
    seen = []
    real = inv_router.authorize

    def record(db, actor, action, **kw):
        seen.append(action)
        return real(db, actor, action, **kw)

    monkeypatch.setattr(inv_router, "authorize", record)
    return seen


def _who(db, email):
    return db.scalar(select(User).where(User.email == email))


def _submitted_by_tom(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, _who(db, "tom@abc.test"))
    uc = _uc(client, cid, hr, [copilot["id"]], name="Meeting notes")
    assert client.post(f"/api/v1/use-cases/{uc['id']}/submit").status_code == 200
    login_as(client, db, _who(db, "priya@abc.test"))
    return uc


def _without(monkeypatch, role, action):
    monkeypatch.setitem(MATRIX, role, {a: s for a, s in MATRIX[role].items() if a != action})


def test_approving_a_use_case_proposes_its_tier(client, db, inv, spy):
    uc = _submitted_by_tom(client, db, inv)
    r = client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "dept_approved", r.text
    assert Action.PROPOSE_TIER in spy


def test_without_propose_tier_the_lead_returns_but_does_not_approve(client, db, inv, monkeypatch):
    uc = _submitted_by_tom(client, db, inv)
    _without(monkeypatch, Role.DEPT_COMPLIANCE_LEAD, Action.PROPOSE_TIER)
    r = client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": True})
    assert r.status_code == 403 and r.json()["detail"] == "You do not have permission to do this."
    r = client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": False, "comment": "Add the usage."})
    assert r.status_code == 200 and r.json()["status"] == "returned", r.text


def test_a_contributor_records_named_users(client, db, inv, spy):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, _who(db, "tom@abc.test"))
    uc = _uc(client, cid, hr, [chatgpt["id"]], named_users=[LEE])
    assert [n["person_name"] for n in uc["named_users"]] == ["Lee Park"]
    assert Action.RECORD_NAMED_USERS in spy


def test_without_record_named_users_the_list_cannot_change_but_the_rest_can(client, db, inv, monkeypatch):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, _who(db, "tom@abc.test"))
    uc = _uc(client, cid, hr, [chatgpt["id"]], named_users=[LEE])
    _without(monkeypatch, Role.CONTRIBUTOR, Action.RECORD_NAMED_USERS)
    body = {"name": uc["name"], "department_id": hr.id, "purpose": "Ranks applicants for New York roles", "tool_ids": [chatgpt["id"]], "data_categories": ["none"],
            "decision_impact": "none", "usage": [{"role_name": "Recruiter", "headcount": 4, "frequency": "daily"}], "named_users": [LEE]}
    r = client.put(f"/api/v1/use-cases/{uc['id']}", json=body)
    assert r.status_code == 200 and r.json()["purpose"] == "Ranks applicants for New York roles", r.text
    r = client.put(f"/api/v1/use-cases/{uc['id']}", json=body | {"named_users": [LEE, {"person_name": "Tom Reyes", "email": "tom@abc.test"}]})
    assert r.status_code == 403 and r.json()["detail"] == "You do not have permission to do this."
    assert client.put(f"/api/v1/use-cases/{uc['id']}", json=body | {"named_users": []}).status_code == 403  # removing someone changes the list too
    assert client.post(f"/api/v1/clients/{cid}/use-cases", json=body | {"name": "Second"}).status_code == 403
    r = client.post(f"/api/v1/clients/{cid}/use-cases", json=body | {"name": "Third", "named_users": []})
    assert r.status_code == 200, r.text


def test_an_auditor_no_longer_changes_named_users(client, db, inv, people):
    """The Auditor holds SUBMIT_USE_CASE on assigned engagements but not RECORD_NAMED_USERS (spec §5: V assigned)."""
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, _who(db, "tom@abc.test"))
    uc = _uc(client, cid, hr, [chatgpt["id"]], named_users=[LEE])
    login_as(client, db, people["aud"])
    body = {"name": uc["name"], "department_id": hr.id, "purpose": "Edited by Futran", "tool_ids": [chatgpt["id"]], "data_categories": ["none"],
            "decision_impact": "none", "usage": [{"role_name": "Recruiter", "headcount": 4, "frequency": "daily"}], "named_users": [LEE]}
    assert client.put(f"/api/v1/use-cases/{uc['id']}", json=body).status_code == 200
    assert client.put(f"/api/v1/use-cases/{uc['id']}", json=body | {"named_users": []}).status_code == 403
