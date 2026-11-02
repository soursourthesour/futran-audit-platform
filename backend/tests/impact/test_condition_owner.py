"""A condition's owner may sit outside the project's department: they see the project read-only and mark their own
condition met; nothing else opens up to them."""
from tests.factories import login_as
from tests.impact.test_projects_api import _review, _submit, abc, chatbot  # noqa: F401


def _approved_with_condition_for(client, db, abc, owner):
    p = _submit(client, db, abc, chatbot(abc))
    _review(client, db, abc, p["id"], "dana", "department")
    _review(client, db, abc, p["id"], "priya", "dpo")
    login_as(client, db, abc["maria"])
    r = client.post(f"/api/v1/projects/{p['id']}/decide", json={"decision": "approved_with_conditions", "note": "ok",
                    "conditions": [{"text": "HR updates the notice", "owner_user_id": abc[owner].id}]})
    assert r.status_code == 200, r.text
    return p["id"], r.json()["conditions"][0]["id"]


def test_a_condition_owner_outside_the_department_sees_the_project_and_marks_it_met(client, db, abc):
    pid, cid = _approved_with_condition_for(client, db, abc, "hal")
    login_as(client, db, abc["hal"])
    r = client.get(f"/api/v1/projects/{pid}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["conditions"][0]["can_mark_met"] is True and d["conditions"][0]["can_close"] is False
    assert not any(d[k] for k in ("can_edit", "can_review_department", "can_review_dpo", "can_decide", "can_request_opinion"))
    r = client.post(f"/api/v1/projects/{pid}/conditions/{cid}/met", json={"note": "Notice updated on the careers site."})
    assert r.status_code == 200 and r.json()["status"] == "met"
    assert client.post(f"/api/v1/projects/{pid}/conditions/{cid}/close", json={}).status_code == 403
    assert client.patch(f"/api/v1/projects/{pid}", json={"purpose": "Changed"}).status_code in (403, 409)


def test_someone_outside_the_department_who_owns_no_condition_still_cannot_see_it(client, db, abc):
    pid, _cid = _approved_with_condition_for(client, db, abc, "priya")
    login_as(client, db, abc["hal"])
    assert client.get(f"/api/v1/projects/{pid}").status_code == 404
