"""Y02: submitting the governance structure is the CAICO's approval of the answers (spec §5: C/E/A), so it needs
APPROVE_GOVERNANCE as well as ANSWER_GOVERNANCE. Answering items is unchanged."""
import pytest

from app.governance import router as gov_router
from app.policy.actions import Action
from app.policy.matrix import MATRIX
from app.policy.roles import Role
from tests.factories import login_as
from tests.governance.test_governance import _answer_all
from tests.initiation.conftest import live, people, submitted  # noqa: F401


@pytest.fixture
def spy(monkeypatch):
    seen = []
    real = gov_router.authorize

    def record(db, actor, action, **kw):
        seen.append(action)
        return real(db, actor, action, **kw)

    monkeypatch.setattr(gov_router, "authorize", record)
    return seen


def test_submitting_the_governance_structure_needs_approve_governance(client, db, live, spy):
    cid, e, maria = live
    login_as(client, db, maria)
    _answer_all(client, cid)
    r = client.post(f"/api/v1/clients/{cid}/governance/submit", json={"accuracy_confirmed": True})
    assert r.status_code == 200 and r.json()["status"] == "submitted", r.text
    assert Action.APPROVE_GOVERNANCE in spy


def test_without_approve_governance_the_caico_answers_but_does_not_submit(client, db, live, monkeypatch):
    cid, e, maria = live
    login_as(client, db, maria)
    monkeypatch.setitem(MATRIX, Role.CAICO, {a: s for a, s in MATRIX[Role.CAICO].items() if a != Action.APPROVE_GOVERNANCE})
    _answer_all(client, cid)
    assert all(i["status"] != "unanswered" for i in client.get(f"/api/v1/clients/{cid}/governance").json()["items"])
    r = client.post(f"/api/v1/clients/{cid}/governance/submit", json={"accuracy_confirmed": True})
    assert r.status_code == 403 and r.json()["detail"] == "You do not have permission to do this."
