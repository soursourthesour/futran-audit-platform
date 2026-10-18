"""Phase 6 independent review: each finding reproduced before the fix."""
from datetime import timedelta

from sqlalchemy import select

from app.core.clock import today, utcnow
from app.engagements.gates import advance_if_ready
from app.engagements.models import Engagement
from app.findings.models import Finding
from app.inventory.models import UseCase
from app.remediation.models import RemediationItem
from app.systems.models import AISystem
from app.tenancy.models import Department, User
from tests.factories import approve_client_review, login_as, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import _uc, inv  # noqa: F401
from tests.reports.test_reports import _no_public_summary, _released, ready  # noqa: F401
from tests.signoffs.test_signoffs import rev  # noqa: F401


def _stage(db, e, n):
    db.get(Engagement, e.id).stage = n
    db.commit()


def _drop_systems(db, e):
    """No systems to score, and the client review signed: only findings stand between fieldwork and QA."""
    for s in db.scalars(select(AISystem).where(AISystem.engagement_id == e.id)):
        s.deleted_at = utcnow()
    db.commit()
    approve_client_review(db, e)


def _new(client, cid, title="Personal AI accounts", severity="medium"):
    r = client.post(f"/api/v1/clients/{cid}/findings", json={"title": title, "severity": severity, "description": "x", "recommended_remediation": "y"})
    assert r.status_code == 200, r.text
    return r.json()


# C1: stages move on by themselves when their gate is met
def test_c1_last_finding_submitted_moves_to_stage6(client, db, inv, people):
    cid, e, *_ = inv
    _stage(db, e, 5)
    _drop_systems(db, e)
    login_as(client, db, people["aud"])
    f = _new(client, cid)
    client.post(f"/api/v1/findings/{f['id']}/submit")
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 6


def test_c1_stage9_with_no_items_completes(client, db, inv, people):
    cid, e, *_ = inv
    eng = db.get(Engagement, e.id)
    eng.stage, eng.status = 9, "in_progress"
    db.commit()
    advance_if_ready(db, people["chief"], eng)
    db.commit()
    db.expire_all()
    assert db.get(Engagement, e.id).status == "completed"


# I1: a finding the Chief Auditor edited goes to the QA Reviewer
def test_i1_chief_edited_finding_routes_to_qa(client, db, inv, people):
    cid, e, *_ = inv
    _stage(db, e, 5)
    login_as(client, db, people["aud"])
    f = _new(client, cid)
    login_as(client, db, people["chief"])
    assert client.patch(f"/api/v1/findings/{f['id']}", json={"description": "Sharper wording."}).status_code == 200
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/findings/{f['id']}/submit")
    assert r.status_code == 409 and "QA Reviewer" in r.json()["detail"]  # no QA Reviewer on this team yet


# I2: a sign-off nobody else can sign is refused, and the preparer can withdraw one
def test_i2_lone_signer_cannot_be_preparer(client, db, rev):
    cid, e, maria, hr, copilot, chatgpt = rev
    priya, tom = (db.scalar(select(User).where(User.email == x)) for x in ("priya@abc.test", "tom@abc.test"))
    login_as(client, db, tom)
    uc = _uc(client, cid, hr, [copilot["id"]], name="Meeting notes")
    client.post(f"/api/v1/use-cases/{uc['id']}/submit")
    login_as(client, db, priya)
    assert client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": True}).status_code == 200
    r = client.post(f"/api/v1/clients/{cid}/signoffs/2/submit", json={"scope_ref": hr.id})
    assert r.status_code == 409 and "Department Compliance Lead" in r.text
    login_as(client, db, maria)
    so = client.post(f"/api/v1/clients/{cid}/signoffs/2/submit", json={"scope_ref": hr.id}).json()
    w = client.post(f"/api/v1/signoffs/{so['id']}/withdraw", json={})
    assert w.status_code == 200 and w.json()["status"] == "returned"


# I3: preconditions are checked again when signing
def test_i3_new_draft_finding_blocks_signoff5(client, db, inv, people):
    cid, e, *_ = inv
    _stage(db, e, 5)
    _drop_systems(db, e)
    login_as(client, db, people["aud"])
    f = _new(client, cid)
    client.post(f"/api/v1/findings/{f['id']}/submit")
    login_as(client, db, people["chief"])
    client.post(f"/api/v1/findings/{f['id']}/approve", json={})
    login_as(client, db, people["aud"])
    so = client.post(f"/api/v1/clients/{cid}/signoffs/5/submit", json={}).json()
    _new(client, cid, "Late critical", "critical")
    login_as(client, db, people["chief"])
    r = client.post(f"/api/v1/signoffs/{so['id']}/sign", json={"typed_name": people["chief"].name})
    assert r.status_code == 409 and "Late critical" in r.text


# I4: no correction once later work depends on the sign-off
def test_i4_no_signoff5_correction_after_release(client, db, ready, people):
    cid, e, maria, f = ready
    _no_public_summary(db, e)
    _released(client, db, people, cid)
    from app.signoffs.service import current

    so5 = current(db, db.get(Engagement, e.id), 5)
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/signoffs/{so5.id}/correct", json={"reason": "Add a finding."})
    assert r.status_code == 409


# I5: the locked inventory does not change without reopening sign-off 4
def test_i5_inventory_locked_after_snapshot(client, db, inv, people):
    cid, e, maria, hr, copilot, chatgpt = inv
    _stage(db, e, 5)
    from app.signoffs.service import create_sign_off

    so = create_sign_off(db, db.get(Engagement, e.id), 4, preparer_id=maria.id, required_roles=["caico"])
    so.status = "approved"
    db.commit()
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/use-cases", json={"name": "Late tool use", "department_id": hr.id, "tool_ids": [copilot["id"]], "data_categories": ["none"], "decision_impact": "none", "usage": [], "named_users": []})
    assert r.status_code == 409 and "sign-off 4" in r.text


# I6: an evidence request's owner can open the file they uploaded
def test_i6_owner_downloads_own_evidence(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    uc = UseCase(organization_id=cid, engagement_id=e.id, name="Résumé screening", department_id=hr.id, tool_ids=[], data_categories=["pii"], decision_impact="consequential", proposed_tier=3, status="dept_approved")
    db.add(uc)
    _stage(db, e, 5)
    login_as(client, db, people["aud"])
    req = client.post(f"/api/v1/use-cases/{uc.id}/evidence-requests", json={"description": "Bias audit", "due_date": (today() + timedelta(days=5)).isoformat()}).json()
    priya = db.scalar(select(User).where(User.email == "priya@abc.test"))
    from app.docrequests.models import EvidenceRequest

    db.get(EvidenceRequest, req["id"]).owner_user_id = priya.id
    db.commit()
    login_as(client, db, priya)
    up = client.post(f"/api/v1/evidence-requests/{req['id']}/files", files={"file": ("audit.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert up.status_code == 200, up.text
    fid = db.get(EvidenceRequest, req["id"]).file_ids[-1]
    assert client.get(f"/api/v1/files/{fid}").status_code == 200


# upgraded minor 5: editing a response leaves an item already under way alone
def test_m5_response_edit_keeps_progressed_item(client, db, ready, people):
    cid, e, maria, f = ready
    _no_public_summary(db, e)
    _released(client, db, people, cid)
    priya = db.scalar(select(User).where(User.email == "priya@abc.test"))
    login_as(client, db, maria)
    body = {"response": "agree", "planned_action": "First plan.", "owner_user_id": priya.id, "due_date": (today() + timedelta(days=30)).isoformat()}
    client.put(f"/api/v1/findings/{f['id']}/response", json=body)
    item = db.scalar(select(RemediationItem).where(RemediationItem.finding_id == f["id"]))
    client.post(f"/api/v1/remediation/{item.id}/done", json={"note": "Done."})
    client.put(f"/api/v1/findings/{f['id']}/response", json=body | {"response": "disagree", "planned_action": "We disagree."})
    db.expire_all()
    it = db.get(RemediationItem, item.id)
    assert it.deleted_at is None and it.action == "First plan." and it.status == "awaiting_verification"
