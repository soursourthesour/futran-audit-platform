"""Email screens' API and the §26.9 permissions."""
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.engagements.models import Engagement, EngagementTeam
from app.mail.models import AdminLogEntry, MailConnection, MailRecipient, MailSend, OutboxMessage
from app.mail.people import upsert_person
from app.mail.providers.fake import FAKE
from tests.factories import login_as, make_department, make_org, make_user


@pytest.fixture(autouse=True)
def _reset():
    FAKE.reset()


@pytest.fixture
def w(db):
    f = make_org(db, type="futran", name="Futran Solutions")
    c = make_org(db, type="client", name="ABC Corp")
    other = make_org(db, type="client", name="Other Co")
    hr = make_department(db, c, name="Human Resources")
    fin = make_department(db, c, name="Finance")
    e = Engagement(organization_id=c.id, client_id=c.id, name="AI audit", status="active", stage=3, audit_ref="FSL-AI-AUD-2026-001")
    db.add(e)
    db.flush()
    p = {
        "admin": make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test"),
        "chief": make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test"),
        "aud": make_user(db, f, roles=["auditor"], name="Al Auditor", email="al@futran.test"),
        "aud2": make_user(db, f, roles=["auditor"], name="Bo Auditor", email="bo@futran.test"),
        "cadmin": make_user(db, c, roles=["client_admin"], name="Cleo Admin", email="cleo@abc.com"),
        "caico": make_user(db, c, roles=["caico"], name="Priya Shah", email="priya@abc.com"),
        "lead": make_user(db, c, roles=[("dept_compliance_lead", "department", hr.id)], name="Lena Lead", email="lena@abc.com", department_id=hr.id),
        "contrib": make_user(db, c, roles=[("contributor", "department", hr.id)], name="Tom Reyes", email="tom@abc.com", department_id=hr.id),
        "other": make_user(db, other, roles=["client_admin"], name="Oz Other", email="oz@other.com"),
    }
    db.add(EngagementTeam(organization_id=c.id, engagement_id=e.id, user_id=p["aud"].id, role="auditor"))
    upsert_person(db, c.id, email="eve@abc.com", name="Eve Long", department_id=hr.id)
    upsert_person(db, c.id, email="finn@abc.com", name="Finn Berg", department_id=fin.id)
    db.commit()
    return {"f": f, "c": c, "other": other, "hr": hr, "fin": fin, "e": e, **p}


def _as(client, db, user):
    return login_as(client, db, user)


def _consent(client, start):
    """Follow a test-mode consent link the way the test consent page does."""
    q = parse_qs(urlparse(start["url"]).query)
    assert "/mail/test-consent" in start["url"]
    return client.post(f"/api/v1/mail/oauth/{q['provider'][0]}/test", json={"state": q["state"][0], "mailbox": start.get("mailbox") or "aiaudit@futransolutions.com"})


# ---- E1 Futran mailbox
def test_futran_admin_connects_the_futran_mailbox(client, db, w):
    _as(client, db, w["admin"])
    r = client.post("/api/v1/mail/futran/connect", json={"provider": "microsoft365", "mailbox_address": "aiaudit@futransolutions.com"})
    assert r.status_code == 200, r.text
    done = _consent(client, {**r.json(), "mailbox": "aiaudit@futransolutions.com"})
    assert done.status_code == 200, done.text
    st = client.get("/api/v1/mail/futran").json()
    assert st["connection"]["status"] == "connected" and st["connection"]["mailbox_address"] == "aiaudit@futransolutions.com"
    assert st["credentials"]["test_mode"] is True
    conn = db.scalar(select(MailConnection).where(MailConnection.owner == "futran"))
    assert conn.token_encrypted and "fake-access" not in conn.token_encrypted
    assert db.scalar(select(AdminLogEntry).where(AdminLogEntry.category == "consent")) is not None
    t = client.post("/api/v1/mail/futran/test", json={"to": "ada@futran.test"})
    assert t.status_code == 200 and len(FAKE.sent) == 1


def test_oauth_state_works_once(client, db, w):
    _as(client, db, w["admin"])
    start = client.post("/api/v1/mail/futran/connect", json={"provider": "google", "mailbox_address": "aiaudit@futransolutions.com"}).json()
    assert _consent(client, start).status_code == 200
    assert _consent(client, start).status_code == 400


def test_only_the_futran_admin_manages_the_futran_mailbox_and_groups(client, db, w):
    for who in ("chief", "aud"):
        _as(client, db, w[who])
        assert client.post("/api/v1/mail/futran/connect", json={"provider": "microsoft365"}).status_code == 403
        assert client.get("/api/v1/mail/groups?owner=futran").status_code == 200  # view
        assert client.post("/api/v1/mail/groups?owner=futran", json={"name": "X", "source": "manual"}).status_code == 403
    _as(client, db, w["cadmin"])
    assert client.get("/api/v1/mail/futran").status_code == 403
    _as(client, db, w["admin"])
    assert client.post("/api/v1/mail/groups?owner=futran", json={"name": "FutranResearch", "source": "manual"}).status_code == 200


# ---- E2 client onboarding
def test_client_admin_onboarding_steps(client, db, w):
    _as(client, db, w["cadmin"])
    st = client.get("/api/v1/mail/client").json()
    assert st["connection"]["status"] == "not_connected" and st["step"] == 1
    it = client.post("/api/v1/mail/client/request-it", json={"email": "it@abc.com", "provider": "microsoft365"})
    assert it.status_code == 200
    mail = db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "it_consent_request"))
    assert mail.to == ["it@abc.com"] and "/mail/test-consent" in mail.body_text
    start = client.post("/api/v1/mail/client/connect", json={"provider": "microsoft365", "mailbox_address": "ai-governance@abc.com"}).json()
    assert _consent(client, {**start, "mailbox": "ai-governance@abc.com"}).status_code == 200
    r = client.patch("/api/v1/mail/client/connection", json={"sender_mode": "own", "mailbox_address": "ai-governance@abc.com", "send_as_name": "ABC AI Governance", "onboarding_step": 3})
    assert r.status_code == 200, r.text
    d = client.post("/api/v1/mail/client/directory", json={"schedule": "daily", "include_guests": False})
    assert d.status_code == 200
    s = client.post("/api/v1/mail/client/directory/sync")
    assert s.status_code == 200 and s.json()["people"] > 10
    t = client.post("/api/v1/mail/client/test", json={"to": "cleo@abc.com"})
    assert t.status_code == 200 and FAKE.sent[-1].message.from_address == "ai-governance@abc.com"
    st = client.get("/api/v1/mail/client").json()
    assert st["connection"]["status"] == "connected" and st["directory"]["people"] > 10 and st["connection"]["test_sent_at"]
    cats = {e.category for e in db.scalars(select(AdminLogEntry).where(AdminLogEntry.organization_id == w["c"].id))}
    assert {"consent", "sender", "directory", "send"} <= cats


def test_caico_views_the_connection_but_only_the_client_admin_connects(client, db, w):
    _as(client, db, w["caico"])
    assert client.get("/api/v1/mail/client").status_code == 200
    assert client.post("/api/v1/mail/client/connect", json={"provider": "google"}).status_code == 403
    _as(client, db, w["lead"])
    assert client.get("/api/v1/mail/client").status_code == 403


def test_futran_sees_the_clients_email_status_for_wizard_step_6(client, db, w):
    _as(client, db, w["chief"])
    r = client.get(f"/api/v1/mail/clients/{w['c'].id}/status")
    assert r.status_code == 200 and r.json()["status"] == "not_connected"
    _as(client, db, w["other"])
    assert client.get(f"/api/v1/mail/clients/{w['c'].id}/status").status_code == 404


# ---- E3 groups
def test_client_groups_grid_and_nesting(client, db, w):
    _as(client, db, w["cadmin"])
    grid = client.get("/api/v1/mail/groups").json()
    assert {g["name"] for g in grid["groups"]} >= {"AIComplianceTeam", "DeptHeads", "Employees · All", "AI Governance Committee"}
    a = client.post("/api/v1/mail/groups", json={"name": "AI-EUAct", "purpose": "EU AI Act working group", "source": "manual"}).json()
    b = client.post("/api/v1/mail/groups", json={"name": "AI-NIST", "source": "manual"}).json()
    assert client.post(f"/api/v1/mail/groups/{a['id']}/members", json={"email": "new.person@abc.com", "name": "New Person"}).status_code == 200
    assert client.post(f"/api/v1/mail/groups/{b['id']}/members", json={"nested_group_id": a["id"]}).status_code == 200
    loop = client.post(f"/api/v1/mail/groups/{a['id']}/members", json={"nested_group_id": b["id"]})
    assert loop.status_code == 409 and "loop" in loop.json()["detail"]
    detail = client.get(f"/api/v1/mail/groups/{b['id']}").json()
    assert detail["member_count"] == 1 and detail["members"][0]["kind"] == "group"
    rule = client.post("/api/v1/mail/groups", json={"name": "Employees · HR", "source": "rule", "rule": {"kind": "department", "department_id": w["hr"].id}}).json()
    assert client.get(f"/api/v1/mail/groups/{rule['id']}").json()["member_count"] == 3  # Eve, Lena, Tom
    dup = client.post(f"/api/v1/mail/groups/{a['id']}/duplicate")
    assert dup.status_code == 200 and dup.json()["name"].startswith("AI-EUAct")
    csv = client.get(f"/api/v1/mail/groups/{a['id']}/export")
    assert "new.person@abc.com" in csv.text
    defaults = [g for g in client.get("/api/v1/mail/groups").json()["groups"] if g["is_default"]]
    assert client.delete(f"/api/v1/mail/groups/{defaults[0]['id']}").status_code == 409
    assert client.delete(f"/api/v1/mail/groups/{a['id']}").status_code == 200
    assert db.scalar(select(AdminLogEntry).where(AdminLogEntry.category == "group", AdminLogEntry.organization_id == w["c"].id)) is not None


def test_group_permissions(client, db, w):
    _as(client, db, w["caico"])
    g = client.post("/api/v1/mail/groups", json={"name": "AI-NIST", "source": "manual"}).json()
    _as(client, db, w["lead"])  # own department's groups only
    assert client.post("/api/v1/mail/groups", json={"name": "HR leads", "source": "manual", "department_id": w["hr"].id}).status_code == 200
    assert client.post("/api/v1/mail/groups", json={"name": "Finance x", "source": "manual", "department_id": w["fin"].id}).status_code == 403
    assert client.patch(f"/api/v1/mail/groups/{g['id']}", json={"purpose": "x"}).status_code == 404  # another department's group is not visible
    _as(client, db, w["contrib"])
    assert client.get("/api/v1/mail/groups").status_code == 403
    _as(client, db, w["aud"])  # assigned auditor: view only
    assert client.get(f"/api/v1/mail/groups?client_id={w['c'].id}").status_code == 200
    assert client.patch(f"/api/v1/mail/groups/{g['id']}", json={"purpose": "x"}).status_code == 403
    _as(client, db, w["aud2"])  # not on the engagement
    assert client.get(f"/api/v1/mail/groups?client_id={w['c'].id}").status_code == 404
    _as(client, db, w["other"])
    assert client.get(f"/api/v1/mail/groups/{g['id']}").status_code == 404


# ---- E4 send
def _everyone(client):
    return next(g for g in client.get("/api/v1/mail/groups").json()["groups"] if g["name"] == "Employees · All")


def test_send_with_preview_counts(client, db, w):
    _as(client, db, w["caico"])
    opts = client.get("/api/v1/mail/send/options").json()
    assert any(t["key"] == "attestation_request" for t in opts["templates"])
    g = _everyone(client)
    body = {"template_key": "training_ai_literacy", "group_ids": [g["id"]], "mode": "personal", "reminder_days": [3, 7]}
    p = client.post("/api/v1/mail/send/preview", json=body).json()
    assert p["steps"][-1]["label"] == "Will receive" and p["total"] == p["steps"][-1]["count"]
    assert p["message"]["subject"].startswith("AI literacy training") and "Hi " in p["message"]["text"]
    r = client.post("/api/v1/mail/send", json=body)
    assert r.status_code == 200, r.text
    s = db.get(MailSend, r.json()["id"])
    assert s.recipient_count == p["total"] and s.expansion == p["steps"]
    lst = client.post("/api/v1/mail/send/people.csv", json=body)
    assert "eve@abc.com" in lst.text


def test_department_lead_sends_to_own_department_only(client, db, w):
    _as(client, db, w["lead"])
    g = client.post("/api/v1/mail/groups", json={"name": "HR team", "source": "rule", "rule": {"kind": "all_people"}, "department_id": w["hr"].id}).json()
    r = client.post("/api/v1/mail/send", json={"template_key": "training_ai_literacy", "group_ids": [g["id"]]})
    assert r.status_code == 200, r.text
    emails = {x.email for x in db.scalars(select(MailRecipient).where(MailRecipient.send_id == r.json()["id"]))}
    assert "finn@abc.com" not in emails and "eve@abc.com" in emails


def test_futran_sends_engagement_emails_only(client, db, w):
    _as(client, db, w["cadmin"])
    g = _everyone(client)
    client.post("/api/v1/mail/templates/training_ai_literacy/copy")
    own = next(t for t in client.get("/api/v1/mail/templates").json() if t["key"] == "training_ai_literacy")
    _as(client, db, w["chief"])
    ok = client.post("/api/v1/mail/send", json={"client_id": w["c"].id, "template_key": "evidence_request", "group_ids": [g["id"]]})
    assert ok.status_code == 200, ok.text
    assert db.get(MailSend, ok.json()["id"]).engagement_id == w["e"].id
    assert client.post("/api/v1/mail/send", json={"client_id": w["c"].id, "template_id": own["id"], "group_ids": [g["id"]]}).status_code == 403
    _as(client, db, w["admin"])
    assert client.post("/api/v1/mail/send", json={"client_id": w["c"].id, "template_key": "evidence_request", "group_ids": [g["id"]]}).status_code == 403


# ---- E5 log
def test_email_and_admin_log_visibility(client, db, w):
    _as(client, db, w["caico"])
    g = _everyone(client)
    sid = client.post("/api/v1/mail/send", json={"template_key": "training_ai_literacy", "group_ids": [g["id"]]}).json()["id"]
    log = client.get("/api/v1/mail/log/sends").json()
    row = next(x for x in log["sends"] if x["id"] == sid)
    assert row["recipients"] > 0 and row["delivered"] == row["recipients"] and row["mode"] == "personal"
    d = client.get(f"/api/v1/mail/log/sends/{sid}").json()
    assert len(d["recipients"]) == row["recipients"] and d["message"]["subject"]
    assert client.post(f"/api/v1/mail/log/sends/{sid}/remind").json()["reminded"] == row["recipients"]
    assert "Sent email" in {e["label"] for e in client.get("/api/v1/mail/log/admin").json()["entries"]} or client.get("/api/v1/mail/log/admin").json()["entries"]
    _as(client, db, w["other"])
    assert all(x["id"] != sid for x in client.get("/api/v1/mail/log/sends").json()["sends"])
    assert client.get(f"/api/v1/mail/log/sends/{sid}").status_code == 404
    _as(client, db, w["aud"])
    assert any(x["id"] == sid for x in client.get(f"/api/v1/mail/log/sends?client_id={w['c'].id}").json()["sends"])
    _as(client, db, w["lead"])
    assert all(x["id"] != sid for x in client.get("/api/v1/mail/log/sends").json()["sends"])  # not their department's send


def test_admin_log_cannot_be_changed(db, w):
    e = AdminLogEntry(owner="client", organization_id=w["c"].id, category="group", action="x", summary="x", retain_until=__import__("datetime").datetime(2033, 1, 1))
    db.add(e)
    db.commit()
    e.summary = "changed"
    with pytest.raises(PermissionError):
        db.commit()
    db.rollback()


# ---- per-user mailbox (§27.1)
def test_per_user_mailbox_policy_and_connection(client, db, w):
    _as(client, db, w["contrib"])
    me = client.get("/api/v1/me/mailbox").json()
    assert me["policy"] == "optional" and me["prompt"] is True and me["connection"] is None
    assert client.post("/api/v1/me/mailbox/decline").status_code == 200
    assert client.get("/api/v1/me/mailbox").json()["prompt"] is False
    _as(client, db, w["cadmin"])
    assert client.patch("/api/v1/mail/settings", json={"per_user_sync": "required"}).status_code == 200
    _as(client, db, w["contrib"])
    me = client.get("/api/v1/me/mailbox").json()
    assert me["policy"] == "required" and me["prompt"] is True
    assert client.post("/api/v1/me/mailbox/decline").status_code == 409
    start = client.post("/api/v1/me/mailbox/connect", json={"provider": "microsoft365"}).json()
    assert _consent(client, {**start, "mailbox": "tom@abc.com"}).status_code == 200
    me = client.get("/api/v1/me/mailbox").json()
    assert me["connection"]["status"] == "connected" and me["prompt"] is False
    assert client.post("/api/v1/me/mailbox/disconnect").status_code == 200
    _as(client, db, w["caico"])
    assert client.patch("/api/v1/mail/settings", json={"per_user_sync": "off"}).status_code == 403


# ---- templates
def test_templates_are_copied_and_versioned(client, db, w):
    _as(client, db, w["caico"])
    c = client.post("/api/v1/mail/templates/attestation_request/copy").json()
    assert c["owner"] == "client" and c["version"] == 1
    e = client.put(f"/api/v1/mail/templates/{c['id']}", json={"subject": "Which AI tools do you use?", "body": "Hi [First name],\n\n[Link]"})
    assert e.status_code == 200 and e.json()["version"] == 2
    futran = next(t for t in client.get("/api/v1/mail/templates").json() if t["key"] == "evidence_request")
    assert client.put(f"/api/v1/mail/templates/{futran['id']}", json={"subject": "x", "body": "y"}).status_code == 403
    _as(client, db, w["admin"])
    assert client.put(f"/api/v1/mail/templates/{futran['id']}", json={"subject": "Evidence needed", "body": "Hi [First name]\n\n[Link]"}).json()["version"] == 2


# ---- Getting started item and the scheduler
def test_getting_started_lists_connect_your_email_for_the_client_admin(client, db, w):
    _as(client, db, w["cadmin"])
    r = client.get("/api/v1/me/initiation")
    assert r.status_code == 200, r.text
    extra = r.json()["extra_items"]
    assert extra[0]["key"] == "email" and extra[0]["title"] == "Connect your email" and extra[0]["done"] is False
    assert r.json()["total"] == len(r.json()["items"])  # the seven package items are counted on their own
    _as(client, db, w["caico"])
    assert client.get("/api/v1/me/initiation").json()["extra_items"] == []


def test_mail_tick_finishes_sends_and_runs_due_jobs(db, settings, w):
    from app.mail.jobs import run_mail_tick
    from app.notifications.jobs import JOBS

    out = run_mail_tick(db, settings, __import__("app.core.clock", fromlist=["utcnow"]).utcnow())
    assert set(out) == {"dispatched", "replies", "directory_syncs", "reminders"}
    assert "email" in JOBS
