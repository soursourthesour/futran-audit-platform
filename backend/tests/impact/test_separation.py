"""Separation of duties on new AI projects (spec §6 rule 2): nobody reviews or decides a project they prepared
(started, edited or submitted)."""
from tests.factories import login_as
from tests.impact.test_projects_api import _review, _submit, abc, chatbot  # noqa: F401


def _decide(client, db, abc, pid, who):
    login_as(client, db, abc[who])
    return client.post(f"/api/v1/projects/{pid}/decide", json={"decision": "approved", "note": "ok"})


def test_the_department_lead_cannot_review_their_own_submission(client, db, abc):
    p = _submit(client, db, abc, chatbot(abc), who="dana")
    login_as(client, db, abc["dana"])
    assert client.get(f"/api/v1/projects/{p['id']}").json()["can_review_department"] is False
    assert _review(client, db, abc, p["id"], "dana", "department").status_code == 403


def test_the_department_lead_reviews_a_contributors_submission(client, db, abc):
    p = _submit(client, db, abc, chatbot(abc), who="cole")
    assert _review(client, db, abc, p["id"], "dana", "department").status_code == 200


def test_whoever_started_the_project_cannot_decide_it(client, db, abc):
    login_as(client, db, abc["maria"])
    pid = client.post("/api/v1/projects", json=chatbot(abc)).json()["id"]
    login_as(client, db, abc["cole"])
    assert client.post(f"/api/v1/projects/{pid}/submit").status_code == 200
    _review(client, db, abc, pid, "dana", "department")
    _review(client, db, abc, pid, "priya", "dpo")
    login_as(client, db, abc["maria"])
    assert client.get(f"/api/v1/projects/{pid}").json()["can_decide"] is False
    assert _decide(client, db, abc, pid, "maria").status_code == 403
    assert _decide(client, db, abc, pid, "omar").status_code == 200


def test_whoever_edited_the_project_cannot_decide_it(client, db, abc):
    login_as(client, db, abc["cole"])
    pid = client.post("/api/v1/projects", json=chatbot(abc)).json()["id"]
    login_as(client, db, abc["maria"])
    assert client.patch(f"/api/v1/projects/{pid}", json={"purpose": "Answer questions about orders, refunds and delivery."}).status_code == 200
    login_as(client, db, abc["cole"])
    assert client.post(f"/api/v1/projects/{pid}/submit").status_code == 200
    _review(client, db, abc, pid, "dana", "department")
    _review(client, db, abc, pid, "priya", "dpo")
    assert _decide(client, db, abc, pid, "maria").status_code == 403
    assert _decide(client, db, abc, pid, "omar").status_code == 200
