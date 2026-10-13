"""Regression tests for the Phase 1 review findings (C1, C2, I1–I7, M1–M6)."""
import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from app.audit_log import service as audit
from app.audit_log.models import AuditLog
from app.core.errors import Conflict, Forbidden, NotFound
from app.engagements.models import Engagement, EngagementTeam
from app.invitations.service import accept_invitation, invite_user
from app.mail.models import OutboxMessage
from app.main import create_app
from app.policy.actions import Action as A
from app.policy.authorize import authorize, get_scoped
from tests.factories import login_as, make_department, make_org, make_user
from tests.policy.test_sod import actor_for

PW = "Correct-Horse-2026"


# C1 — invitation tokens never stored readable outside test mode
def test_smtp_mode_outbox_redacts_invitation_link(db, settings, monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, m): sent.append(m)

    monkeypatch.setattr("app.mail.service.smtplib.SMTP", FakeSMTP)
    s = settings.model_copy(update={"email_mode": "smtp", "smtp_host": "smtp.test"})
    org = make_org(db, type="client")
    u = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com")
    inv = invite_user(db, s, None, u)
    msg = db.query(OutboxMessage).one()
    assert "/invite/" not in msg.body_html and "/invite/" not in msg.body_text
    assert "/invite/" in sent[0].get_body(("plain",)).get_content()
    assert inv.raw_token  # available to the caller (CLI), never persisted


# C2 — TOTP brute force is cut off
def test_mfa_verify_locks_after_5_failures(settings, engine, db):
    app = create_app(settings.model_copy(update={"mfa_required": True}), engine=engine)
    org = make_org(db, type="client")
    make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com", password=PW)
    db.commit()
    with TestClient(app) as c:
        body = c.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW}).json()
        h = {"X-CSRF-Token": body["csrf_token"]}
        c.post("/api/v1/auth/mfa/enroll", headers=h)
        codes = [c.post("/api/v1/auth/mfa/verify", json={"code": "000000"}, headers=h).status_code for _ in range(6)]
        assert codes[:4] == [401] * 4
        assert 429 in codes[4:]
        assert c.get("/api/v1/auth/session").json()["authenticated"] is False


# M1 — a TOTP code cannot be replayed
def test_totp_code_cannot_be_replayed(settings, engine, db):
    app = create_app(settings.model_copy(update={"mfa_required": True}), engine=engine)
    org = make_org(db, type="client")
    make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com", password=PW)
    db.commit()
    with TestClient(app) as c:
        body = c.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW}).json()
        h = {"X-CSRF-Token": body["csrf_token"]}
        secret = c.post("/api/v1/auth/mfa/enroll", headers=h).json()["secret"]
        code = pyotp.TOTP(secret).now()
        assert c.post("/api/v1/auth/mfa/verify", json={"code": code}, headers=h).status_code == 200
        c.post("/api/v1/auth/logout", headers=h)
        body2 = c.post("/api/v1/auth/login", json={"email": "priya@abc.com", "password": PW}).json()
        h2 = {"X-CSRF-Token": body2["csrf_token"]}
        assert c.post("/api/v1/auth/mfa/verify", json={"code": code}, headers=h2).status_code == 401


@pytest.fixture
def two_depts(db):
    abc = make_org(db, type="client", name="ABC Corp")
    hr = make_department(db, abc, name="Human Resources")
    fin = make_department(db, abc, name="Finance")
    eng = Engagement(organization_id=abc.id, client_id=abc.id, name="E")
    db.add(eng)
    db.flush()
    u = make_user(db, abc, roles=[("dept_compliance_lead", "department", hr.id), ("contributor", "department", fin.id)], name="Two Hats", email="two@abc.test")
    return abc, hr, fin, eng, u


# I1 — a department scope from one role does not lend another role's rights
def test_dept_scope_is_per_role(db, two_depts):
    abc, hr, fin, eng, u = two_depts
    a = actor_for(db, u)
    authorize(db, a, A.APPROVE_USE_CASE, engagement_id=eng.id, department_id=hr.id)
    authorize(db, a, A.SUBMIT_USE_CASE, engagement_id=eng.id, department_id=fin.id)
    with pytest.raises(Forbidden):
        authorize(db, a, A.APPROVE_USE_CASE, engagement_id=eng.id, department_id=fin.id)


# I2 — Futran ASSIGNED scope checks the org when no engagement is given
def test_unassigned_auditor_cannot_reach_other_client_org(db):
    f = make_org(db, type="futran")
    abc = make_org(db, type="client", name="ABC Corp")
    aud = make_user(db, f, roles=["auditor"], name="Aud", email="aud@f.test")
    with pytest.raises(NotFound):
        authorize(db, actor_for(db, aud), A.VIEW_CLIENT_USERS, org_id=abc.id)


def test_assigned_scope_without_resource_needs_list_view(db):
    f = make_org(db, type="futran")
    aud = make_user(db, f, roles=["auditor"], name="Aud", email="aud@f.test")
    with pytest.raises(Forbidden):
        authorize(db, actor_for(db, aud), A.RECORD_FINDINGS)
    authorize(db, actor_for(db, aud), A.RECORD_FINDINGS, list_view=True)


# I3 — get_scoped also checks the engagement
def test_get_scoped_checks_engagement_assignment(db):
    f = make_org(db, type="futran")
    abc = make_org(db, type="client", name="ABC Corp")
    e2025 = Engagement(organization_id=abc.id, client_id=abc.id, name="2025")
    e2026 = Engagement(organization_id=abc.id, client_id=abc.id, name="2026")
    db.add_all([e2025, e2026])
    db.flush()
    aud = make_user(db, f, roles=["auditor"], name="Aud", email="aud@f.test")
    other = make_user(db, f, roles=["auditor"], name="Other", email="other@f.test")
    db.add(EngagementTeam(organization_id=abc.id, engagement_id=e2025.id, user_id=aud.id, role="auditor"))
    row2026 = EngagementTeam(organization_id=abc.id, engagement_id=e2026.id, user_id=other.id, role="auditor")
    db.add(row2026)
    db.flush()
    with pytest.raises(NotFound):
        get_scoped(db, actor_for(db, aud), EngagementTeam, row2026.id)


# I4 — bulk statements cannot touch the audit log
def test_audit_log_bulk_update_and_delete_blocked(db):
    org = make_org(db, type="client")
    audit.record(db, actor_id=None, action="x", obj=org)
    db.commit()
    with pytest.raises(Exception):
        db.execute(update(AuditLog).values(action="tampered"))
        db.flush()
    db.rollback()
    with pytest.raises(Exception):
        db.execute(delete(AuditLog))
        db.flush()
    db.rollback()
    assert db.query(AuditLog).one().action == "x"


# I5 — disabled users cannot reactivate through an old invitation
def test_disabled_user_cannot_accept_invitation(client, db):
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")
    db.commit()
    login_as(client, db, admin)
    uid = client.post("/api/v1/admin/users", json={"name": "Quinn", "email": "quinn@f.test", "roles": ["auditor"]}).json()["id"]
    msg = db.query(OutboxMessage).filter(OutboxMessage.to.contains("quinn@f.test")).one()
    token = msg.body_text.split("/invite/")[1].split()[0]
    from app.tenancy.models import User

    u = db.get(User, uid)
    u.status = "disabled"
    db.commit()
    with pytest.raises((Conflict, NotFound)):
        accept_invitation(db, client.app.state.settings, token, "A-Long-Password-2026")


def test_disabling_revokes_pending_invitations(client, db):
    from app.invitations.models import Invitation

    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")
    aud = make_user(db, f, roles=["auditor"], name="Aud", email="aud@f.test")
    aud.password_hash = None
    aud.status = "invited"
    invite_user(db, client.app.state.settings, admin, aud)
    db.commit()
    login_as(client, db, admin)
    # status invited -> disabled
    r = client.patch(f"/api/v1/admin/users/{aud.id}", json={"status": "disabled"})
    assert r.status_code == 200
    db.expire_all()
    assert db.query(Invitation).filter_by(user_id=aud.id, status="pending").count() == 0


# I6 — unknown emails are treated like known ones
def test_unknown_email_lockout_is_uniform(client, db):
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": "ghost@abc.com", "password": "wrong-password-x"})
    r = client.post("/api/v1/auth/login", json={"email": "ghost@abc.com", "password": "wrong-password-x"})
    assert r.status_code == 429


def test_unknown_email_runs_password_hash(monkeypatch, client, db):
    calls = []
    import app.auth.service as svc

    real = svc.verify_password
    monkeypatch.setattr(svc, "verify_password", lambda h, p: calls.append(1) or real(h, p))
    client.post("/api/v1/auth/login", json={"email": "ghost@abc.com", "password": "x" * 12})
    assert calls, "a dummy hash check must run for unknown emails"


# I7 — refuse to run with the default key when MFA is on
def test_default_secret_key_refused_with_mfa(settings, engine):
    bad = settings.model_copy(update={"mfa_required": True, "secret_key": "change-me"})
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(bad, engine=engine)


# M2 / M3 — CSV formula injection and negative limits
def test_audit_csv_neutralises_formulas_and_limit_clamped(client, db):
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")
    audit.record(db, actor_id=admin.id, action="x", obj=f, summary="=HYPERLINK(\"http://evil\")")
    db.commit()
    login_as(client, db, admin)
    text = client.get("/api/v1/audit-log?format=csv").text
    assert "'=HYPERLINK" in text
    assert len(client.get("/api/v1/audit-log?limit=-1").json()) <= 1


# M5 — email uniqueness enforced by the database
def test_email_unique_index_in_database(db):
    from sqlalchemy.exc import IntegrityError
    from app.tenancy.models import User

    a = make_org(db, type="client", name="ABC Corp")
    b = make_org(db, type="client", name="BCD Inc")
    db.add(User(organization_id=a.id, name="One", email="same@x.com"))
    db.flush()
    db.add(User(organization_id=b.id, name="Two", email="SAME@x.com"))
    with pytest.raises(IntegrityError):
        db.flush()


# M6 — used invitation links reveal nothing
def test_used_invitation_info_hides_details(client, db):
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")
    org = make_org(db, type="client")
    u = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com")
    u.status = "invited"
    u.password_hash = None
    inv = invite_user(db, client.app.state.settings, admin, u)
    db.commit()
    accept_invitation(db, client.app.state.settings, inv.raw_token, "A-Long-Password-2026")
    db.commit()
    info = client.get(f"/api/v1/invitations/accept/{inv.raw_token}").json()
    assert info == {"expired": False, "used": True}
