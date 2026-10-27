"""Regression tests for the Phase 4 review findings (C1, I1–I9, I11 and the minors fixed with them)."""
from datetime import timedelta

from sqlalchemy import select

from app.attestation.models import Attestation
from app.audit_log.models import AuditLog
from app.core.clock import utcnow
from app.engagements.models import Engagement
from app.inventory.models import AITool, NamedUser, NamedUserLink
from app.notifications.models import Notification
from app.tenancy.models import Department, RoleAssignment, User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import _link_token, _uc, inv  # noqa: F401

CLOSES = (utcnow() + timedelta(days=10)).isoformat()


def _user(db, email):
    return db.scalar(select(User).where(User.email == email))


def _campaign(client, cid, depts):
    client.post("/api/v1/me/initiation/items/notice/done")
    r = client.post(f"/api/v1/clients/{cid}/attestation/campaigns", json={"department_ids": depts, "closes_at": CLOSES, "policy_version": "1.0"})
    assert r.status_code == 200, r.text
    return r.json()["link"].rsplit("/", 1)[1]


def _pub(client):
    return client.__class__(client.app, raise_server_exceptions=False)


# ---- C1: answers are append-only; counts are recomputed
def test_resubmission_keeps_the_earlier_answer(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, maria)
    token = _campaign(client, cid, [hr.id])
    pub = _pub(client)
    good = {"respondent_name": "Ceo Person", "respondent_email": "ceo@abc.test", "department_id": hr.id, "uses_ai": True, "tools_declared": [{"tool": "copilot", "account_type": "company"}], "purposes": ["writing"], "data_entered": ["none"], "policy_acknowledged": True}
    assert pub.post(f"/api/v1/public/attest/{token}", json=good).status_code == 200
    forged = good | {"tools_declared": [{"tool": "claude", "account_type": "personal_free"}] * 2000, "data_entered": ["phi"]}
    assert pub.post(f"/api/v1/public/attest/{token}", json=forged).status_code == 200
    rows = db.scalars(select(Attestation).order_by(Attestation.submitted_at)).all()
    assert len(rows) == 2 and rows[0].superseded_by_id == rows[1].id and rows[0].data_entered == ["none"]
    assert rows[1].tools_declared == [{"tool": "claude", "account_type": "personal_free", "name": None}]  # de-duplicated
    log = db.scalars(select(AuditLog).where(AuditLog.action == "attestation.submit").order_by(AuditLog.at)).all()[-1]
    assert log.before == {"data_entered": ["none"], "tools_declared": [{"tool": "copilot", "account_type": "company", "name": None}], "purposes": ["writing"], "uses_ai": True}
    tools = {(t.product, t.account_type): t.declared_count for t in db.scalars(select(AITool).where(AITool.organization_id == cid))}
    assert tools[("Copilot", "enterprise")] == 0 and tools[("Claude", "personal_free")] == 1
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    assert len(t["individuals"]) == 1 and t["individuals"][0]["data_entered"] == ["Health information"]


# ---- I1: only the CAICO approves tools; contributors and leads create only
def test_tool_edit_and_approval_rights(client, db, people, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, _user(db, "tom@abc.test"))
    assert client.patch(f"/api/v1/tools/{chatgpt['id']}", json={"account_type": "enterprise"}).status_code == 403
    assert client.post(f"/api/v1/clients/{cid}/tools", json={"vendor": "X", "product": "Y", "approval_status": "approved"}).json()["approval_status"] == "unreviewed"
    login_as(client, db, _user(db, "priya@abc.test"))
    assert client.patch(f"/api/v1/tools/{chatgpt['id']}", json={"approval_status": "approved"}).status_code == 403
    login_as(client, db, people["aud"])
    assert client.patch(f"/api/v1/tools/{chatgpt['id']}", json={"approval_status": "approved"}).status_code == 403
    assert client.patch(f"/api/v1/tools/{chatgpt['id']}", json={"training_on_inputs": "no"}).status_code == 200
    login_as(client, db, maria)
    assert client.patch(f"/api/v1/tools/{chatgpt['id']}", json={"approval_status": "not_approved"}).json()["approval_status"] == "not_approved"
    r = client.patch(f"/api/v1/tools/{chatgpt['id']}", json={"vendor": "Microsoft", "product": "Copilot", "account_type": "enterprise"})
    assert r.status_code == 409  # would duplicate the Copilot row


# ---- I2: attestation privacy outside the tracker
def test_aggregate_viewers_see_no_small_counts_or_free_text(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Finance"})
    fin = db.scalar(select(Department).where(Department.organization_id == cid, Department.name == "Finance"))
    token = _campaign(client, cid, [hr.id, fin.id])
    pub = _pub(client)
    for i, acct in enumerate(["company", "company", "personal_free"]):
        pub.post(f"/api/v1/public/attest/{token}", json={"respondent_name": f"P{i}", "department_id": hr.id, "uses_ai": True, "tools_declared": [{"tool": "claude" if acct == "personal_free" else "copilot", "account_type": acct}], "policy_acknowledged": True})
    pub.post(f"/api/v1/public/attest/{token}", json={"respondent_name": "F1", "department_id": fin.id, "uses_ai": True, "tools_declared": [{"tool": "other", "account_type": "personal_free", "name": "Bob's secret bot"}], "policy_acknowledged": True})
    log = db.scalars(select(AuditLog).where(AuditLog.action == "attestation.submit")).all()
    assert all(a.ip is None and a.actor_name == "Employee (self-declared)" and "F1" not in (a.summary or "") for a in log)
    # a lead of both departments
    priya = _user(db, "priya@abc.test")
    db.add(RoleAssignment(organization_id=cid, user_id=priya.id, role="dept_compliance_lead", scope_type="department", scope_id=fin.id))
    db.commit()
    login_as(client, db, priya)
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    assert {d["name"]: d["responses"] for d in t["departments"]} == {"Finance": "fewer than 3", "HR": 3}
    assert t["totals"]["responses"] == "hidden" and t["totals"]["personal_accounts"] == "fewer than 3"
    assert {"label": "Claude · personal, free", "count": "fewer than 3", "kind": "tool"} in t["tools"]
    tools = client.get(f"/api/v1/clients/{cid}/inventory").json()["tools"]
    assert all(x["declared_count"] is None for x in tools)
    assert not any("Bob" in x["product"] for x in tools)
    login_as(client, db, maria)
    assert any("Bob" in x["product"] and x["declared_count"] == 1 for x in client.get(f"/api/v1/clients/{cid}/inventory").json()["tools"])


# ---- I3 / I9: setup needs the confirmed list; scope is fixed after setup
def test_stage2_needs_confirmed_department_list(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "HR"})
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Priya", "last_name": "Shah", "email": "priya@abc.test", "department": "HR", "role": "dept_compliance_lead"})
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 2
    assert client.post(f"/api/v1/clients/{cid}/departments/confirm").status_code == 200
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 3
    assert db.scalar(select(Notification).where(Notification.kind == "departments_confirmed")) is not None
    r = client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Sales"})
    assert r.status_code == 409 and "fixed after setup" in r.json()["detail"]
    hr = db.scalar(select(Department).where(Department.organization_id == cid))
    assert client.patch(f"/api/v1/clients/{cid}/departments/{hr.id}", json={"in_scope": False}).status_code == 409


def test_adding_department_after_confirm_needs_reconfirm(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "HR"})
    client.post(f"/api/v1/clients/{cid}/departments/confirm")
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Finance"})
    from app.engagements.gates import gate_status

    db.expire_all()
    assert "The client has not confirmed the department list." in gate_status(db, db.get(Engagement, e.id)).unmet


# ---- I4: CSV robustness
def test_department_csv_whitespace_and_bad_files(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    csv = "department,head_name,head_email,headcount\nHuman Resources,,,3\nHuman  Resources,,,4\nFinance,,,5\n"
    r = client.post(f"/api/v1/clients/{cid}/departments/import", json={"csv_text": csv}).json()
    assert r["imported"] == 2 and r["errors"][0]["message"] == "Department 'Human  Resources' appears more than once in this file."
    pv = client.post(f"/api/v1/clients/{cid}/departments/import/preview", json={"csv_text": "department,head_name,head_email,headcount\n\"" + "x" * 200000 + "\",,,1\n"})
    assert pv.status_code == 200 and pv.json()["errors"][0]["field"] == "file"
    pv = client.post(f"/api/v1/clients/{cid}/departments/import/preview", json={"csv_text": "department,head_name,head_email,headcount\n" + "D" * 130 + ",,,1\n"}).json()
    assert pv["errors"][0]["message"] == "Department name must be 120 characters or fewer."


def test_user_import_errors_keep_row_numbers(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "HR"})
    from tests.factories import make_org, make_user

    make_user(db, make_org(db, name="Other Co"), name="Elsewhere", email="taken@other.test")
    db.commit()
    text = "first_name,last_name,email,job_title,department,role,location\nA,B,taken@other.test,,HR,Contributor,\n"
    out = client.post(f"/api/v1/clients/{cid}/users/import", json={"csv_text": text}).json()
    assert out["errors"] == [{"row": 2, "field": "email", "message": "This email can't be used. Check the address, or contact your Futran Chief Auditor."}]


# ---- I5: anyone who prepared a use case cannot approve it
def test_lead_who_edited_cannot_approve(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, _user(db, "tom@abc.test"))
    uc = _uc(client, cid, hr, [copilot["id"]], name="Notes")
    login_as(client, db, _user(db, "priya@abc.test"))
    body = {"name": "Notes rewritten", "department_id": hr.id, "tool_ids": [copilot["id"]], "data_categories": ["none"], "decision_impact": "none"}
    client.put(f"/api/v1/use-cases/{uc['id']}", json=body)
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    assert client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": True}).status_code == 403
    login_as(client, db, maria)
    assert client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": True}).status_code == 200


# ---- I6: raising the tier re-checks the named-user rules
def test_raise_tier_returns_when_people_lack_email_or_role(client, db, inv, people):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [copilot["id"]], name="Notes", named_users=[{"person_name": "No Email"}])
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/use-cases/{uc['id']}/final-tier", json={"tier": 3, "rationale": "Ranks people"})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    assert "work email" in r.json()["returned_comment"]


# ---- I7: role escalation
def test_no_self_grant_of_sign_off_roles(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Ann", "last_name": "Admin", "email": "ann@abc.test", "role": "client_admin"})
    ann = _user(db, "ann@abc.test")
    ann.status = "active"
    db.commit()
    login_as(client, db, ann)
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Ann", "last_name": "Admin", "email": "ann@abc.test", "role": "caico"})
    assert r.status_code == 403
    # granting a sign-off role to someone else tells the client's CAICO as well as Futran
    r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Dee", "last_name": "Po", "email": "dee@abc.test", "role": "dpo"})
    assert r.status_code == 200
    assert maria.id in {n.user_id for n in db.scalars(select(Notification).where(Notification.kind == "sign_off_role_changed"))}


def test_last_caico_counts_only_active_holders(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Old", "last_name": "Caico", "email": "old@abc.test", "role": "caico"})
    old = _user(db, "old@abc.test")
    old.status = "disabled"
    db.commit()
    ra = db.scalar(select(RoleAssignment).where(RoleAssignment.user_id == maria.id, RoleAssignment.role == "caico"))
    assert client.delete(f"/api/v1/clients/{cid}/users/{maria.id}/roles/{ra.id}").status_code == 409


# ---- I8: links die with the named user
def test_link_revoked_when_named_user_removed(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [chatgpt["id"]], name="Drafts", data_categories=["pii"], named_users=[{"person_name": "Wrong Person", "email": "wrong@other.test"}])
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    token = _link_token(db)
    login_as(client, db, _user(db, "priya@abc.test"))
    client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": False, "comment": "wrong email"})
    login_as(client, db, maria)
    body = {"name": "Drafts", "department_id": hr.id, "tool_ids": [chatgpt["id"]], "data_categories": ["pii"], "decision_impact": "none", "named_users": [{"person_name": "Right Person", "email": "right@abc.test"}]}
    client.put(f"/api/v1/use-cases/{uc['id']}", json=body)
    pub = _pub(client)
    assert pub.get(f"/api/v1/public/confirm/{token}").status_code == 404
    assert pub.post(f"/api/v1/public/confirm/{token}", json={"training_complete": True, "policy_acknowledged": True, "oversight_role_confirmed": True}).status_code == 404


# ---- I10: tiering follows spec §11 only
def test_unknown_training_terms_do_not_raise_the_tier(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    tool = client.post(f"/api/v1/clients/{cid}/tools", json={"vendor": "Acme", "product": "Notes", "account_type": "enterprise"}).json()
    assert tool["training_on_inputs"] == "unknown"
    assert _uc(client, cid, hr, [tool["id"]], name="N")["proposed_tier"] == 1


# ---- I11: forwarded client address when behind a trusted proxy
def test_rate_limit_uses_forwarded_address_when_trusted(client, db, inv, settings):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, maria)
    token = _campaign(client, cid, [hr.id])
    client.app.state.settings = settings.model_copy(update={"trust_proxy_headers": True})
    pub = _pub(client)
    body = {"respondent_name": "A", "department_id": hr.id, "uses_ai": False, "policy_acknowledged": True}
    for i in range(30):
        assert pub.post(f"/api/v1/public/attest/{token}", json=body, headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 200
    assert pub.post(f"/api/v1/public/attest/{token}", json=body, headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 429
    assert pub.post(f"/api/v1/public/attest/{token}", json=body, headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 200


# ---- minors
def test_odd_input_is_422_not_500(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, maria)
    token = _campaign(client, cid, [hr.id])
    c = _pub(client)
    c.cookies, c.headers = client.cookies, client.headers
    assert c.patch(f"/api/v1/clients/{cid}/departments/{hr.id}", json={"headcount": "abc"}).status_code == 422
    body = {"name": "N", "department_id": hr.id, "tool_ids": [copilot["id"]], "data_categories": ["none"], "decision_impact": "none", "usage": [{"role_name": "R", "headcount": "²"}]}
    assert c.post(f"/api/v1/clients/{cid}/use-cases", json=body).status_code == 200
    assert c.post(f"/api/v1/clients/{cid}/use-cases", json=body | {"usage": [], "tool_ids": [{"a": 1}]}).status_code == 422
    pub = _pub(client)
    base = {"respondent_name": "A", "department_id": hr.id, "uses_ai": True, "tools_declared": [{"tool": "chatgpt", "account_type": "company"}], "purposes": ["writing"], "data_entered": [], "policy_acknowledged": True}
    assert pub.post(f"/api/v1/public/attest/{token}", json=base | {"purposes": [["x"]]}).status_code == 200
    assert pub.post(f"/api/v1/public/attest/{token}", json=base | {"tools_declared": 5}).status_code == 422
    assert pub.post(f"/api/v1/public/attest/{token}", json=base | {"tools_declared": [{"tool": ["x"], "account_type": "company"}]}).status_code == 422


def test_no_new_campaign_after_discovery(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, maria)
    _campaign(client, cid, [hr.id])
    client.post(f"/api/v1/clients/{cid}/attestation/close")
    eng = db.get(Engagement, e.id)
    eng.stage = 4
    db.commit()
    r = client.post(f"/api/v1/clients/{cid}/attestation/campaigns", json={"department_ids": [hr.id], "closes_at": CLOSES})
    assert r.status_code == 409


def test_expired_link_says_so_before_answering(client, db, inv):
    cid, e, maria, hr, copilot, chatgpt = inv
    uc = _uc(client, cid, hr, [chatgpt["id"]], data_categories=["pii"], named_users=[{"person_name": "Lee Park", "email": "lee@abc.test"}])
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    token = _link_token(db)
    for link in db.scalars(select(NamedUserLink)):
        link.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert _pub(client).get(f"/api/v1/public/confirm/{token}").status_code == 410
