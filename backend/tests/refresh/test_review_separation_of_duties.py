"""Security review I5, I6 and the QA self-review finding: §6 rule 2 (no self-approval) and §25.7 (Futran Admin edits
become proposals) on the regulatory master."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.laws.models import Regulation
from app.regmaster import changes
from app.regmaster.models import LawVersion, ProposedChange, RoleCatalog
from tests.factories import login_as

API = "/api/v1"


def _propose(client, db, user, law, value):
    login_as(client, db, user)
    body = {"summary": "Effective date moved", "reason": "Per act", "changes": [{"field_path": "law.effective_on", "new_value": value}],
            "source_url": "https://lawfirm.example/post", "source_quote": "The Act takes effect on that day."}
    r = client.post(f"{API}/reg/laws/{law.id}/proposals", json=body)
    assert r.status_code == 200, r.text
    return db.get(ProposedChange, r.json()["proposals"][0]["id"])


def _effective_on(db, law) -> str:
    db.expire_all()
    return db.get(LawVersion, db.get(Regulation, law.id).current_version_id).effective_on.isoformat()


# ---------------------------------------------------------------- I5
def test_the_chief_auditor_cannot_approve_a_change_they_proposed(client, db, lit, reg):
    pc = _propose(client, db, lit["chief"], reg["law"], "2028-01-01")
    r = client.post(f"{API}/reg/changes/{pc.id}/decide", json={"action": "approve"})
    assert r.status_code == 403, r.text
    assert _effective_on(db, reg["law"]) != "2028-01-01"
    login_as(client, db, lit["chief2"])  # another Chief Auditor may
    assert client.post(f"{API}/reg/changes/{pc.id}/decide", json={"action": "approve"}).status_code == 200
    assert _effective_on(db, reg["law"]) == "2028-01-01"


def test_bulk_approval_skips_the_chief_auditors_own_proposals(client, db, lit, reg):
    pc = _propose(client, db, lit["chief"], reg["law"], "2028-02-01")
    r = client.post(f"{API}/reg/changes/bulk", json={"ids": [pc.id], "action": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["ok"] is False and "prepared" in r.json()["results"][0]["error"]
    db.expire_all()
    assert db.get(ProposedChange, pc.id).status == "pending"


def test_a_change_the_refresh_pipeline_proposed_is_not_the_runners_own(client, db, lit, reg):
    """Ruling: a Claude-made proposal (origin claude_refresh) records no proposer, so the Chief Auditor who ran the run may
    approve it."""
    pc = changes.propose(db, actor_id=None, regulation_id=reg["law"].id, field_path="law.effective_on", new_value="2028-03-01", summary="Effective date moved",
                         origin="claude_refresh", change_type="effective_date", source_url="https://www.ilga.gov/x", source_quote="Takes effect March 1, 2028.")
    db.commit()
    assert pc.proposed_by is None
    login_as(client, db, lit["chief"])
    assert client.post(f"{API}/reg/changes/{pc.id}/decide", json={"action": "approve"}).status_code == 200
    assert _effective_on(db, reg["law"]) == "2028-03-01"


# ---------------------------------------------------------------- QA second review
def test_qa_cannot_second_review_their_own_suggestion(client, db, lit, reg):
    pc = _propose(client, db, lit["qa"], reg["law"], "2029-01-01")
    pc.confidence = "low"
    db.commit()
    r = client.post(f"{API}/reg/changes/{pc.id}/second-review", json={"outcome": "concur", "note": "Looks right"})
    assert r.status_code == 403, r.text
    db.expire_all()
    assert db.get(ProposedChange, pc.id).second_reviewer_id is None


# ---------------------------------------------------------------- I6
def _role(db):
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(db)
    db.commit()
    return db.scalar(select(RoleCatalog).where(RoleCatalog.level == "company").order_by(RoleCatalog.number))


def test_a_futran_admin_role_edit_is_sent_for_approval(client, db, lit, reg):
    role = _role(db)
    login_as(client, db, lit["admin"])
    r = client.patch(f"{API}/reg/roles/{role.code}", json={"level": "agent", "reason": "The role sits with each agent"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "proposed" and r.json()["proposal_id"]
    db.expire_all()
    assert db.get(RoleCatalog, role.id).level == "company"  # nothing changed yet
    pc = db.get(ProposedChange, r.json()["proposal_id"])
    assert pc.field_path == f"role.{role.code}" and pc.new_value == {"level": "agent"} and pc.proposed_by == lit["admin"].id
    login_as(client, db, lit["chief"])
    assert client.post(f"{API}/reg/changes/{pc.id}/decide", json={"action": "approve"}).status_code == 200
    db.expire_all()
    assert db.get(RoleCatalog, role.id).level == "agent"
    assert db.get(ProposedChange, pc.id).status == "approved"


def test_a_chief_auditor_role_edit_applies_at_once_with_an_audit_entry(client, db, lit, reg):
    role = _role(db)
    login_as(client, db, lit["chief"])
    r = client.patch(f"{API}/reg/roles/{role.code}", json={"description": "Owns the AI governance program."})
    assert r.status_code == 200 and r.json()["status"] == "applied", r.text
    db.expire_all()
    assert db.get(RoleCatalog, role.id).description == "Owns the AI governance program."
    assert db.scalar(select(AuditLog).where(AuditLog.action == "regmaster.role_edit", AuditLog.object_id == role.id)) is not None
