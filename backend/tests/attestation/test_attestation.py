from datetime import timedelta

import pytest
from sqlalchemy import select

from app.attestation.models import Attestation, AttestationCampaign
from app.audit_log.models import AuditLog
from app.core.clock import utcnow
from app.engagements.models import Engagement
from app.tenancy.models import Department, User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401

CLOSES = (utcnow() + timedelta(days=10)).isoformat()


@pytest.fixture
def ready(client, db, live):
    """Departments HR (lead Priya), Finance (lead Fay), notice acknowledged."""
    cid, e, maria = live
    login_as(client, db, maria)
    for d in ("HR", "Finance"):
        client.post(f"/api/v1/clients/{cid}/departments", json={"name": d})
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Priya", "last_name": "Shah", "email": "priya@abc.test", "job_title": "", "department": "HR", "role": "dept_compliance_lead"})
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Fay", "last_name": "Lead", "email": "fay@abc.test", "job_title": "", "department": "Finance", "role": "dept_compliance_lead"})
    for u in db.scalars(select(User).where(User.organization_id == cid)):
        u.status = "active"
    db.commit()
    depts = {d.name: d.id for d in db.scalars(select(Department).where(Department.organization_id == cid))}
    return cid, e, maria, depts


def _launch(client, cid, depts):
    return client.post(f"/api/v1/clients/{cid}/attestation/campaigns", json={"department_ids": list(depts.values()), "closes_at": CLOSES, "policy_version": "1.0"})


def _answer(dept_id, name="Sam Staff", email=None, tools=None):
    return {
        "respondent_name": name, "respondent_email": email, "department_id": dept_id, "uses_ai": True,
        "tools_declared": tools or [{"tool": "chatgpt", "account_type": "personal_free"}],
        "purposes": ["writing"], "data_entered": ["client"], "policy_acknowledged": True,
    }


def test_launch_blocked_without_data_notice_ack(client, db, ready):
    cid, e, maria, depts = ready
    r = _launch(client, cid, depts)
    assert r.status_code == 409 and "employee data notice" in r.json()["detail"]
    assert client.post("/api/v1/me/initiation/items/notice/done").status_code == 200
    r = _launch(client, cid, depts)
    assert r.status_code == 200, r.text
    assert r.json()["link"].startswith("/attest/") and r.json()["status"] == "open"
    assert _launch(client, cid, depts).status_code == 409  # one open campaign at a time


def _launched(client, cid, depts):
    client.post("/api/v1/me/initiation/items/notice/done")
    return _launch(client, cid, depts).json()["link"].rsplit("/", 1)[1]


def test_public_link_exposes_no_other_data(client, db, ready):
    cid, e, maria, depts = ready
    token = _launched(client, cid, depts)
    client.cookies.clear()
    r = client.get(f"/api/v1/public/attest/{token}")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"client_name", "policy_version", "policy_text", "departments", "tools", "account_types", "purposes", "data_categories", "closes_at", "open"}
    assert {d["name"] for d in body["departments"]} == {"HR", "Finance"}
    assert set(body["departments"][0]) == {"id", "name"}
    assert client.get("/api/v1/public/attest/not-a-token").status_code == 404


def test_submission_audited_and_counted(client, db, ready):
    cid, e, maria, depts = ready
    token = _launched(client, cid, depts)
    client.cookies.clear()
    r = client.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], email="sam@abc.test"))
    assert r.status_code == 200, r.text
    a = db.scalar(select(Attestation))
    assert a.respondent_email == "sam@abc.test" and a.tools_declared == [{"tool": "chatgpt", "account_type": "personal_free", "name": None}]
    log = db.scalar(select(AuditLog).where(AuditLog.action == "attestation.submit"))
    assert log is not None and log.organization_id == cid and log.actor_id is None
    # the same email again supersedes the earlier answer, which is kept
    client.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], email="SAM@abc.test", tools=[{"tool": "copilot", "account_type": "company"}]))
    assert db.query(Attestation).count() == 2
    assert db.query(Attestation).filter(Attestation.superseded_by_id.is_(None)).count() == 1


def test_bad_submissions_rejected(client, db, ready):
    cid, e, maria, depts = ready
    token = _launched(client, cid, depts)
    client.cookies.clear()
    bad = _answer("not-a-department")
    assert client.post(f"/api/v1/public/attest/{token}", json=bad).status_code == 422
    bad = _answer(depts["HR"]) | {"policy_acknowledged": False}
    r = client.post(f"/api/v1/public/attest/{token}", json=bad)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "policy_acknowledged"
    bad = _answer(depts["HR"]) | {"tools_declared": [{"tool": "chatgpt", "account_type": "stolen"}]}
    assert client.post(f"/api/v1/public/attest/{token}", json=bad).status_code == 422


def test_dept_counts_under_3_masked(client, db, people, ready):
    cid, e, maria, depts = ready
    token = _launched(client, cid, depts)
    client.cookies.clear()
    for i in range(3):
        client.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], name=f"H{i}", email=f"h{i}@abc.test"))
    client.post(f"/api/v1/public/attest/{token}", json=_answer(depts["Finance"], name="F1", email="f1@abc.test"))
    login_as(client, db, maria)
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    rows = {d["name"]: d["responses"] for d in t["departments"]}
    assert rows == {"HR": 3, "Finance": "fewer than 3"}
    assert t["totals"]["responses"] == 4 and t["totals"]["personal_accounts"] == 4
    assert {"label": "ChatGPT · personal, free", "count": 4, "kind": "tool"} in t["tools"]
    assert len(t["individuals"]) == 4  # the CAICO sees individual answers
    assert db.scalar(select(AuditLog).where(AuditLog.action == "attestation.view_individual")) is not None


def test_dept_lead_gets_aggregate_only(client, db, ready):
    cid, e, maria, depts = ready
    token = _launched(client, cid, depts)
    client.cookies.clear()
    for i in range(4):
        client.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], name=f"H{i}", email=f"h{i}@abc.test"))
    priya = db.scalar(select(User).where(User.email == "priya@abc.test"))
    login_as(client, db, priya)
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    assert t["individuals"] is None
    assert [d["name"] for d in t["departments"]] == ["HR"]  # own department only
    assert client.post(f"/api/v1/clients/{cid}/attestation/close").status_code == 403


def test_closed_campaign_rejects_submissions(client, db, people, ready):
    cid, e, maria, depts = ready
    token = _launched(client, cid, depts)
    assert client.post(f"/api/v1/clients/{cid}/attestation/close").status_code == 200
    client.cookies.clear()
    r = client.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"]))
    assert r.status_code == 410
    assert client.get(f"/api/v1/public/attest/{token}").json()["open"] is False
    # a campaign past its closing time is closed too
    c = db.scalar(select(AttestationCampaign))
    c.status, c.closed_at, c.closes_at = "open", None, utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"])).status_code == 410


def test_public_submissions_rate_limited(client, db, ready):
    cid, e, maria, depts = ready
    token = _launched(client, cid, depts)
    client.cookies.clear()
    codes = [client.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], name=f"P{i}", email=f"p{i}@abc.test")).status_code for i in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


def test_stage3_gate_needs_closed_campaign_and_governance(client, db, people, ready):
    from app.engagements.gates import gate_status

    cid, e, maria, depts = ready
    e = db.get(Engagement, e.id)
    e.stage = 3
    db.commit()
    unmet = gate_status(db, e).unmet
    assert "Run and close the employee attestation campaign." in unmet and "The client has not submitted the AI governance structure." in unmet
    _launched(client, cid, depts)
    client.post(f"/api/v1/clients/{cid}/attestation/close")
    assert gate_status(db, e).unmet == ["The client has not submitted the AI governance structure."]


def test_discovery_finishes_when_both_done(client, db, people, ready):
    cid, e, maria, depts = ready
    _launched(client, cid, depts)
    client.post(f"/api/v1/clients/{cid}/attestation/close")
    for i in client.get(f"/api/v1/clients/{cid}/governance").json()["items"]:
        client.put(f"/api/v1/governance/items/{i['id']}", json={"status": "not_applicable", "na_reason": "Not relevant."})
    db.expire_all()
    eng = db.get(Engagement, e.id)
    eng.stage = 3
    db.commit()
    assert client.post(f"/api/v1/clients/{cid}/governance/submit", json={"accuracy_confirmed": True}).status_code == 200
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 4
