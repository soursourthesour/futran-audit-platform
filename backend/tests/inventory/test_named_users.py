import re

import pytest
from sqlalchemy import select

from app.attestation.models import AttestationCampaign  # noqa: F401
from app.engagements.models import Engagement
from app.inventory.models import AITool, NamedUser, NamedUserLink, UseCase
from app.mail.models import OutboxMessage
from app.tenancy.models import Department, User
from tests.factories import login_as, make_org, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401


@pytest.fixture
def inv(client, db, live):
    """HR with lead Priya and contributor Tom; two tools (company Copilot, personal ChatGPT)."""
    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "HR"})
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Priya", "last_name": "Shah", "email": "priya@abc.test", "job_title": "", "department": "HR", "role": "dept_compliance_lead"})
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Tom", "last_name": "Reyes", "email": "tom@abc.test", "job_title": "", "department": "HR", "role": "contributor"})
    for u in db.scalars(select(User).where(User.organization_id == cid)):
        u.status = "active"
    db.commit()
    hr = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "HR"))
    copilot = client.post(f"/api/v1/clients/{cid}/tools", json={"vendor": "Microsoft", "product": "Copilot", "account_type": "enterprise", "training_on_inputs": "no"}).json()
    chatgpt = client.post(f"/api/v1/clients/{cid}/tools", json={"vendor": "OpenAI", "product": "ChatGPT", "account_type": "personal_free"}).json()
    return cid, e, maria, hr, copilot, chatgpt


def _uc(client, cid, hr, tool_ids, **kw):
    body = {"name": "Résumé screening", "department_id": hr.id, "purpose": "Ranks applicants", "tool_ids": tool_ids, "data_categories": ["none"], "decision_impact": "none", "usage": [{"role_name": "Recruiter", "headcount": 4, "frequency": "daily"}], "named_users": []} | kw
    r = client.post(f"/api/v1/clients/{cid}/use-cases", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_tier2_requires_named_users(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    tom = db.scalar(select(User).where(User.email == "tom@abc.test"))
    login_as(client, db, tom)
    uc = _uc(client, cid, hr, [chatgpt["id"]])
    assert uc["proposed_tier"] == 2 and uc["status"] == "draft"
    r = client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    assert r.status_code == 422 and r.json()["errors"][0] == {"field": "named_users", "message": "Tier 2 and 3 use cases need the people who use them, with their work email."}
    t1 = _uc(client, cid, hr, [copilot["id"]], name="Meeting notes")
    assert t1["proposed_tier"] == 1
    assert client.post(f"/api/v1/use-cases/{t1['id']}/submit").json()["status"] == "submitted"


def test_tier3_needs_oversight_role(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [copilot["id"]], decision_impact="consequential", named_users=[{"person_name": "Lee Park", "email": "lee@abc.test"}])
    r = client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    assert r.status_code == 422 and r.json()["errors"][0]["message"] == "Lee Park needs a human oversight role (for example, reviews the ranked list)."


def test_links_sent_on_submit_tier2(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [chatgpt["id"]], data_categories=["pii"], named_users=[{"person_name": "Lee Park", "email": "lee@abc.test"}, {"person_name": "Tom Reyes", "email": "tom@abc.test"}])
    r = client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    assert r.status_code == 200, r.text
    lee = db.scalar(select(NamedUser).where(NamedUser.email == "lee@abc.test"))
    tom = db.scalar(select(NamedUser).where(NamedUser.email == "tom@abc.test"))
    assert tom.user_id is not None  # has an account: no link needed
    assert db.query(NamedUserLink).filter_by(named_user_id=lee.id).count() == 1
    assert db.query(NamedUserLink).filter_by(named_user_id=tom.id).count() == 0
    mail = db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "named_user_confirm"))
    assert mail.to == ["lee@abc.test"] and "Résumé screening" in mail.body_text


def _link_token(db) -> str:
    mail = db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "named_user_confirm").order_by(OutboxMessage.created_at.desc())).first()
    return re.search(r"/confirm/([A-Za-z0-9_-]+)", mail.body_text).group(1)


def test_confirm_link_public_minimal(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [copilot["id"]], decision_impact="consequential", named_users=[{"person_name": "Lee Park", "email": "lee@abc.test", "oversight_role": "Reviews the ranked list"}])
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    token = _link_token(db)
    client.cookies.clear()
    view = client.get(f"/api/v1/public/confirm/{token}").json()
    assert set(view) == {"client_name", "first_name", "use_case", "tool", "oversight_role", "policy_text", "completed"}
    assert view["first_name"] == "Lee" and view["oversight_role"] == "Reviews the ranked list"
    r = client.post(f"/api/v1/public/confirm/{token}", json={"training_complete": True, "policy_acknowledged": True, "oversight_role_confirmed": False, "unable_reason": "I only read the list; I do not decide."})
    assert r.status_code == 200
    nu = db.scalar(select(NamedUser).where(NamedUser.email == "lee@abc.test"))
    assert nu.training_complete is True and nu.oversight_role_confirmed is False
    assert client.post(f"/api/v1/public/confirm/{token}", json={"training_complete": True, "policy_acknowledged": True, "oversight_role_confirmed": True}).status_code == 410
    assert client.get("/api/v1/public/confirm/nope").status_code == 404


def test_client_cannot_set_final_tier(client, db, people, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [copilot["id"]])
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    assert client.post(f"/api/v1/use-cases/{uc['id']}/final-tier", json={"tier": 1, "rationale": "x"}).status_code == 403
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/use-cases/{uc['id']}/final-tier", json={"tier": 1, "rationale": ""})
    assert r.status_code == 422
    r = client.post(f"/api/v1/use-cases/{uc['id']}/final-tier", json={"tier": 1, "rationale": "Company tenant, no personal data."})
    assert r.status_code == 200 and r.json()["final_tier"] == 1
    login_as(client, db, people["aud2"])  # not on the team
    assert client.post(f"/api/v1/use-cases/{uc['id']}/final-tier", json={"tier": 2, "rationale": "x"}).status_code == 404


def test_admin_cannot_set_final_tier(client, db, people, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [copilot["id"]])
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    from app.tenancy.models import Organization

    admin = make_user(db, db.get(Organization, people["chief"].organization_id), roles=["admin"], name="Ada Admin", email="ada@futran.test")
    db.commit()
    login_as(client, db, admin)
    assert client.post(f"/api/v1/use-cases/{uc['id']}/final-tier", json={"tier": 2, "rationale": "x"}).status_code == 403


def test_raise_tier_resends_links(client, db, people, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [chatgpt["id"]], named_users=[{"person_name": "Lee Park", "email": "lee@abc.test", "oversight_role": "Checks each shortlist"}])
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    lee = db.scalar(select(NamedUser).where(NamedUser.email == "lee@abc.test"))
    first = db.scalar(select(NamedUserLink).where(NamedUserLink.named_user_id == lee.id))
    login_as(client, db, people["aud"])
    client.post(f"/api/v1/use-cases/{uc['id']}/final-tier", json={"tier": 3, "rationale": "Used to shortlist candidates.", "aedt_determination": "in_scope"})
    db.expire_all()
    links = db.scalars(select(NamedUserLink).where(NamedUserLink.named_user_id == lee.id)).all()
    assert len(links) == 2 and db.get(NamedUserLink, first.id).revoked_at is not None
    # lowering does not resend; the Chief Auditor overrides with a rationale
    client.post(f"/api/v1/use-cases/{uc['id']}/final-tier", json={"tier": 2, "rationale": "Shortlist is advisory only."})
    assert len(db.scalars(select(NamedUserLink).where(NamedUserLink.named_user_id == lee.id)).all()) == 2
    login_as(client, db, people["chief"])
    r = client.post(f"/api/v1/use-cases/{uc['id']}/final-tier", json={"tier": 3, "rationale": "Chief override: LL144 applies."})
    assert r.status_code == 200 and r.json()["final_tier"] == 3


def test_attestation_tools_upserted(client, db, inv):
    from datetime import timedelta

    from app.core.clock import utcnow

    cid, e, maria, hr, copilot, chatgpt = inv
    client.post("/api/v1/me/initiation/items/notice/done")
    link = client.post(f"/api/v1/clients/{cid}/attestation/campaigns", json={"department_ids": [hr.id], "closes_at": (utcnow() + timedelta(days=5)).isoformat(), "policy_version": "1.0"}).json()["link"]
    token = link.rsplit("/", 1)[1]
    client.cookies.clear()
    for i in range(2):
        client.post(f"/api/v1/public/attest/{token}", json={"respondent_name": f"S{i}", "department_id": hr.id, "uses_ai": True, "tools_declared": [{"tool": "chatgpt", "account_type": "personal_free"}, {"tool": "in_app", "account_type": "company", "name": "Workday"}], "purposes": [], "data_entered": [], "policy_acknowledged": True})
    tools = {(t.vendor, t.product, t.account_type): t for t in db.scalars(select(AITool).where(AITool.organization_id == cid))}
    assert tools[("OpenAI", "ChatGPT", "personal_free")].declared_count == 2  # matched to the existing row, case-insensitively
    assert tools[("Other", "Workday", "enterprise")].source == "attestation"
    assert len(tools) == 3


def test_stage3_waits_for_use_cases(client, db, inv):
    from app.engagements.gates import gate_status

    cid, e, maria, hr, copilot, chatgpt = inv
    _uc(client, cid, hr, [copilot["id"]])
    eng = db.get(Engagement, e.id)
    eng.stage = 3
    assert "1 use case is still a draft or returned. Submit it or delete it." in gate_status(db, eng).unmet


def test_dept_scope_on_inventory(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Finance"})
    fin = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "Finance"))
    _uc(client, cid, fin, [copilot["id"]], name="Invoice checks")
    _uc(client, cid, hr, [copilot["id"]], name="Interview notes")
    priya = db.scalar(select(User).where(User.email == "priya@abc.test"))
    login_as(client, db, priya)
    names = [u["name"] for u in client.get(f"/api/v1/clients/{cid}/inventory").json()["use_cases"]]
    assert names == ["Interview notes"]
    r = client.post(f"/api/v1/clients/{cid}/use-cases", json={"name": "x", "department_id": fin.id, "tool_ids": [copilot["id"]], "data_categories": ["none"], "decision_impact": "none"})
    assert r.status_code == 403
    other = make_user(db, make_org(db, name="XYZ"), roles=["caico"], name="X", email="x@xyz.test")
    db.commit()
    login_as(client, db, other)
    assert client.get(f"/api/v1/clients/{cid}/inventory").status_code == 404
