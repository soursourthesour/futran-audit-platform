"""How a carried-forward answer reads on the client's and the auditor's screens."""
from app.annual.service import _label
from app.questionnaire.models import Question


def test_person_answers_read_as_name_and_title_and_options_as_their_labels():
    q = Question(code="3.1.04", options=None)
    assert _label(q, {"name": "Maria Lopez", "title": "Chief AI Compliance Officer"}, "answered") == "Maria Lopez, Chief AI Compliance Officer"
    q = Question(code="6.2.01", options=[{"value": "no", "label": "No"}, {"value": "yes", "label": "Yes"}])
    assert _label(q, "no", "answered") == "No" and _label(q, None, "na") == "Not applicable"
    assert _label(Question(code="3.2.01", options=[{"value": "ml", "label": "Machine learning"}]), ["ml", "other"], "answered") == "Machine learning, other"
