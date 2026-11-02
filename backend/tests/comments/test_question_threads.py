"""Comments on any question (spec §21 F18), including one nobody has answered yet: the first comment needs an empty response
row to hang on. Opening that thread follows the same visibility rules as the comments and never marks the question
answered or changes completion."""
from sqlalchemy import select

from app.questionnaire.models import Question, Response

API = "/api/v1"


def _unanswered(db, w, code="6.2.02", respondent="client"):
    q = Question(template_version_id=db.get(Question, w.resp.question_id).template_version_id, code=code, section="6", sub_section="6.2", section_title="Bias",
                 scope="system", label="Bias monitoring in place", type="single", default_respondent=respondent)
    db.add(q)
    db.commit()
    return q


def _completion(client, w):
    r = client.get(f"{API}/systems/{w.sys.id}/assessment")
    assert r.status_code == 200, r.text
    return r.json()["completion"], {x["code"]: x["response"] for x in r.json()["questions"]}


def test_the_audit_team_comments_on_an_unanswered_question(client, db, w):
    q = _unanswered(db, w)
    w.as_(w.aud)
    before, rows = _completion(client, w)
    assert rows["6.2.02"] is None
    r = client.post(f"{API}/systems/{w.sys.id}/responses/6.2.02/thread")
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert client.post(f"{API}/systems/{w.sys.id}/responses/6.2.02/thread").json()["id"] == rid  # one row per question
    c = client.post(f"{API}/comments", json={"object_type": "response", "object_id": rid, "body": "Ask HR for the monitoring plan."})
    assert c.status_code == 200, c.text
    row = db.scalar(select(Response).where(Response.question_id == q.id))
    db.refresh(row)
    assert row.status == "unanswered" and row.client_status is None and row.value is None and row.answered_by is None
    after, rows = _completion(client, w)
    assert after == before and rows["6.2.02"]["status"] == "unanswered" and rows["6.2.02"]["id"] == rid


def test_the_client_comments_on_its_own_unanswered_question(client, db, w):
    _unanswered(db, w)
    w.as_(w.hr_lead)  # Human Resources owns the system
    r = client.post(f"{API}/systems/{w.sys.id}/responses/6.2.02/thread")
    assert r.status_code == 200, r.text
    c = client.post(f"{API}/comments", json={"object_type": "response", "object_id": r.json()["id"], "body": "We are drafting the plan."})
    assert c.status_code == 200, c.text
    _, rows = _completion(client, w)
    assert rows["6.2.02"]["status"] == "unanswered"


def test_opening_a_thread_follows_the_same_visibility_rules(client, db, w):
    _unanswered(db, w)
    _unanswered(db, w, code="6.2.03", respondent="auditor")
    for user in (w.fin_lead, w.x_caico):  # another department's lead; another tenant
        w.as_(user)
        assert client.post(f"{API}/systems/{w.sys.id}/responses/6.2.02/thread").status_code in (403, 404), user.name
    w.as_(w.hr_lead)  # an auditor-only question is not shown to the client
    assert client.post(f"{API}/systems/{w.sys.id}/responses/6.2.03/thread").status_code == 404
    w.as_(w.aud2)  # a Futran auditor who is not on the engagement
    assert client.post(f"{API}/systems/{w.sys.id}/responses/6.2.02/thread").status_code in (403, 404)
    assert db.scalar(select(Response).join(Question, Question.id == Response.question_id).where(Question.code.in_(["6.2.02", "6.2.03"]))) is None
