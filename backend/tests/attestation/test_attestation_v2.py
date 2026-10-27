"""Attestation changes of 27 October: agents in question 2, "Something else" text in question 3, the editable
individual answers grid, and the in-app attestation for client users with a login."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.attestation.models import Attestation, AttestationAssignment
from app.audit_log.models import AuditLog
from app.core.clock import utcnow
from app.inventory.models import AITool
from app.mail.models import OutboxMessage
from app.notifications.models import Notification
from app.policy.actions import Action as A
from app.policy.matrix import MATRIX, Scope as S
from app.policy.roles import Role as R
from app.tenancy.models import Department, User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401

CLOSES = (utcnow() + timedelta(days=10)).isoformat()


def _user(db, email):
    return db.scalar(select(User).where(User.email == email))


@pytest.fixture
def world(client, db, live):
    """ABC Corp with HR (lead Priya, contributor Tom, IT director Ian as a contributor) and Finance; DPO Dana;
    Sam is Client Admin only; Olga is invited but has not accepted. Notice acknowledged."""
    cid, e, maria = live
    login_as(client, db, maria)
    for d in ("HR", "Finance"):
        client.post(f"/api/v1/clients/{cid}/departments", json={"name": d})
    users = [("Priya", "Shah", "priya@abc.test", "HR", "dept_compliance_lead"), ("Tom", "Reyes", "tom@abc.test", "HR", "contributor"),
             ("Ian", "Doyle", "ian@abc.test", "Finance", "contributor"), ("Dana", "Pohl", "dana@abc.test", "", "dpo"),
             ("Sam", "Admin", "sam@abc.test", "", "client_admin"), ("Olga", "New", "olga@abc.test", "HR", "contributor")]
    for first, last, email, dept, role in users:
        r = client.post(f"/api/v1/clients/{cid}/users", json={"first_name": first, "last_name": last, "email": email, "job_title": "IT Director" if first == "Ian" else "", "department": dept, "role": role})
        assert r.status_code == 200, r.text
    for u in db.scalars(select(User).where(User.organization_id == cid)):
        if u.email != "olga@abc.test":
            u.status = "active"
    db.commit()
    depts = {d.name: d.id for d in db.scalars(select(Department).where(Department.organization_id == cid))}
    assert client.post("/api/v1/me/initiation/items/notice/done").status_code == 200
    r = client.post(f"/api/v1/clients/{cid}/attestation/campaigns", json={"department_ids": list(depts.values()), "closes_at": CLOSES, "policy_version": "1.0"})
    assert r.status_code == 200, r.text
    token = r.json()["link"].rsplit("/", 1)[1]
    return cid, e, maria, depts, token


def _pub(client):
    return client.__class__(client.app, raise_server_exceptions=False)


def _answer(dept_id, name="Sam Staff", email=None, tools=None, **kw):
    return {
        "respondent_name": name, "respondent_email": email, "department_id": dept_id, "uses_ai": True,
        "tools_declared": tools or [{"tool": "chatgpt", "account_type": "personal_free"}],
        "purposes": ["writing"], "data_entered": ["client"], "policy_acknowledged": True,
    } | kw


# ---- 1. question 2 lists agents as well as tools
def test_public_form_offers_agents(client, db, world):
    cid, e, maria, depts, token = world
    body = _pub(client).get(f"/api/v1/public/attest/{token}").json()
    kinds = {t["value"]: t["kind"] for t in body["tools"]}
    assert kinds["chatgpt"] == "tool" and kinds["other"] == "tool"
    agents = [t["value"] for t in body["tools"] if t["kind"] == "agent"]
    for v in ("copilot_agents", "chatgpt_agent", "claude_agentic", "gemini_agents", "agentforce", "servicenow_agents", "automations", "github_coding_agent", "in_house_agent", "other_agent"):
        assert v in agents
    named = {t["value"] for t in body["tools"] if t.get("needs_name")}
    assert {"other", "in_house_agent", "other_agent"} <= named


def test_agents_are_stored_counted_and_reach_the_inventory_as_agents(client, db, world):
    cid, e, maria, depts, token = world
    pub = _pub(client)
    tools = [{"tool": "agentforce", "account_type": "company"}, {"tool": "other_agent", "account_type": "personal_paid", "name": "Invoice chaser"}, {"tool": "copilot", "account_type": "company"}]
    assert pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], email="a@abc.test", tools=tools)).status_code == 200
    rows = {(t.vendor, t.product): t for t in db.scalars(select(AITool).where(AITool.organization_id == cid))}
    assert rows[("Salesforce", "Agentforce")].kind == "agent" and rows[("Salesforce", "Agentforce")].declared_count == 1
    assert rows[("Other", "Invoice chaser")].kind == "agent"
    assert rows[("Microsoft", "Copilot")].kind == "tool"
    login_as(client, db, maria)
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    by_label = {x["label"]: x["kind"] for x in t["tools"]}
    assert by_label["Salesforce Agentforce · company account"] == "agent"
    assert by_label["Invoice chaser · personal, paid"] == "agent"
    assert by_label["Microsoft Copilot · company account"] == "tool"
    inv = client.get(f"/api/v1/clients/{cid}/inventory").json()
    assert {x["product"]: x["kind"] for x in inv["tools"]}["Agentforce"] == "agent"


def test_other_tool_and_agent_need_a_name(client, db, world):
    cid, e, maria, depts, token = world
    pub = _pub(client)
    for tool in ("other", "other_agent", "in_house_agent"):
        r = pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], tools=[{"tool": tool, "account_type": "company"}]))
        assert r.status_code == 422, tool
        assert r.json()["errors"][0]["field"] == "tools_declared"


# ---- 2. question 3 "Something else" needs the detail
def test_something_else_needs_text_and_is_shown(client, db, world):
    cid, e, maria, depts, token = world
    pub = _pub(client)
    r = pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], purposes=["writing", "other"]))
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "purpose_other"
    r = pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], email="x@abc.test", purposes=["other"], purpose_other="  Translating   supplier contracts " + "x" * 300))
    assert r.status_code == 200, r.text
    a = db.scalar(select(Attestation).where(Attestation.respondent_email == "x@abc.test"))
    assert a.purpose_other.startswith("Translating supplier contracts") and len(a.purpose_other) == 200
    # the text is dropped when "Something else" is not ticked
    pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], email="y@abc.test", purposes=["writing"], purpose_other="ignored"))
    assert db.scalar(select(Attestation).where(Attestation.respondent_email == "y@abc.test")).purpose_other is None
    login_as(client, db, maria)
    ind = {i["email"]: i for i in client.get(f"/api/v1/clients/{cid}/attestation").json()["individuals"]}
    assert ind["x@abc.test"]["purposes"] == ["Something else: " + a.purpose_other]
    assert ind["x@abc.test"]["purpose_other"] == a.purpose_other


def test_answers_saved_before_the_change_still_load_and_count(client, db, world):
    cid, e, maria, depts, token = world
    from app.attestation.models import AttestationCampaign

    c = db.scalar(select(AttestationCampaign))
    old = Attestation(organization_id=cid, campaign_id=c.id, engagement_id=c.engagement_id, respondent_name="Old Answer", respondent_email=None, department_id=depts["HR"], uses_ai=True,
                      tools_declared=[{"tool": "other", "account_type": "personal_free", "name": None}, {"tool": "in_app", "account_type": "company"}], purposes=["other"], data_entered=["none"],
                      policy_acknowledged=True, submitted_at=utcnow())
    db.add(old)
    db.commit()
    login_as(client, db, maria)
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    assert t["totals"]["responses"] == 1
    row = t["individuals"][0]
    assert row["purposes"] == ["Something else"] and row["status"] == "new" and row["source"] == "link"
    assert row["tools"] == ["Another AI tool · personal, free", "AI inside another app (for example an ATS or CRM) · company account"]


# ---- 3. individual answers: review, edit, remove, export
def _three(client, db, world):
    cid, e, maria, depts, token = world
    pub = _pub(client)
    for i, (dept, email) in enumerate([("HR", "h1@abc.test"), ("HR", "h2@abc.test"), ("Finance", "f1@abc.test")]):
        pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts[dept], name=f"=Person {i}", email=email, purposes=["other"], purpose_other="Board packs"))
    return {a.respondent_email: a.id for a in db.scalars(select(Attestation))}


def test_caico_marks_reviewed_and_exports_selected_rows(client, db, world):
    cid, e, maria, depts, token = world
    ids = _three(client, db, world)
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/attestation/answers/review", json={"ids": [ids["h1@abc.test"], ids["h2@abc.test"]]})
    assert r.status_code == 200 and r.json() == {"reviewed": 2}
    ind = {i["email"]: i for i in client.get(f"/api/v1/clients/{cid}/attestation").json()["individuals"]}
    assert ind["h1@abc.test"]["status"] == "reviewed" and ind["h1@abc.test"]["reviewed_by"] == "Maria Lopez"
    assert ind["f1@abc.test"]["status"] == "new"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "attestation.review")) is not None
    r = client.post(f"/api/v1/clients/{cid}/attestation/answers/export", json={"ids": [ids["h1@abc.test"], ids["f1@abc.test"]]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert len(lines) == 3 and lines[0].startswith("Name,Email,Department")
    assert "'=Person 0" in r.text  # spreadsheet formulas neutralised
    assert "h2@abc.test" not in r.text
    assert db.scalar(select(AuditLog).where(AuditLog.action == "attestation.export")) is not None


def test_remove_needs_a_reason_and_drops_the_row_from_totals(client, db, world):
    cid, e, maria, depts, token = world
    ids = _three(client, db, world)
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/attestation/answers/remove", json={"ids": [ids["h2@abc.test"]], "reason": " "})
    assert r.status_code == 422
    r = client.post(f"/api/v1/clients/{cid}/attestation/answers/remove", json={"ids": [ids["h2@abc.test"]], "reason": "Duplicate of h1, sent twice by mistake"})
    assert r.status_code == 200 and r.json() == {"removed": 1}
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    assert t["totals"]["responses"] == 2 and {i["email"] for i in t["individuals"]} == {"h1@abc.test", "f1@abc.test"}
    assert {d["name"]: d["responses"] for d in t["departments"]}["HR"] == "fewer than 3"  # the department rule is unchanged
    a = db.get(Attestation, ids["h2@abc.test"])
    assert a.deleted_at is not None and a.removed_reason == "Duplicate of h1, sent twice by mistake"  # soft delete; the row is kept
    tool = db.scalar(select(AITool).where(AITool.organization_id == cid, AITool.product == "ChatGPT", AITool.account_type == "personal_free"))
    assert tool.declared_count == 2
    log = db.scalar(select(AuditLog).where(AuditLog.action == "attestation.remove"))
    assert log is not None and "Duplicate" in (log.after or {}).get("reason", "")


def test_edit_records_before_and_after_and_keeps_tool_answers(client, db, world):
    cid, e, maria, depts, token = world
    ids = _three(client, db, world)
    pub = _pub(client)
    pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], name="Oz", email="oz@abc.test", tools=[{"tool": "other", "account_type": "personal_free", "name": "Chatgtp"}]))
    oz = db.scalar(select(Attestation).where(Attestation.respondent_email == "oz@abc.test"))
    dana = _user(db, "dana@abc.test")
    login_as(client, db, dana)  # the DPO may edit
    r = client.patch(f"/api/v1/clients/{cid}/attestation/answers/{oz.id}", json={"department_id": depts["Finance"], "respondent_name": "Oz Kaya", "tool_names": {"0": "ChatGPT"},
                                                                                 "reviewer_note": "Department confirmed with HR", "tools_declared": [], "uses_ai": False})
    assert r.status_code == 200, r.text
    db.expire_all()
    oz = db.get(Attestation, oz.id)
    assert oz.department_id == depts["Finance"] and oz.respondent_name == "Oz Kaya" and oz.reviewer_note == "Department confirmed with HR"
    assert oz.uses_ai is True and oz.tools_declared == [{"tool": "other", "account_type": "personal_free", "name": "ChatGPT"}]  # only the typed name changed
    assert oz.edited_by == dana.id and oz.edited_at is not None
    log = db.scalar(select(AuditLog).where(AuditLog.action == "attestation.edit"))
    assert log.before["department"] == "HR" and log.after["department"] == "Finance"
    assert log.before["tool_names"] == ["Chatgtp"] and log.after["tool_names"] == ["ChatGPT"]
    row = {i["id"]: i for i in client.get(f"/api/v1/clients/{cid}/attestation").json()["individuals"]}[oz.id]
    assert row["edited_by"] == "Dana Pohl" and row["edited_at"] and row["reviewer_note"] == "Department confirmed with HR"
    # the department must be one in the campaign
    assert client.patch(f"/api/v1/clients/{cid}/attestation/answers/{oz.id}", json={"department_id": "nope"}).status_code == 422
    # the full answer is available row by row
    full = client.get(f"/api/v1/clients/{cid}/attestation/answers/{oz.id}").json()
    assert full["name"] == "Oz Kaya" and full["policy_acknowledged"] is True


def test_who_may_manage_individual_answers(client, db, people, world):
    cid, e, maria, depts, token = world
    ids = _three(client, db, world)
    one = ids["h1@abc.test"]
    for email in ("priya@abc.test", "tom@abc.test", "sam@abc.test"):
        login_as(client, db, _user(db, email))
        assert client.post(f"/api/v1/clients/{cid}/attestation/answers/review", json={"ids": [one]}).status_code == 403, email
        assert client.post(f"/api/v1/clients/{cid}/attestation/answers/remove", json={"ids": [one], "reason": "x"}).status_code == 403, email
        assert client.patch(f"/api/v1/clients/{cid}/attestation/answers/{one}", json={"reviewer_note": "x"}).status_code == 403, email
        assert client.post(f"/api/v1/clients/{cid}/attestation/answers/export", json={"ids": [one]}).status_code == 403, email
        assert client.get(f"/api/v1/clients/{cid}/attestation/answers/{one}").status_code == 403, email
    # the department lead still gets totals only
    login_as(client, db, _user(db, "priya@abc.test"))
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    assert t["individuals"] is None and t["in_app"] is None
    assert {d["name"]: d["responses"] for d in t["departments"]} == {"HR": "fewer than 3"}
    # a Futran auditor can read and export, not change
    from app.engagements.models import EngagementTeam

    assert db.scalar(select(EngagementTeam).where(EngagementTeam.engagement_id == e.id, EngagementTeam.user_id == people["aud"].id)) is not None
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/clients/{cid}/attestation/answers/export", json={"ids": [one]}).status_code == 200
    assert client.post(f"/api/v1/clients/{cid}/attestation/answers/review", json={"ids": [one]}).status_code == 403


def test_answer_ids_from_another_campaign_are_ignored(client, db, world):
    cid, e, maria, depts, token = world
    ids = _three(client, db, world)
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/attestation/answers/review", json={"ids": [ids["h1@abc.test"], "not-an-id"]})
    assert r.json() == {"reviewed": 1}
    assert client.patch(f"/api/v1/clients/{cid}/attestation/answers/not-an-id", json={"reviewer_note": "x"}).status_code == 404


# ---- 4. in-app attestation for users with a login
def test_matrix_rows_for_the_new_permissions():
    for role in (R.CAICO, R.CLIENT_ADMIN):
        assert MATRIX[role].get(A.SEND_ATTESTATION) == S.ORG
    for role in (R.DPO, R.DEPT_COMPLIANCE_LEAD, R.CONTRIBUTOR, R.EXEC_SPONSOR, R.AUDITOR, R.CHIEF_AUDITOR):
        assert MATRIX.get(role, {}).get(A.SEND_ATTESTATION, S.NONE) == S.NONE
    for role in (R.CAICO, R.CLIENT_ADMIN, R.DPO, R.DEPT_COMPLIANCE_LEAD, R.CONTRIBUTOR, R.EXEC_SPONSOR):
        assert MATRIX[role].get(A.COMPLETE_OWN_ATTESTATION) == S.ORG
    for role in (R.AUDITOR, R.CHIEF_AUDITOR, R.ADMIN):
        assert MATRIX.get(role, {}).get(A.COMPLETE_OWN_ATTESTATION, S.NONE) == S.NONE
    assert MATRIX[R.CAICO].get(A.MANAGE_ATTESTATION_ANSWERS) == S.ORG and MATRIX[R.DPO].get(A.MANAGE_ATTESTATION_ANSWERS) == S.ORG
    for role in (R.CLIENT_ADMIN, R.DEPT_COMPLIANCE_LEAD, R.CONTRIBUTOR, R.EXEC_SPONSOR, R.AUDITOR, R.CHIEF_AUDITOR):
        assert MATRIX.get(role, {}).get(A.MANAGE_ATTESTATION_ANSWERS, S.NONE) == S.NONE


def test_no_line_item_before_it_is_sent(client, db, world):
    cid, e, maria, depts, token = world
    login_as(client, db, _user(db, "tom@abc.test"))
    r = client.get("/api/v1/me/attestation")
    assert r.status_code == 200 and r.json()["line_item"] is None


def test_send_creates_line_items_for_active_users_and_notifies_them(client, db, world):
    cid, e, maria, depts, token = world
    login_as(client, db, _user(db, "tom@abc.test"))
    assert client.post(f"/api/v1/clients/{cid}/attestation/send").status_code == 403
    login_as(client, db, _user(db, "priya@abc.test"))
    assert client.post(f"/api/v1/clients/{cid}/attestation/send").status_code == 403
    login_as(client, db, _user(db, "sam@abc.test"))  # Client Admin only
    r = client.post(f"/api/v1/clients/{cid}/attestation/send")
    assert r.status_code == 200, r.text
    active = {u.email for u in db.scalars(select(User).where(User.organization_id == cid, User.status == "active", User.deleted_at.is_(None)))}
    assert "olga@abc.test" not in active and r.json()["sent"] == len(active)
    got = {db.get(User, a.user_id).email for a in db.scalars(select(AttestationAssignment))}
    assert got == active
    notes = {db.get(User, n.user_id).email for n in db.scalars(select(Notification).where(Notification.kind == "attestation_sent"))}
    assert notes == active
    mails = list(db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "attestation_sent")))
    assert {m.to[0] for m in mails} == active and "/my-attestation" in mails[0].body_text
    assert db.scalar(select(AuditLog).where(AuditLog.action == "attestation.send")) is not None
    # sending again reaches nobody new and tells nobody twice
    again = client.post(f"/api/v1/clients/{cid}/attestation/send").json()
    assert again["sent"] == 0 and again["total"] == len(active)
    assert db.query(Notification).filter(Notification.kind == "attestation_sent").count() == len(active)
    # the Client Admin sees counts only
    s = client.get(f"/api/v1/clients/{cid}/attestation/in-app").json()
    assert s["assigned"] == len(active) and s["submitted"] == 0 and "outstanding" not in s


def test_send_needs_an_open_campaign(client, db, world):
    cid, e, maria, depts, token = world
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/close")
    r = client.post(f"/api/v1/clients/{cid}/attestation/send")
    assert r.status_code == 409


def test_contributor_completes_own_attestation_in_app(client, db, world):
    cid, e, maria, depts, token = world
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/send")
    ian = _user(db, "ian@abc.test")  # an IT Director with only the Contributor role
    login_as(client, db, ian)
    me = client.get("/api/v1/me/attestation").json()
    assert me["line_item"]["status"] == "to_do"
    assert me["prefill"] == {"respondent_name": "Ian Doyle", "respondent_email": "ian@abc.test", "department_id": depts["Finance"]}
    assert any(t["kind"] == "agent" for t in me["form"]["tools"])
    # the tracker stays closed to him
    assert client.get(f"/api/v1/clients/{cid}/attestation").status_code == 403
    body = _answer(depts["HR"], name="Someone Else", email="spoof@abc.test", tools=[{"tool": "github_coding_agent", "account_type": "company"}])
    r = client.post("/api/v1/me/attestation", json=body)
    assert r.status_code == 200, r.text
    a = db.scalar(select(Attestation).where(Attestation.user_id == ian.id))
    assert a.respondent_name == "Ian Doyle" and a.respondent_email == "ian@abc.test" and a.department_id == depts["Finance"] and a.source == "in_app"
    me = client.get("/api/v1/me/attestation").json()
    assert me["line_item"]["status"] == "submitted" and me["line_item"]["submitted_at"]
    assert client.post("/api/v1/me/attestation", json=body).status_code == 409  # not twice
    # the CAICO sees who is still to do it
    login_as(client, db, maria)
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    out = {o["email"] for o in t["in_app"]["outstanding"]}
    assert "ian@abc.test" not in out and "tom@abc.test" in out
    assert t["in_app"]["submitted"] == 1 and t["totals"]["responses"] == 1
    assert t["individuals"][0]["source"] == "in_app"


def test_user_without_department_chooses_one(client, db, world):
    cid, e, maria, depts, token = world
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/send")
    dana = _user(db, "dana@abc.test")
    login_as(client, db, dana)
    assert client.get("/api/v1/me/attestation").json()["prefill"]["department_id"] is None
    r = client.post("/api/v1/me/attestation", json=_answer("nope"))
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "department_id"
    assert client.post("/api/v1/me/attestation", json=_answer(depts["HR"])).status_code == 200


def test_public_link_and_in_app_answers_are_not_double_counted(client, db, world):
    cid, e, maria, depts, token = world
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/send")
    # Tom answered through the staff link with his work email first
    _pub(client).post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], name="Tom R", email="TOM@abc.test"))
    tom = _user(db, "tom@abc.test")
    login_as(client, db, tom)
    me = client.get("/api/v1/me/attestation").json()
    assert me["line_item"]["status"] == "submitted" and me["line_item"]["via"] == "link"
    assert client.post("/api/v1/me/attestation", json=_answer(depts["HR"])).status_code == 409
    # Ian answers in the app first, then through the link with the same email: one current answer
    ian = _user(db, "ian@abc.test")
    login_as(client, db, ian)
    client.post("/api/v1/me/attestation", json=_answer(depts["Finance"]))
    _pub(client).post(f"/api/v1/public/attest/{token}", json=_answer(depts["Finance"], name="Ian D", email="ian@abc.test", tools=[{"tool": "claude", "account_type": "company"}]))
    current = [a for a in db.scalars(select(Attestation).where(Attestation.superseded_by_id.is_(None), Attestation.deleted_at.is_(None)))]
    assert len(current) == 2
    assert {a.user_id for a in current} == {tom.id, ian.id}  # the link answers are tied to the matching login
    login_as(client, db, maria)
    t = client.get(f"/api/v1/clients/{cid}/attestation").json()
    assert t["totals"]["responses"] == 2 and t["in_app"]["submitted"] == 2


def test_user_who_accepts_later_gets_the_line_item(client, db, settings, world):
    cid, e, maria, depts, token = world
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/send")
    from app.invitations.service import accept_invitation, invite_user

    olga = _user(db, "olga@abc.test")
    inv = invite_user(db, settings, maria, olga)
    accept_invitation(db, settings, inv.raw_token, "A-much-Longer-pass-2026!")
    db.commit()
    assert db.scalar(select(AttestationAssignment).where(AttestationAssignment.user_id == olga.id)) is not None
    assert db.scalar(select(Notification).where(Notification.user_id == olga.id, Notification.kind == "attestation_sent")) is not None
    login_as(client, db, olga)
    assert client.get("/api/v1/me/attestation").json()["line_item"]["status"] == "to_do"


def test_no_line_item_after_the_campaign_closes(client, db, world):
    cid, e, maria, depts, token = world
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/send")
    client.post(f"/api/v1/clients/{cid}/attestation/close")
    login_as(client, db, _user(db, "tom@abc.test"))
    me = client.get("/api/v1/me/attestation").json()
    assert me["line_item"]["status"] == "closed"
    assert client.post("/api/v1/me/attestation", json=_answer(depts["HR"])).status_code == 410


def test_futran_staff_have_no_own_attestation(client, db, people, world):
    login_as(client, db, people["aud"])
    assert client.get("/api/v1/me/attestation").status_code == 403


def test_report_counts_current_answers_only(client, db, world):
    from app.engagements.models import Engagement
    from app.reports.context import scope_facts

    cid, e, maria, depts, token = world
    ids = _three(client, db, world)
    pub = _pub(client)
    pub.post(f"/api/v1/public/attest/{token}", json=_answer(depts["HR"], email="h1@abc.test"))  # replaces h1's answer
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/attestation/answers/remove", json={"ids": [ids["f1@abc.test"]], "reason": "Test answer"})
    assert scope_facts(db, db.get(Engagement, e.id), [])["attestations"] == 2
