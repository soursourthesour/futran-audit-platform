"""F10 customer questionnaires (client: Client Admin, CAICO): upload XLSX/DOCX/PDF, detect the questions, draft
answers from the answer library, published policies and the latest signed Futran report with citations, review, and
export in the original format. Approved answers grow the library; facts from the signed report are marked."""
from io import BytesIO

import pytest
from sqlalchemy import select

from app.ai.models import AIInteraction, AnswerLibraryItem, QuestionnaireItem
from tests.ai.conftest import CONSENT, docx, pdf
from tests.factories import login_as

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
REPORT_LINE = "ABC Corp performs an independent bias audit of each hiring tool every year."


def _xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "AI controls"
    ws.append(["Vendor security and AI questionnaire"])
    ws.append([])
    ws.append(["Ref", "Category", "Question", "Supplier response"])
    ws.append(["AI-1", "Governance", "Do you maintain an inventory of AI systems used in your services?", None])
    ws.append(["AI-2", "Fairness", "How often are your hiring tools audited for bias?", None])
    ws.append(["AI-3", "Security", "Describe your penetration testing programme for AI models.", None])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def qn(client, db, live, people, app):
    from app.ai.client import FakeAIClient

    cid, e, maria = live
    fake = FakeAIClient()
    app.state.ai_client_factory = lambda s: fake
    return cid, e, maria, people, fake


def _enable(client, db, people, e):
    login_as(client, db, people["chief"])
    assert client.put(f"/api/v1/engagements/{e.id}/ai", json={"enabled": True, "consent_note": CONSENT}).status_code == 200


def _upload(client, name, data, ctype, customer="Northwind Bank"):
    return client.post("/api/v1/questionnaires", data={"customer_name": customer}, files={"file": (name, data, ctype)})


def test_detects_questions_in_xlsx_docx_and_pdf(client, db, qn):
    cid, e, maria, people, fake = qn
    login_as(client, db, maria)
    r = _upload(client, "Northwind_AI_DDQ.xlsx", _xlsx(), XLSX_CT)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["question"] for i in items][0] == "Do you maintain an inventory of AI systems used in your services?" and len(items) == 3
    assert items[0]["locator"] == {"sheet": "AI controls", "row": 4, "col": 3, "answer_col": 4} and items[1]["section"] == "Fairness"
    d = _upload(client, "Security_review.docx", docx(["Section A: Governance", "Who is accountable for AI risk in your company?", "Do you train staff on AI use?", "Thank you."]), DOCX_CT).json()
    assert [i["question"] for i in d["items"]] == ["Who is accountable for AI risk in your company?", "Do you train staff on AI use?"]
    p = _upload(client, "DDQ.pdf", pdf([["Supplier questionnaire", "1. Do you test AI models for bias", "before deployment?", "2. Where is customer data stored?"]]), "application/pdf").json()
    assert [i["question"] for i in p["items"]] == ["1. Do you test AI models for bias before deployment?", "2. Where is customer data stored?"]
    assert _upload(client, "x.csv", b"a,b", "text/csv").status_code == 422
    login_as(client, db, people["aud"])
    assert client.get("/api/v1/questionnaires").status_code == 404  # client screen only


def test_draft_review_and_library(client, db, qn):
    cid, e, maria, people, fake = qn
    login_as(client, db, maria)
    assert client.post("/api/v1/answer-library", json={"question": "Do you keep an inventory of AI systems?", "answer": "Yes. We keep a register of every AI system with its owner and risk tier."}).status_code == 200
    q = _upload(client, "Northwind_AI_DDQ.xlsx", _xlsx(), XLSX_CT).json()
    assert client.post(f"/api/v1/questionnaires/{q['id']}/draft").status_code == 403  # AI is off for the engagement
    _enable(client, db, people, e)
    # a signed Futran report with a fact the questionnaire asks about (no service: report generation is out of scope here)
    from app.core.clock import utcnow
    from app.reports.models import Report

    db.add(Report(organization_id=cid, engagement_id=e.id, version="v1.0", status="final", body_md=f"# Audit report\n\n{REPORT_LINE}\n", content_hash="x", signed_at=utcnow(), released_to_client_at=utcnow()))
    db.commit()
    login_as(client, db, maria)
    r = client.post(f"/api/v1/questionnaires/{q['id']}/draft")
    assert r.status_code == 200, r.text
    items = {i["locator"]["row"]: i for i in r.json()["items"]}
    inv, bias, pen = items[4], items[5], items[6]
    assert inv["status"] == "suggested" and inv["answer"].startswith("Yes. We keep a register") and inv["citations"][0]["source_type"] == "library"
    assert bias["status"] == "suggested" and bias["audited_by_futran"] is True and bias["citations"][0]["source_type"] == "report"
    assert pen["status"] == "unsupported" and not pen["answer"]
    assert "Do you maintain an inventory" in fake.calls[-1]["prompt"] and REPORT_LINE in fake.calls[-1]["prompt"]
    # review
    assert client.post(f"/api/v1/questionnaires/{q['id']}/items/{bias['id']}/accept", json={"confirm_audited": True}).status_code == 200  # the approver confirms the label
    assert client.post(f"/api/v1/questionnaires/{q['id']}/items/{pen['id']}/accept", json={}).status_code == 409
    r = client.put(f"/api/v1/questionnaires/{q['id']}/items/{pen['id']}", json={"answer": "An external firm tests our models twice a year."})
    assert r.status_code == 200 and r.json()["status"] == "answered"
    lib = client.get("/api/v1/answer-library").json()["rows"]
    assert {x["question"] for x in lib} >= {"How often are your hiring tools audited for bias?", "Describe your penetration testing programme for AI models."}
    assert next(x for x in lib if x["question"].startswith("How often"))["audited_by_futran"] is True
    i = db.scalar(select(QuestionnaireItem).where(QuestionnaireItem.id == bias["id"]))
    assert db.get(AIInteraction, i.interaction_id).status == "accepted" and db.get(AIInteraction, i.interaction_id).engagement_id is None


def test_export_in_the_original_format(client, db, qn):
    from openpyxl import load_workbook

    cid, e, maria, people, fake = qn
    login_as(client, db, maria)
    q = _upload(client, "Northwind_AI_DDQ.xlsx", _xlsx(), XLSX_CT).json()
    client.put(f"/api/v1/questionnaires/{q['id']}/items/{q['items'][0]['id']}", json={"answer": "Yes, a register of every AI system."})
    r = client.get(f"/api/v1/questionnaires/{q['id']}/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith(XLSX_CT)
    ws = load_workbook(BytesIO(r.content))["AI controls"]
    assert ws.cell(row=4, column=4).value == "Yes, a register of every AI system." and ws.cell(row=5, column=4).value is None

    import docx as _docx

    d = _upload(client, "Security_review.docx", docx(["Who is accountable for AI risk in your company?", "Do you train staff on AI use?"]), DOCX_CT).json()
    client.put(f"/api/v1/questionnaires/{d['id']}/items/{d['items'][1]['id']}", json={"answer": "Yes, every employee completes AI literacy training each year."})
    out = _docx.Document(BytesIO(client.get(f"/api/v1/questionnaires/{d['id']}/export").content))
    texts = [p.text for p in out.paragraphs]
    assert texts.index("Answer: Yes, every employee completes AI literacy training each year.") == texts.index("Do you train staff on AI use?") + 1

    p = _upload(client, "DDQ.pdf", pdf([["1. Where is customer data stored?"]]), "application/pdf").json()
    client.put(f"/api/v1/questionnaires/{p['id']}/items/{p['items'][0]['id']}", json={"answer": "In Azure East US."})
    r = client.get(f"/api/v1/questionnaires/{p['id']}/export")
    assert r.headers["content-type"].startswith(DOCX_CT)
    texts = [x.text for x in _docx.Document(BytesIO(r.content)).paragraphs]
    assert any("original was a PDF" in t for t in texts) and "In Azure East US." in " ".join(texts)
