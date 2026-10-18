"""Task 28: auditor fieldwork on a use case, the null-compliance check, evidence requests and the stage 5 gate."""
from datetime import date, timedelta

from sqlalchemy import select

from app.core.clock import today
from app.docrequests.models import EvidenceRequest
from app.engagements.gates import GATES
from app.engagements.models import Engagement
from app.findings.models import Finding
from app.inventory.models import UseCase
from app.mail.models import OutboxMessage
from app.notifications import jobs
from app.questionnaire.service import Target, save_response
from app.systems.models import AISystem
from app.systems.service import create_from_use_case
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401
from app.questionnaire.seed import load_question_bank

SRC = {"source_person_name": "Lee Park", "source_person_title": "HR systems lead"}


def _t3(db, cid, e, hr, aedt="in_scope"):
    uc = UseCase(organization_id=cid, engagement_id=e.id, name="Résumé screening, NYC roles", department_id=hr.id, tool_ids=[], data_categories=["pii"], decision_impact="consequential",
                 proposed_tier=3, final_tier=3, final_tier_rationale="Ranks candidates", aedt_determination=aedt, status="dept_approved")
    db.add(uc)
    db.flush()
    return uc


def test_null_compliance_panel_and_draft_finding(client, db, inv, people):
    load_question_bank(db)
    cid, e, maria, hr, *_ = inv
    eng = db.get(Engagement, e.id)
    eng.type = "ll144_bias_audit"
    uc = _t3(db, cid, eng, hr)
    s = create_from_use_case(db, people["aud"], eng, [uc.id], built_by="vendor")
    save_response(db, people["aud"], Target(eng, s), "5.1a.01", {"value": "no", "status": "answered", **SRC}, futran=True)
    db.commit()
    login_as(client, db, people["aud"])
    d = client.get(f"/api/v1/use-cases/{uc.id}/fieldwork").json()
    nc = d["null_compliance"]
    assert nc["applies"] is True and "no applicant demographic data" in nc["message"]
    draft = nc["suggested_finding"]
    assert draft["severity"] == "high" and draft["null_compliance_flag"] is True and draft["use_case_ids"] == [uc.id]
    r = client.post(f"/api/v1/clients/{cid}/findings", json=draft)
    assert r.status_code == 200, r.text
    f = db.get(Finding, r.json()["id"])
    assert f.null_compliance_flag and f.status == "draft" and f.author_id == people["aud"].id and f.ref.startswith("F-")
    assert any(x["id"] == f.id for x in client.get(f"/api/v1/use-cases/{uc.id}/fieldwork").json()["findings"])
    # not an AEDT: no panel
    uc.aedt_determination = "out_of_scope"
    db.commit()
    assert client.get(f"/api/v1/use-cases/{uc.id}/fieldwork").json()["null_compliance"]["applies"] is False
    # the client cannot open the fieldwork view
    login_as(client, db, maria)
    assert client.get(f"/api/v1/use-cases/{uc.id}/fieldwork").status_code in (403, 404)


def test_stage5_gate_unmet_lists_unmapped_and_incomplete(client, db, inv, people):
    load_question_bank(db)
    cid, e, maria, hr, *_ = inv
    eng = db.get(Engagement, e.id)
    mapped = _t3(db, cid, eng, hr)
    loose = _t3(db, cid, eng, hr)
    loose.name = "Interview scoring"
    s = create_from_use_case(db, people["aud"], eng, [mapped.id], built_by="vendor")
    db.add(Finding(organization_id=cid, engagement_id=eng.id, ref="F-009", title="Open draft", severity="medium", status="draft", use_case_ids=[], source_question_ids=[], control_refs=[]))
    db.commit()
    unmet = GATES[5](db, eng).unmet
    assert any("Interview scoring" in u and "not mapped" in u for u in unmet)
    assert any(s.reference_id in u and "required question" in u for u in unmet)
    assert any(s.reference_id in u and "not scored" in u for u in unmet)
    assert any("F-009" in u for u in unmet)


def test_evidence_request_due_soon_notifies(client, db, inv, people, settings):
    cid, e, maria, hr, *_ = inv
    uc = _t3(db, cid, db.get(Engagement, e.id), hr)
    db.commit()
    login_as(client, db, people["aud"])
    due = today() + timedelta(days=3)
    r = client.post(f"/api/v1/use-cases/{uc.id}/evidence-requests", json={"description": "Most recent independent bias audit summary", "due_date": due.isoformat()})
    assert r.status_code == 200, r.text
    req_id = r.json()["id"]
    owner = r.json()["owner"]
    created = db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "notification")).all()
    assert any("bias audit summary" in (m.body_text or "") for m in created)
    assert client.post(f"/api/v1/use-cases/{uc.id}/evidence-requests", json={"description": "", "due_date": due.isoformat()}).status_code == 422
    n = jobs.run_due_soon(db, settings, today())
    assert n >= 1 and jobs.run_due_soon(db, settings, today()) == 0  # once
    # the owner answers on the client side
    login_as(client, db, maria)
    mine = client.get("/api/v1/me/evidence-requests").json()["requests"]
    assert [x["id"] for x in mine] == [req_id] and owner
    assert client.post(f"/api/v1/evidence-requests/{req_id}/answer", json={"answer": "We have never commissioned one."}).json()["status"] == "answered"
    up = client.post(f"/api/v1/evidence-requests/{req_id}/files", files={"file": ("audit.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert up.status_code == 200 and up.json()["status"] == "received"
    assert client.post(f"/api/v1/evidence-requests/{req_id}/waive", json={"reason": "x"}).status_code in (403, 404)
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/evidence-requests/{req_id}/waive", json={"reason": "Covered by the vendor audit."}).json()["status"] == "waived"
