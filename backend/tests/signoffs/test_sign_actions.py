"""Y02: signing goes through the matrix's sign actions. A client signer needs SIGN_CLIENT_SIGNOFF; the Chief Auditor
signing the final report (sign-off 7) needs SIGN_FINAL_REPORT. Who can sign is unchanged."""
import pytest

from app.policy.actions import Action
from app.policy.matrix import MATRIX
from app.policy.roles import Role
from app.signoffs import service as so_svc
from tests.factories import login_as
from tests.signoffs.test_signoff1 import sent  # noqa: F401


@pytest.fixture
def spy(monkeypatch):
    seen = []
    real = so_svc.authorize

    def record(db, actor, action, **kw):
        seen.append(action)
        return real(db, actor, action, **kw)

    monkeypatch.setattr(so_svc, "authorize", record)
    return seen


def _sign(client, so, user):
    return client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": user.name})


def test_a_client_signer_is_checked_against_sign_client_signoff(client, db, sent, spy, people):
    cid, e, maria, so = sent
    login_as(client, db, maria)
    assert _sign(client, so, maria).status_code == 200
    assert Action.SIGN_CLIENT_SIGNOFF in spy
    spy.clear()
    login_as(client, db, people["chief"])
    assert _sign(client, so, people["chief"]).status_code == 200  # sign-off 1: the Chief Auditor signs as before
    assert Action.SIGN_CLIENT_SIGNOFF not in spy and Action.SIGN_FINAL_REPORT not in spy


def test_without_the_sign_action_the_role_alone_does_not_sign(client, db, sent, monkeypatch):
    cid, e, maria, so = sent
    monkeypatch.setitem(MATRIX, Role.CAICO, {a: s for a, s in MATRIX[Role.CAICO].items() if a != Action.SIGN_CLIENT_SIGNOFF})
    login_as(client, db, maria)
    assert _sign(client, so, maria).status_code == 403


def _as_final_report(db, so):
    so.number = 7  # the final report sign-off, which the Chief Auditor signs
    db.commit()


def test_the_final_report_is_signed_on_sign_final_report(client, db, sent, spy, people):
    cid, e, maria, so = sent
    _as_final_report(db, so)
    login_as(client, db, people["chief"])
    r = _sign(client, so, people["chief"])
    assert Action.SIGN_FINAL_REPORT in spy and r.status_code != 403, r.text


def test_without_sign_final_report_the_chief_does_not_sign_it(client, db, sent, people, monkeypatch):
    cid, e, maria, so = sent
    _as_final_report(db, so)
    monkeypatch.setitem(MATRIX, Role.CHIEF_AUDITOR, {a: s for a, s in MATRIX[Role.CHIEF_AUDITOR].items() if a != Action.SIGN_FINAL_REPORT})
    login_as(client, db, people["chief"])
    assert _sign(client, so, people["chief"]).status_code == 403


def _as_management_responses(db, so):
    so.number = 6  # management responses and remediation plan, which the CAICO and Executive Sponsor sign
    db.commit()


def test_signing_management_responses_approves_them(client, db, sent, spy):
    """Y02: sign-off 6 is the client's approval of its management responses, so a signer needs APPROVE_RESPONSES."""
    cid, e, maria, so = sent
    _as_management_responses(db, so)
    login_as(client, db, maria)
    r = _sign(client, so, maria)
    assert Action.APPROVE_RESPONSES in spy and r.status_code != 403, r.text


def test_without_approve_responses_the_caico_does_not_sign_them(client, db, sent, monkeypatch):
    cid, e, maria, so = sent
    _as_management_responses(db, so)
    monkeypatch.setitem(MATRIX, Role.CAICO, {a: s for a, s in MATRIX[Role.CAICO].items() if a != Action.APPROVE_RESPONSES})
    login_as(client, db, maria)
    assert _sign(client, so, maria).status_code == 403
