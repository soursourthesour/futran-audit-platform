"""Phase 5 review findings (I1–I8 and the minors fixed with them)."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.clock import utcnow
from app.docrequests.models import DocumentRequest
from app.engagements.models import Engagement
from app.findings.models import DraftFindingLink, Finding
from app.inventory.models import UseCase
from app.questionnaire.models import Question, Response
from app.reference.models import DocumentCatalogItem
from app.questionnaire.service import Target, save_response
from app.scoring import service as scoring
from app.systems.models import AISystem
from app.systems.service import create_from_use_case
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401
from tests.questionnaire.test_service import sys1  # noqa: F401
from tests.scoring.test_service import ats  # noqa: F401
from tests.governance.test_governance import _answer_all

SRC = {"source_person_name": "Lee Park", "source_person_title": "HR systems lead"}


def _aud(db, people, e, s, code, value, status="answered"):
    return save_response(db, people["aud"], Target(db.get(Engagement, e.id), db.get(AISystem, s.id)), code, {"value": value, "status": status, **SRC}, futran=True)


# ---- I1: raising a use case to Tier 3 makes its systems full depth
def test_raising_tier_upgrades_light_system(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    uc = UseCase(organization_id=cid, engagement_id=e.id, name="Drafting", department_id=hr.id, tool_ids=[], data_categories=["pii"], decision_impact="informs", proposed_tier=2, status="submitted",
                 submitted_by=maria.id)
    db.add(uc)
    db.flush()
    s = create_from_use_case(db, people["aud"], db.get(Engagement, e.id), [uc.id], built_by="vendor")
    db.commit()
    assert s.assessment_depth == "light"
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/use-cases/{uc.id}/final-tier", json={"tier": 3, "rationale": "Shortlists applicants."})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(AISystem, s.id).assessment_depth == "full"


# ---- I2: "not yet in place" counts as No for the BAA knock-out
def test_nyip_baa_triggers_knockout(client, db, ats, people):
    cid, e, maria, s = ats
    _aud(db, people, e, s, "5.1.02", "yes")
    _aud(db, people, e, s, "5.3.02", None, status="not_yet_in_place")
    assert "phi_vendor_no_baa" in scoring.latest(db, s).knockouts_triggered


# ---- I3: answers to questions that no longer apply drop out
def test_inapplicable_answer_stops_counting(client, db, ats, people):
    cid, e, maria, s = ats
    _aud(db, people, e, s, "5.1.02", "yes")
    _aud(db, people, e, s, "5.3.02", "baa_not_in_place")
    assert "phi_vendor_no_baa" in scoring.latest(db, s).knockouts_triggered
    assert db.scalar(select(Finding).where(Finding.source_question_ids == ["5.3.02"], Finding.deleted_at.is_(None))) is not None
    _aud(db, people, e, s, "5.1.02", "no")
    assert "phi_vendor_no_baa" not in scoring.latest(db, s).knockouts_triggered
    assert db.scalar(select(Finding).where(Finding.source_question_ids == ["5.3.02"], Finding.deleted_at.is_(None))) is None


# ---- I4: evidence downloads follow who may see the system; clients cannot use Futran's evidence
def test_evidence_access_by_department_and_side(client, db, sys1, people):
    cid, e, maria, s = sys1
    priya = db.scalar(select(User).where(User.email == "priya@abc.test"))
    login_as(client, db, priya)
    up = client.post(f"/api/v1/systems/{s.id}/evidence", files={"file": ("notes.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert up.status_code == 200, up.text
    assert client.get(f"/api/v1/files/{up.json()['id']}").status_code == 200
    login_as(client, db, people["aud"])
    mine = client.post(f"/api/v1/systems/{s.id}/evidence", files={"file": ("interview-notes.pdf", b"%PDF-1.4 y", "application/pdf")}).json()["id"]
    login_as(client, db, maria)
    assert client.get(f"/api/v1/files/{mine}").status_code == 404
    r = client.put(f"/api/v1/systems/{s.id}/responses/3.1.03", json={"value": "4.1", "status": "answered", "evidence_ids": [mine]})
    assert r.status_code == 422


# ---- I5: governance request answers pre-fill §4.1–4.2
def test_governance_submission_prefills_section_4(client, db, live):
    cid, e, maria = live
    from app.questionnaire.seed import load_question_bank

    load_question_bank(db)
    db.commit()
    login_as(client, db, maria)
    client.put(f"/api/v1/clients/{cid}/governance/extra", json={"fields": {"policy_owner": "Maria Lopez", "policy_covers_employees": "no", "raci_exists": "partial"}})
    _answer_all(client, cid)
    assert client.post(f"/api/v1/clients/{cid}/governance/submit", json={"accuracy_confirmed": True}).status_code == 200
    qs = {q["code"]: q["response"] for q in client.get(f"/api/v1/clients/{cid}/assessment").json()["questions"]}
    assert qs["4.1.02"]["value"] == {"name": "Maria Lopez", "title": None}
    assert qs["4.1.04"]["value"] == "no" and qs["4.2.07"]["value"] == "partial"
    assert db.scalar(select(Finding).where(Finding.source_question_ids == ["4.1.04"])) is not None


# ---- I6: dismissing a High draft recalculates the score
def test_dismiss_recalculates(client, db, ats, people):
    cid, e, maria, s = ats
    assert scoring.latest(db, s).domain_inputs["bias"]["open_high_or_critical"] == 1
    link = db.scalar(select(DraftFindingLink).join(Finding, Finding.id == DraftFindingLink.finding_id).where(Finding.source_question_ids == ["6.2.01"]))
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/draft-findings/{link.id}/dismiss", json={"reason": "Vendor test covers this."}).status_code == 200
    db.expire_all()
    assert scoring.latest(db, db.get(AISystem, s.id)).domain_inputs["bias"]["open_high_or_critical"] == 0


# ---- I7: the Lead Auditor sets final domain scores
def test_only_lead_auditor_sets_domain_scores(client, db, ats, people):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    assert client.put(f"/api/v1/systems/{s.id}/score/domains/data", json={"score": 2, "rationale": "x"}).status_code == 403
    login_as(client, db, people["chief"])
    assert client.put(f"/api/v1/systems/{s.id}/score/domains/data", json={"score": 2, "rationale": "x"}).status_code == 200
    assert client.put(f"/api/v1/systems/{s.id}/score/domains/data", json={"score": "²"}).status_code == 422  # M1


# ---- declined-to-judge ruling: an EU-prohibited practice stays Critical; other knock-outs can be overridden with a rationale
def test_override_cannot_lower_prohibited(client, db, ats, people):
    cid, e, maria, s = ats
    db.get(Engagement, e.id).frameworks = ["nist_ai_rmf", "eu_ai_act"]
    db.commit()
    _aud(db, people, e, s, "3.3.08", "prohibited")
    db.commit()
    assert scoring.latest(db, s).final_rating == "critical"
    login_as(client, db, people["chief"])
    r = client.put(f"/api/v1/systems/{s.id}/score/override", json={"rating": "high", "rationale": "Disagree"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "rating"


# ---- M6, M9: "false" is not verified; locks hold for uploads and drafts
def test_verified_false_string_and_locks(client, db, sys1, people):
    cid, e, maria, s = sys1
    login_as(client, db, people["aud"])
    assert client.put(f"/api/v1/systems/{s.id}/responses/3.1.03", json={"value": "4.2", "status": "answered", "verified": "false"}).status_code == 200
    db.get(Engagement, e.id).client_answers_locked_at = utcnow()
    db.commit()
    login_as(client, db, maria)
    assert client.post(f"/api/v1/systems/{s.id}/evidence", files={"file": ("x.pdf", b"%PDF-1.4 z", "application/pdf")}).status_code == 409
    db.get(Engagement, e.id).client_answers_locked_at = None
    db.commit()
    client.put(f"/api/v1/systems/{s.id}/responses/6.2.01", json={"value": "no", "status": "answered"})
    link = db.scalar(select(DraftFindingLink))
    sysrow = db.get(AISystem, s.id)
    sysrow.status = "locked"
    db.commit()
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/draft-findings/{link.id}/dismiss", json={"reason": "x"}).status_code == 409


# ---- M2: one row per target even when no system is involved
def test_engagement_level_rows_are_unique(client, db, sys1, people):
    cid, e, maria, s = sys1
    q = db.scalar(select(Question).where(Question.code == "4.1.02"))
    for _ in range(2):
        db.add(Response(organization_id=cid, engagement_id=e.id, ai_system_id=None, question_id=q.id, status="unanswered", evidence_ids=[], client_evidence_ids=[]))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    item = db.scalar(select(DocumentCatalogItem).limit(1))
    for _ in range(2):
        db.add(DocumentRequest(organization_id=cid, engagement_id=e.id, catalog_item_id=item.id, ai_system_id=None, requested_at=utcnow(), status="pending", evidence_ids=[]))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
