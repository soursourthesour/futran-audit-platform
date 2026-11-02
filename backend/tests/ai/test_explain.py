"""Client Q&A helper (F1): "Explain this question" explains a question from the glossary and the help text, and never
suggests an answer. Only when AI is on for the engagement; logged like every AI call."""
from sqlalchemy import select

from app.ai.models import AIInteraction
from tests.ai.conftest import enable_ai
from tests.factories import login_as


def test_explain_uses_glossary_and_help_and_never_answers(client, db, ai_sys):
    w = ai_sys
    login_as(client, db, w.maria)
    assert client.post(f"/api/v1/systems/{w.s.id}/questions/7.1.02/explain").status_code == 403  # AI is off
    enable_ai(client, db, w)
    login_as(client, db, w.maria)
    r = client.post(f"/api/v1/systems/{w.s.id}/questions/7.1.02/explain")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["explanation"] and "answer" not in d  # the client sees an explanation only
    call = w.fake.calls[-1]
    assert "Never suggest" in call["system"] and "Can a human override the AI?" in call["prompt"]
    assert "Human oversight" in call["prompt"]  # glossary term the question touches
    assert "suggest" not in call["prompt"].lower() or "never suggest" in call["prompt"].lower()
    row = db.scalar(select(AIInteraction).where(AIInteraction.feature == "explain"))
    assert row.created_by == w.maria.id and row.engagement_id == w.e.id


def test_an_explanation_that_proposes_an_answer_is_replaced(client, db, ai_sys):
    w = ai_sys
    enable_ai(client, db, w)
    w.fake.replies["explain"] = {"explanation": "This is about overrides. The answer is Yes — always, so choose that.", "terms": []}
    login_as(client, db, w.maria)
    d = client.post(f"/api/v1/systems/{w.s.id}/questions/7.1.02/explain").json()
    assert "the answer is" not in d["explanation"].lower() and "always" not in d["explanation"].lower()
    assert db.scalar(select(AIInteraction).where(AIInteraction.feature == "explain")).status == "rejected"


def test_explain_is_for_questions_the_client_can_see(client, db, ai_sys):
    w = ai_sys
    enable_ai(client, db, w)
    login_as(client, db, w.maria)
    assert client.post(f"/api/v1/systems/{w.s.id}/questions/3.3.05s/explain").status_code == 404  # auditor-only question
