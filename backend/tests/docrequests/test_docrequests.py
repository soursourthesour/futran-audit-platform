from datetime import date, datetime

import pytest
import yaml
from sqlalchemy import select

from app.docrequests.models import DocumentChase, DocumentRequest
from app.docrequests.service import business_days_between, escalate_due, escalations_due
from app.engagements.models import Engagement
from app.findings.models import Finding
from app.mail.models import OutboxMessage
from app.notifications.models import Notification
from app.questionnaire.rules import EngagementFacts  # noqa: F401
from app.systems.models import AISystem
from app.systems.service import create_system
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401

SEED = yaml.safe_load(open("seeds/document_catalog.yaml"))["items"]


@pytest.fixture
def reg(client, db, inv, people):
    """ABC Corp with 4 systems and fieldwork starting Monday 16 November 2026."""
    cid, e, maria, hr, *_ = inv
    for name in ("Invoice anomaly model", "Interview scheduling chatbot"):
        create_system(db, people["aud"], db.get(Engagement, e.id), {"name": name, "built_by": "vendor", "use_case_ids": []}, source="wizard")
    eng = db.get(Engagement, e.id)
    eng.fieldwork_start = date(2026, 11, 16)
    db.commit()
    return cid, eng, maria


def _issue(client, db, people, cid):
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/clients/{cid}/document-requests/issue")
    assert r.status_code == 200, r.text
    return r.json()


def test_register_counts_with_per_system_items(client, db, reg, people):
    cid, e, maria = reg
    fw = set(e.frameworks or [])
    applies = lambda i: not i.get("condition") or i["condition"] in fw  # noqa: E731
    base = sum(1 for i in SEED if applies(i) and not i.get("per_system"))
    per_system = sum(1 for i in SEED if applies(i) and i.get("per_system"))
    out = _issue(client, db, people, cid)
    assert len(db.scalars(select(AISystem).where(AISystem.engagement_id == e.id)).all()) == 4
    assert out["kpis"]["requested"] == base + 4 * per_system
    assert db.query(DocumentRequest).count() == base + 4 * per_system
    mail = db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "document_request"))
    assert mail.to == ["maria@abc.test"] and "eli@futran.test" in (mail.cc or [])
    assert "Model card" in mail.body_text or "model card" in mail.body_text.lower()
    # issuing again adds nothing
    assert client.post(f"/api/v1/clients/{cid}/document-requests/issue").status_code == 409


def test_due_5_business_days_before_fieldwork(client, db, reg, people):
    cid, e, maria = reg
    _issue(client, db, people, cid)
    assert {r.due_at for r in db.scalars(select(DocumentRequest))} == {date(2026, 11, 9)}
    assert business_days_between(date(2026, 11, 6), date(2026, 11, 9)) == 1  # Friday to Monday
    assert business_days_between(date(2026, 11, 2), date(2026, 11, 5)) == 3


def test_not_available_creates_draft_finding(client, db, reg, people):
    cid, e, maria = reg
    _issue(client, db, people, cid)
    req = db.scalar(select(DocumentRequest).where(DocumentRequest.ai_system_id.is_(None)).order_by(DocumentRequest.created_at))
    login_as(client, db, maria)
    assert client.post(f"/api/v1/document-requests/{req.id}/not-available", json={"note": ""}).status_code == 422
    r = client.post(f"/api/v1/document-requests/{req.id}/not-available", json={"note": "We have no written policy yet."})
    assert r.status_code == 200 and r.json()["status"] == "not_available" and "finding" not in r.json()
    db.expire_all()
    f = db.get(Finding, db.get(DocumentRequest, req.id).finding_id)
    assert f.status == "draft" and f.origin == "document_request" and f.title.startswith("Document not available")
    # the document turns up after all: the untouched draft is withdrawn
    up = client.post(f"/api/v1/document-requests/{req.id}/files", files={"file": ("policy.pdf", b"%PDF-1.4 policy", "application/pdf")})
    assert up.status_code == 200 and up.json()["status"] == "received"
    db.expire_all()
    assert db.get(Finding, f.id).deleted_at is not None


def test_escalation_after_3_business_days(client, db, reg, people):
    cid, e, maria = reg
    _issue(client, db, people, cid)
    req = db.scalar(select(DocumentRequest).order_by(DocumentRequest.created_at))
    assert client.post(f"/api/v1/document-requests/{req.id}/chase", json={"note": "Reminder sent"}).status_code == 200
    chase = db.scalar(select(DocumentChase))
    chase.chased_at = datetime(2026, 11, 6, 15, 0)  # a Friday
    db.commit()
    assert escalations_due(db, date(2026, 11, 10)) == []  # Mon, Tue: 2 business days
    assert [r.id for r in escalations_due(db, date(2026, 11, 11))] == [req.id]
    from app.core.config import get_settings

    assert escalate_due(db, get_settings(), date(2026, 11, 11)) == 1
    assert escalate_due(db, get_settings(), date(2026, 11, 12)) == 0  # told once per chase
    notes = db.scalars(select(Notification).where(Notification.kind == "document_escalation")).all()
    assert {n.user_id for n in notes} == {people["chief"].id}


def test_client_sees_own_requests_no_findings(client, db, reg, people):
    cid, e, maria = reg
    _issue(client, db, people, cid)
    login_as(client, db, maria)
    rows = client.get("/api/v1/me/document-requests").json()["requests"]
    assert len(rows) == db.query(DocumentRequest).count()
    assert all("finding" not in r and "chases" not in r for r in rows)
    # a contributor sees only the requests for systems in their department
    from app.tenancy.models import User

    from app.tenancy.models import Department

    hr_system = db.scalar(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.reference_id == "SYS-001"))
    hr_system.department_id = db.scalar(select(Department.id).where(Department.organization_id == cid, Department.name == "HR"))
    db.commit()
    login_as(client, db, db.scalar(select(User).where(User.email == "tom@abc.test")))
    rows = client.get("/api/v1/me/document-requests").json()["requests"]
    assert rows and all(r["system"] == "HireScore" for r in rows)
    other = db.scalar(select(DocumentRequest).where(DocumentRequest.ai_system_id.is_(None)))
    assert client.post(f"/api/v1/document-requests/{other.id}/not-available", json={"note": "x"}).status_code in (403, 404)
