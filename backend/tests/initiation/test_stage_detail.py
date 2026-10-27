"""Stage detail panel behind each step of the stage tracker (fixes 2026-10-27, item 2c)."""
from sqlalchemy import select

from app.tenancy.models import User
from tests.factories import login_as


def _stage(client, cid, n):
    r = client.get(f"/api/v1/clients/{cid}/stages/{n}")
    assert r.status_code == 200, r.text
    return r.json()


def test_completed_stage_shows_who_signed_and_when(client, db, people, live):
    cid, e, maria = live
    s = _stage(client, cid, 1)
    assert s["number"] == 1 and s["name"] == "Onboarding" and s["state"] == "done"
    assert s["entered_at"] and s["exited_at"]
    (so,) = s["sign_offs"]
    assert so["number"] == 1 and so["title"] == "Engagement letter and scope" and so["status_label"] == "Approved"
    assert so["preparer"] == "Alex Auditor"
    signers = {x["role_label"]: x for x in so["signers"]}
    assert signers["Chief AI Compliance Officer"]["signed_by"] == "Maria Lopez" and signers["Chief AI Compliance Officer"]["signed_at"]
    assert signers["Chief Auditor"]["signed_by"] == "Cara Chief"
    actions = [ev["action"] for ev in s["events"]]
    assert "engagement.initiated" in actions and "package.send" in actions and "signoff.approved" in actions and "engagement.advance" in actions
    assert "wizard.save" not in actions  # draft edits are not key events
    assert all(ev["at"] and "actor" in ev and "ip" not in ev for ev in s["events"])
    assert s["open"] == []
    assert any(link["to"] == f"/clients/{cid}/documents" or link["to"].startswith(f"/clients/{cid}") for link in s["links"])


def test_current_stage_lists_open_gate_conditions(client, db, people, live):
    cid, e, maria = live
    s = _stage(client, cid, 2)
    assert s["state"] == "current" and s["entered_at"] and s["exited_at"] is None
    assert s["open"] and any("department" in u.lower() for u in s["open"])
    assert s["sign_offs"] == []
    assert any(ev["action"] == "engagement.advance" for ev in s["events"])  # the move into this stage


def test_future_stage_says_what_will_happen(client, db, people, live):
    cid, e, maria = live
    s = _stage(client, cid, 6)
    assert s["state"] == "upcoming" and s["events"] == [] and s["entered_at"] is None
    assert s["summary"] and s["exit"]
    assert [x["number"] for x in s["expected_sign_offs"]] == [5]
    assert s["open"] == []


def test_staff_on_the_team_only(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    assert client.get(f"/api/v1/clients/{cid}/stages/1").status_code == 404
    login_as(client, db, people["aud2"])  # not on this engagement
    assert client.get(f"/api/v1/clients/{cid}/stages/1").status_code == 404
    login_as(client, db, people["aud"])
    assert client.get(f"/api/v1/clients/{cid}/stages/1").status_code == 200
    assert client.get(f"/api/v1/clients/{cid}/stages/10").status_code == 404
