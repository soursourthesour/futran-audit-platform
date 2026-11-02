"""The in-process fake model used by the demo and the browser tests only quotes text it was given, so its suggestions
pass the quote check, and its client Q&A explanation never proposes an answer."""
from app.ai.fake import answer
from app.ai.text import find_quote

DOCS = [{"ref": "D1", "filename": "Model_Governance_Standard_v3.pdf", "pages": [
    {"page": 4, "text": "2.1 Development. All models are trained and deployed through the MLOps pipeline in Azure ML with staged approval gates."},
    {"page": 7, "text": "4.3 Validation. Validation is performed by the model owner before each release."}]},
    {"ref": "D2", "filename": "Invoice_Anomaly_Model_Card.docx", "pages": [{"page": 1, "text": "Section 5 Limitations: TBD.\nSection 6 Monitoring: drift is monitored weekly by the data science team."}]}]
METHOD = {"code": "6.1.01", "label": "Model development methodology", "help": "How models are built and released.", "type": "single",
          "options": [{"value": "agile", "label": "Agile / iterative"}, {"value": "mlops", "label": "MLOps pipeline"}, {"value": "none", "label": "No formal methodology"}]}
REPRO = {"code": "6.1.07", "label": "Model reproducibility", "help": None, "type": "single", "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]}


def test_fake_prefill_quotes_its_documents_and_leaves_gaps_unsupported():
    out = {s["code"]: s for s in answer("copilot_prefill", {"questions": [METHOD, REPRO], "documents": DOCS})["suggestions"]}
    m = out["6.1.01"]
    assert m["answer"] == "mlops" and m["document"] == "D1" and m["page"] == 4
    assert find_quote(DOCS[0]["pages"], m["quote"], m["page"]) == 4
    assert out["6.1.07"]["answer"] is None and out["6.1.07"]["quote"] is None


def test_fake_explain_never_suggests_an_answer():
    out = answer("explain", {"question": {"label": "Can a human override the AI?", "help": "Whether a person can change the outcome."},
                             "glossary": [{"term": "Human oversight", "meaning": "A person reviews and can change the outcome."}]})
    text = out["explanation"].lower()
    assert "can a human override the ai?" in text
    assert not any(p in text for p in ("you should answer", "the answer is", "choose yes", "choose no", "select "))
    assert out["terms"][0]["term"] == "Human oversight"


def test_fake_finds_contradictions_between_interview_and_documents():
    out = answer("review_check", {"interviews": [{"code": "8.2.05", "label": "Monitoring frequency", "answer": "Daily", "detail": None, "person": "Lee Park"}], "documents": DOCS})
    c = out["contradictions"][0]
    assert c["code"] == "8.2.05" and "weekly" in c["quote"] and c["document"] == "D2"


def test_fake_extracts_duties_from_law_text_and_recorded_requirements():
    out = answer("obligation_extract", {"default_actor": "employer", "question_cues": {"6.2.01": r"bias audit"}, "requirements": [{"code": "LL144-02", "text": "Publish a summary of the results of the most recent bias audit"}],
                                        "sources": [{"kind": "requirement", "label": "LL144-02", "citation": "§20-871(a)(2)", "text": "Publish a summary of the results of the most recent bias audit. A summary of the results of the most recent bias audit of such tool"},
                                                    {"kind": "full_text", "label": "full text", "citation": None, "text": "Such notice shall be made no less than ten business days before such use."}]})["obligations"]
    assert [o["citation"] for o in out] == ["§20-871(a)(2)", None] and out[0]["requirement_codes"] == ["LL144-02"] and out[0]["question_codes"] == ["6.2.01"]
    assert out[1]["deadline"] == "no less than ten business days before such use"
