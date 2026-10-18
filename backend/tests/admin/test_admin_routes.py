import csv
import io

from app.audit_log import service as audit
from app.mail.models import OutboxMessage
from app.tenancy.models import User
from tests.factories import login_as, make_org, make_user


def _futran(db):
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@futran.test")
    aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    db.commit()
    return f, admin, aud


def test_admin_creates_futran_user_and_invites(client, db):
    _, admin, _ = _futran(db)
    login_as(client, db, admin)
    r = client.post("/api/v1/admin/users", json={"name": "Quinn Reviewer", "email": "Quinn@Futran.test", "job_title": "QA lead", "roles": ["qa_reviewer"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "quinn@futran.test" and body["status"] == "invited" and body["roles"] == ["qa_reviewer"]
    db.expire_all()
    assert db.query(OutboxMessage).filter(OutboxMessage.to.contains("quinn@futran.test")).count() == 1
    users = client.get("/api/v1/admin/users").json()
    assert {u["email"] for u in users} >= {"admin@futran.test", "quinn@futran.test"}


def test_admin_cannot_assign_client_role_to_futran_user(client, db):
    _, admin, _ = _futran(db)
    login_as(client, db, admin)
    r = client.post("/api/v1/admin/users", json={"name": "X", "email": "x@futran.test", "roles": ["caico"]})
    assert r.status_code == 422


def test_auditor_cannot_manage_users_403(client, db):
    _, _, aud = _futran(db)
    login_as(client, db, aud)
    r = client.post("/api/v1/admin/users", json={"name": "Q", "email": "q@futran.test", "roles": ["auditor"]})
    assert r.status_code == 403


def test_admin_disables_user(client, db):
    _, admin, aud = _futran(db)
    login_as(client, db, admin)
    r = client.patch(f"/api/v1/admin/users/{aud.id}", json={"status": "disabled"})
    assert r.status_code == 200 and r.json()["status"] == "disabled"


def test_admin_cannot_disable_self(client, db):
    _, admin, _ = _futran(db)
    login_as(client, db, admin)
    r = client.patch(f"/api/v1/admin/users/{admin.id}", json={"status": "disabled"})
    assert r.status_code == 409


def test_resend_invitation(client, db):
    _, admin, _ = _futran(db)
    login_as(client, db, admin)
    uid = client.post("/api/v1/admin/users", json={"name": "Quinn", "email": "quinn@futran.test", "roles": ["qa_reviewer"]}).json()["id"]
    r = client.post(f"/api/v1/invitations/{uid}/resend")
    assert r.status_code == 200
    db.expire_all()
    assert db.query(OutboxMessage).filter(OutboxMessage.to.contains("quinn@futran.test")).count() == 2


def test_audit_log_csv_export_columns(client, db):
    f, admin, _ = _futran(db)
    audit.record(db, actor_id=admin.id, action="org.update", obj=f, summary="Updated settings")
    db.commit()
    login_as(client, db, admin)
    r = client.get("/api/v1/audit-log?format=csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["at", "actor", "action", "object_type", "object_id", "summary", "ip"]
    assert any(row[2] == "org.update" for row in rows[1:])


def test_audit_log_client_sees_own_org_only(client, db):
    _futran(db)
    a = make_org(db, type="client", name="ABC Corp")
    b = make_org(db, type="client", name="BCD Inc")
    caico = make_user(db, a, roles=["caico"], name="Cai Co", email="caico@abc.test")
    audit.record(db, actor_id=caico.id, action="a.thing", obj=a)  # the client's own action
    audit.record(db, actor_id=None, action="b.thing", obj=b)
    db.commit()
    login_as(client, db, caico)
    actions = {e["action"] for e in client.get("/api/v1/audit-log").json()}
    assert "a.thing" in actions and "b.thing" not in actions


def test_contributor_cannot_view_audit_log(client, db):
    a = make_org(db, type="client", name="ABC Corp")
    u = make_user(db, a, roles=["contributor"], name="Con Tributor", email="c@abc.test")
    db.commit()
    login_as(client, db, u)
    assert client.get("/api/v1/audit-log").status_code == 403


def test_settings_endpoint_reports_config(client, db):
    _, admin, _ = _futran(db)
    login_as(client, db, admin)
    s = client.get("/api/v1/admin/settings").json()
    assert s["mfa_required"] is False and s["email_mode"] == "outbox" and s["law_refresh_enabled"] is False
