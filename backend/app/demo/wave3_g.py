"""Demo data for WS-G (spec §21 F1, F5, F10; screen 25): the AI copilot on Meridian's credit risk model, the AI
interaction log, extracted obligations on NYC Local Law 144, and ABC Corp's customer questionnaire in progress.

Everything goes through the API as the person who would do it. The model is the in-process demonstration model
(app.ai.fake), which only quotes the documents it is given, so every citation below is real text from the uploaded files.
"""
from __future__ import annotations

from io import BytesIO

from app.demo.seed_demo import ABC, Demo, DemoError

MERIDIAN = "meridian.example"
CONSENT_MERIDIAN = "Engagement letter clause 11.3, signed by Katrin Vogel: Meridian agrees to AI-assisted document review under enterprise model terms (no training on inputs, EU data residency)."
CONSENT_ABC = "Engagement letter clause 9.2, signed by Maria Lopez: ABC Corp agrees to AI-assisted review and AI drafting of customer questionnaire answers."

# ---------------------------------------------------------------- the client's documents
STANDARD = ("Meridian_Model_Risk_Management_Standard_v3.pdf", "Model Risk Management Standard", [
    ("1. Purpose and scope", [
        "This standard sets out how Meridian Analytics GmbH develops, validates, deploys and monitors statistical and machine learning models used in credit decisions.",
        "Owner: Head of Data Science. Approved by the Model Risk Committee on 12 February. Next review: February next year.",
        "It applies to every model that scores, ranks or segments retail and small business loan applicants in Germany and India."]),
    ("2. Model development", [
        "2.1 All credit models are developed and deployed through the MLOps pipeline in Azure Machine Learning with staged approval gates (development, UAT, production).",
        "2.2 Feature engineering is documented in the feature catalogue, including the source and derivation of each input feature.",
        "2.3 The training, validation and test split is 70/15/15, drawn by application date so that the test set is the most recent quarter.",
        "2.4 Hyperparameter tuning uses Bayesian optimisation over 200 trials, and every trial is recorded in the experiment log."]),
    ("3. Explainability and change", [
        "3.1 SHAP values are calculated for every credit decision and stored with the application record so that adverse action reasons can be given.",
        "3.2 Changes to a production model are approved by the Model Risk Committee under the change management procedure, with a rollback plan for each release."]),
    ("4. Validation", [
        "4.1 Validation is performed by the model owner within the Data Science team before each release.",
        "4.2 The Model Risk Committee reviews each validation report and records its decision in the minutes."]),
])
MONITORING = ("Credit_Model_Monitoring_Report_Q3.pdf", "Credit scorecard monitoring report, third quarter", [
    ("Summary", [
        "This report covers the Credit Risk Scorecard v4 in production for retail lending in Germany.",
        "Drift monitoring for the credit scorecard runs monthly against the development sample.",
        "The last recorded drift run is dated 14 June, four months before this report; the July to September runs did not complete after the data platform migration."]),
    ("Results of the last run", [
        "The population stability index for the last run was 0.08, below the 0.10 alert threshold.",
        "Approval rates by age band and by sex were within two percentage points of the development sample."]),
])
CARD = ("Credit_Risk_Scorecard_v4_Model_Card.docx", [
    ("h", "Credit Risk Scorecard v4: model card"),
    ("p", "This model card documents the purpose and the input features of the scorecard; section 5 (limitations) is not yet complete: TBD."),
    ("h", "1. Purpose"),
    ("p", "The scorecard estimates the probability that a retail loan applicant defaults within 12 months. Credit officers use the score with the lending policy; they make the decision."),
    ("h", "3. Features"),
    ("p", "38 input features from the application form and the credit bureau file. Postcode and nationality are excluded from the feature set."),
    ("h", "5. Limitations"),
    ("p", "TBD."),
    ("h", "6. Monitoring"),
    ("p", "Drift is monitored weekly by the Data Science team, and the score distribution is compared with the development sample."),
])


def _pdf(title: str, org: str, sections: list[tuple[str, list[str]]]) -> bytes:
    """A plain policy-style PDF: one section per page, wrapped text, page numbers in the footer."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    for n, (heading, paras) in enumerate(sections, start=1):
        y = h - 72
        if n == 1:
            c.setFont("Helvetica-Bold", 16)
            c.drawString(72, y, title)
            y -= 20
            c.setFont("Helvetica", 10)
            c.drawString(72, y, org)
            y -= 28
        c.setFont("Helvetica-Bold", 12)
        c.drawString(72, y, heading)
        y -= 20
        c.setFont("Helvetica", 10.5)
        for p in paras:
            for line in simpleSplit(p, "Helvetica", 10.5, w - 144):
                c.drawString(72, y, line)
                y -= 14
            y -= 8
        c.setFont("Helvetica", 8)
        c.drawString(72, 40, f"{org} · Internal · Page {n} of {len(sections)}")
        c.showPage()
    c.save()
    return buf.getvalue()


def _docx(blocks: list[tuple[str, str]]) -> bytes:
    import docx

    d = docx.Document()
    for kind, text in blocks:
        if kind == "h":
            d.add_heading(text, level=1 if text.startswith("Credit") else 2)
        else:
            d.add_paragraph(text)
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def _questionnaire_xlsx() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "AI and data"
    ws.append(["Northwind Bank: supplier due diligence, artificial intelligence and data"])
    ws.append(["Please answer every question. Attach evidence where indicated."])
    ws.append([])
    ws.append(["Ref", "Domain", "Question", "Supplier response", "Evidence attached (Y/N)"])
    rows = [
        ("AI-01", "Governance", "Do you maintain an inventory of the AI systems used to deliver services to us?"),
        ("AI-02", "Governance", "Who in your organization is accountable for AI risk?"),
        ("AI-03", "Fairness", "Has an independent party audited your hiring tools for bias in the last 12 months?"),
        ("AI-04", "Fairness", "Do you publish a summary of your bias audit results?"),
        ("AI-05", "Transparency", "Do you tell candidates when an automated tool is used in their application?"),
        ("AI-06", "Data", "Is our data used to train any AI model?"),
        ("AI-07", "Security", "Describe your penetration testing programme for AI-enabled applications."),
        ("AI-08", "Oversight", "Can a person override the output of your AI screening tool?"),
    ]
    for r in rows:
        ws.append(list(r))
    for c in ws[4]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")
    ws["A1"].font = Font(bold=True, size=13)
    for col, width in (("A", 8), ("B", 14), ("C", 70), ("D", 60), ("E", 14)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=5):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


LIBRARY = [
    ("Do you maintain an inventory of the AI systems you use?",
     "Yes. ABC Corp keeps an AI system register that lists every AI system, its business owner, its risk tier and the laws that apply to it. The Chief AI Compliance Officer reviews it every quarter."),
    ("Is customer data used to train AI models?",
     "No. Customer data is not used to train any AI model. Our enterprise agreements with AI vendors prohibit training on our inputs."),
    ("Who is accountable for AI risk?",
     "The Chief AI Compliance Officer is accountable for AI risk and reports to the Chief Operating Officer, who sponsors the AI governance programme."),
]


# ---------------------------------------------------------------- helpers
def _upload(m: Demo, path: str, name: str, data: bytes, ctype: str) -> dict:
    r = m.c.post(f"/api/v1{path}", files={"file": (name, data, ctype)})
    if r.status_code != 200:
        raise DemoError(f"POST {path} → {r.status_code}: {r.text[:600]}")
    m.db.expire_all()
    return r.json()


def _meridian_copilot(m: Demo, mid: str) -> dict:
    from sqlalchemy import select

    from app.systems.models import AISystem
    from app.tenancy.models import Department

    e = m.engagement(mid)
    chief, aud, katrin = m.user("chief@futran.demo"), m.user("auditor1@futran.demo"), m.user(f"katrin.vogel@{MERIDIAN}")
    m.as_(chief).put(f"/engagements/{e.id}/ai", {"enabled": True, "consent_note": CONSENT_MERIDIAN})
    s = m.db.scalar(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.name == "Credit risk scoring model"))
    if s is None:
        raise DemoError("Meridian has no credit risk scoring model")
    ds = m.db.scalar(select(Department).where(Department.organization_id == mid, Department.name == "Data Science"))
    m.as_(aud).patch(f"/systems/{s.id}", {"built_by": "in_house", "department_id": ds.id, "version": "4.2"})
    files = {}
    for name, title, sections in (STANDARD, MONITORING):
        files[name] = _upload(m, f"/systems/{s.id}/evidence", name, _pdf(title, "Meridian Analytics GmbH", sections), "application/pdf")["id"]
    files[CARD[0]] = _upload(m, f"/systems/{s.id}/evidence", CARD[0], _docx(CARD[1]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")["id"]
    # interview answers recorded by the auditor, with who gave them
    m.put(f"/systems/{s.id}/responses/8.2.01", {"status": "answered", "value": "yes", "detail": "Automated drift job in Azure ML.", "source_person_name": "Lena Fischer", "source_person_title": "Head of Data Science"})
    m.put(f"/systems/{s.id}/responses/8.2.05", {"status": "answered", "value": "weekly", "source_person_name": "Lena Fischer", "source_person_title": "Head of Data Science"})
    # document pre-fill of §6.1, then the auditor's decisions
    rows = {r["target_code"]: r for r in m.post(f"/systems/{s.id}/copilot/prefill", {"sub_section": "6.1"})["suggestions"]}
    high = [r["id"] for r in rows.values() if r["status"] == "suggested" and r["confidence"] == "high"]
    m.post(f"/systems/{s.id}/copilot/accept-high", {"ids": high[:3]})
    card = rows.get("6.1.02")
    if card and card["status"] == "suggested" and card["output"].get("draft_finding"):
        m.post(f"/ai/interactions/{card['id']}/accept", {"create_finding": True})
    for code, r in rows.items():
        if r["status"] == "unsupported":
            m.post(f"/ai/interactions/{r['id']}/interview")
            break
    tune = rows.get("6.1.05")
    if tune and tune["status"] == "suggested" and tune["id"] not in high[:3]:
        m.post(f"/ai/interactions/{tune['id']}/reject", {"reason": "Lena Fischer said in interview that tuning moved to grid search in version 4.2; the standard is out of date."})
    # §8.2 suggestions left for the auditor to review
    m.post(f"/systems/{s.id}/copilot/prefill", {"sub_section": "8.2"})
    # evidence check on checklist 6.4: link the files to the items without ticking them
    m.put(f"/systems/{s.id}/checklist/6.4.05", {"confirmed": False, "evidence_ids": [files[STANDARD[0]]]})
    m.put(f"/systems/{s.id}/checklist/6.4.01", {"confirmed": False, "evidence_ids": [files[CARD[0]]]})
    m.post(f"/systems/{s.id}/copilot/evidence-check", {"section": "6.4"})
    # completeness review before sign-off 5, and two questions to the copilot
    m.post(f"/systems/{s.id}/copilot/completeness", {"signoff": 5})
    m.post(f"/systems/{s.id}/copilot/ask", {"question": "Who validates the credit scorecard before release, and is that validation independent?"})
    m.post(f"/engagements/{e.id}/copilot/ask", {"question": "How often is drift monitoring run on the credit scorecard?"})
    # the client's CAICO asks what a question means
    m.as_(katrin).post(f"/systems/{s.id}/questions/7.1.02/explain")
    return {"meridian_credit_system": s.id}


def _obligations(m: Demo) -> None:
    from app.demo.v061 import LEGAL, _law

    legal = m.user(LEGAL[1])
    law = _law(m, "Local Law 144")
    rows = m.as_(legal).post(f"/reg/laws/{law}/obligations/extract")["obligations"]
    ok = [o for o in rows if o["status"] == "suggested"]
    for o in ok[:2]:
        m.post(f"/obligations/{o['id']}/approve", {})
    for o in rows:
        if o["status"] == "unsupported":
            m.post(f"/obligations/{o['id']}/reject", {"reason": "The quoted text is not in the law as stored."})


def _abc_questionnaire(m: Demo, cid: str) -> None:
    e = m.engagement(cid)
    m.as_(m.user("chief@futran.demo")).put(f"/engagements/{e.id}/ai", {"enabled": True, "consent_note": CONSENT_ABC})
    maria = m.user(f"maria.lopez@{ABC}")
    m.as_(maria)
    for q, a in LIBRARY:
        m.post("/answer-library", {"question": q, "answer": a})
    r = m.c.post("/api/v1/questionnaires", data={"customer_name": "Northwind Bank", "title": "Northwind Bank supplier AI due diligence", "due_date": m.d(12)},
                 files={"file": ("Northwind_Bank_Supplier_AI_Due_Diligence.xlsx", _questionnaire_xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    if r.status_code != 200:
        raise DemoError(f"questionnaire upload → {r.status_code}: {r.text[:600]}")
    qid = r.json()["id"]
    items = m.post(f"/questionnaires/{qid}/draft")["items"]
    drafted = [i for i in items if i["status"] == "suggested"]
    for i in drafted[:2]:
        m.post(f"/questionnaires/{qid}/items/{i['id']}/accept", {})
    pen = next((i for i in items if i["question"].startswith("Describe your penetration")), None)
    if pen:
        m.put(f"/questionnaires/{qid}/items/{pen['id']}", {"answer": "An external CREST-accredited firm tests our AI-enabled applications twice a year, and after each major release. Findings are tracked to closure by the IT security team."})


def seed(m: Demo, ids: dict) -> dict:
    from app.ai.client import FakeAIClient

    app_state = m.c.app.state
    before = getattr(app_state, "ai_client_factory", None)
    app_state.ai_client_factory = lambda s: FakeAIClient()  # never the network while seeding, even with a key set
    try:
        out = _meridian_copilot(m, ids["meridian"])
        _obligations(m)
        _abc_questionnaire(m, ids["abc"])
    finally:
        app_state.ai_client_factory = before
    m.db.commit()
    return out
