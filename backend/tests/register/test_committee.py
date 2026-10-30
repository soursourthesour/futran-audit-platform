from sqlalchemy import select

from app.notifications.models import Notification
from app.register.models import GovernanceRoleAssignment, RegisterSystem
from tests.register.conftest import new_system


def test_committee_starts_not_formed(client, db, reg):
    reg.as_(reg.caico)
    c = client.get("/api/v1/governance/committee").json()
    assert c["committee"]["status"] == "not_formed" and c["members"] == []
    assert c["can"]["record"] is True and c["can"]["members"] is True


def test_client_admin_manages_members_not_the_record(client, db, reg):
    reg.as_(reg.admin)
    r = client.post("/api/v1/governance/committee/members", json={"user_id": reg.caico.id, "committee_role": "secretary"})
    assert r.status_code == 200, r.text
    assert client.put("/api/v1/governance/committee", json={"target_date": "2026-12-15"}).status_code == 403
    assert client.post("/api/v1/governance/committee/formed", json={"formed_on": "2026-10-20", "charter_note": "Charter v1"}).status_code == 403
    reg.as_(reg.hr_lead)
    assert client.get("/api/v1/governance/committee").status_code == 200
    assert client.post("/api/v1/governance/committee/members", json={"user_id": reg.hr_lead.id, "committee_role": "business"}).status_code == 403


def test_member_validation(client, db, reg):
    reg.as_(reg.caico)
    r = client.post("/api/v1/governance/committee/members", json={"committee_role": "chair"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "user_id"
    r = client.post("/api/v1/governance/committee/members", json={"external_party": "Futran Solutions", "committee_role": "external_advisor_non_voting", "covers_role_id": "x"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "covers_role_id"
    r = client.post("/api/v1/governance/committee/members", json={"user_id": reg.caico.id, "committee_role": "boss"})
    assert r.status_code == 422
    assert client.post("/api/v1/governance/committee/members", json={"user_id": reg.caico.id, "committee_role": "chair"}).status_code == 200
    r = client.post("/api/v1/governance/committee/members", json={"user_id": reg.caico.id, "committee_role": "legal"})
    assert r.status_code == 409


def test_record_formed_needs_chair_and_charter_and_notifies_pending(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id)
    db.add(GovernanceRoleAssignment(organization_id=reg.org.id, register_system_id=s["id"], role_id="role-x", status="pending_committee"))
    db.commit()
    r = client.post("/api/v1/governance/committee/formed", json={"formed_on": "2026-12-10"})
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} >= {"charter", "members"}
    m = client.post("/api/v1/governance/committee/members", json={"user_id": reg.admin.id, "committee_role": "chair"}).json()
    client.post("/api/v1/governance/committee/members", json={"external_party": "Futran Solutions", "committee_role": "external_advisor_non_voting"})
    r = client.post("/api/v1/governance/committee/formed", json={"formed_on": "2026-10-20", "charter_note": "AI Governance Committee Charter v1", "meeting_cadence": "monthly", "approval_scope": "tier3_and_exceptions"})
    assert r.status_code == 200, r.text
    c = r.json()["committee"]
    assert c["status"] == "formed" and c["formed_on"] == "2026-10-20" and c["recorded_by"] == "Maria Lopez"
    n = db.scalar(select(Notification).where(Notification.user_id == reg.hr_lead.id, Notification.kind == "register_committee_formed"))
    assert n is not None and "1 role" in n.body
    assert client.request("DELETE", f"/api/v1/governance/committee/members/{m['id']}").status_code == 200
    _ = RegisterSystem


def test_committee_tenant_isolated(client, db, reg):
    from tests.factories import make_org, make_user

    reg.as_(reg.caico)
    m = client.post("/api/v1/governance/committee/members", json={"user_id": reg.caico.id, "committee_role": "chair"}).json()
    other = make_org(db, name="Other Co")
    o = make_user(db, other, roles=["caico"], name="Olga", email="olga@other.test")
    db.commit()
    reg.as_(o)
    assert client.get("/api/v1/governance/committee").json()["members"] == []
    assert client.request("DELETE", f"/api/v1/governance/committee/members/{m['id']}").status_code == 404


def test_committee_email_group_lists_the_committee_members(client, db, reg):
    """The client's default 'AI Governance Committee' email group follows the committee record (spec §26.3)."""
    from app.mail.groups import active_members, default_group, ensure_default_groups

    reg.as_(reg.admin)
    assert client.post("/api/v1/governance/committee/members", json={"user_id": reg.caico.id, "committee_role": "chair"}).status_code == 200
    assert client.post("/api/v1/governance/committee/members", json={"external_party": "Futran Solutions", "committee_role": "external_advisor_non_voting"}).status_code == 200
    ensure_default_groups(db, reg.org.id)
    group = default_group(db, reg.org.id, "committee")
    assert [p.user_id for p in active_members(db, group)] == [reg.caico.id]
