"""Shared set-up for the AI tests: ABC Corp's SYS-001 with the fake model injected (tests never touch the network)."""
from io import BytesIO
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from app.questionnaire.seed import load_question_bank
from app.systems.models import AISystem
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401

CONSENT = "Clause 9.2 of the signed engagement letter: the client agrees to AI-assisted review under enterprise model terms."


@pytest.fixture
def fake_ai(app):
    from app.ai.client import FakeAIClient

    fake = FakeAIClient()
    app.state.ai_client_factory = lambda s: fake
    return fake


@pytest.fixture
def ai_sys(client, db, inv, people, fake_ai):
    """SYS-001 built in-house in HR; Alex (auditor) and Cara (chief) are on the team. AI is still off."""
    load_question_bank(db)
    cid, e, maria, hr, *_ = inv
    s = db.scalar(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.reference_id == "SYS-001"))
    s.built_by, s.department_id = "in_house", hr.id
    db.commit()
    return NS(cid=cid, e=e, maria=maria, s=s, hr=hr, people=people, fake=fake_ai)


def enable_ai(client, db, w) -> None:
    login_as(client, db, w.people["chief"])
    r = client.put(f"/api/v1/engagements/{w.e.id}/ai", json={"enabled": True, "consent_note": CONSENT})
    assert r.status_code == 200, r.text


def pdf(pages: list[list[str]]) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for lines in pages:
        y = 720
        for line in lines:
            c.drawString(72, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


def docx(paragraphs: list[str]) -> bytes:
    import docx as _docx

    d = _docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


STANDARD = [["Model Governance Standard v3", "Owner: Head of Data Science"],
            ["2.1 Development", "All models are trained and deployed through the Azure ML pipeline", "with staged approval gates (dev, UAT, prod)."],
            ["4.3 Validation", "Validation is performed by the model owner before each release."]]
CARD = ["Invoice anomaly model card", "Section 1 Purpose: flags supplier invoices that look unusual for review by accounts payable.",
        "Section 5 Limitations: TBD.", "Section 6 Monitoring: drift is monitored weekly by the data science team."]


def upload_docs(client, db, w) -> dict:
    """Alex uploads the governance standard (PDF) and the model card (DOCX) as SYS-001 evidence."""
    login_as(client, db, w.people["aud"])
    out = {}
    for name, data, ctype in (("Model_Governance_Standard_v3.pdf", pdf(STANDARD), "application/pdf"),
                              ("Invoice_Anomaly_Model_Card.docx", docx(CARD), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")):
        r = client.post(f"/api/v1/systems/{w.s.id}/evidence", files={"file": (name, data, ctype)})
        assert r.status_code == 200, r.text
        out[name] = r.json()["id"]
    return out


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    """The HTTP providers wait before retrying a rate limit or an outage; tests do not."""
    monkeypatch.setattr("app.ai.providers.base._sleep", lambda s: None)
