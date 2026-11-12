"""10 Nov feedback U2 and F2. U2: every client home shows the nine audit stages of the client's current engagement as a
timeline (done, current, upcoming, with dates where known). F2: the Chief Auditor gets a role home, since the Dashboard
moves into the homes and /audits now redirects to each person's home."""
from sqlalchemy import select

from tests.factories import login_as, make_org, make_user

ABC = "abccorp.example"
CLIENT_PEOPLE = [f"maria.lopez@{ABC}", f"sam.okafor@{ABC}", f"robert.chen@{ABC}", f"daniel.kim@{ABC}", f"priya.shah@{ABC}", f"tom.reyes@{ABC}"]


def _get(c, path, status=200):
    r = c.get(f"/api/v1{path}")
    assert r.status_code == status, (path, r.status_code, r.text)
    return r.json()


def test_stage_timeline_for_a_client_at_stage_6(as_user):
    d = _get(as_user(f"maria.lopez@{ABC}"), "/me/stages")
    assert d["engagement"]["stage"] == 6
    stages = d["stages"]
    assert [s["number"] for s in stages] == list(range(1, 10))
    assert [s["name"] for s in stages] == ["Onboarding", "Setup", "Discovery", "Client review", "Fieldwork", "Futran QA", "Response", "Final report", "Remediation"]
    assert [s["state"] for s in stages] == ["done"] * 5 + ["current"] + ["upcoming"] * 3
    assert all(s["summary"] for s in stages)
    # dates where known: when each finished stage started and ended, and when the current one started
    assert stages[0]["started_on"] and stages[4]["finished_on"] and stages[5]["started_on"]
    assert stages[5]["finished_on"] is None and stages[6]["started_on"] is None and stages[6]["finished_on"] is None
    # nothing internal: no open-item lists, sign-off signers or audit log events
    assert set(stages[0]) == {"number", "name", "state", "started_on", "finished_on", "target_on", "summary"}


def test_every_client_role_sees_the_timeline(as_user):
    for email in CLIENT_PEOPLE:
        d = _get(as_user(email), "/me/stages")
        assert len(d["stages"]) == 9, email
        assert sum(s["state"] == "current" for s in d["stages"]) == 1, email


def test_timeline_follows_the_client_s_own_engagement(as_user):
    d = _get(as_user("katrin.vogel@meridian.example"), "/me/stages")
    assert [s["number"] for s in d["stages"] if s["state"] == "current"] == [3]
    assert [s["state"] for s in d["stages"][:2]] == ["done", "done"]


def test_no_engagement_yet_gives_an_empty_timeline(world):
    from fastapi.testclient import TestClient

    db = world["db"]
    org = make_org(db, name="Newco Ltd")
    u = make_user(db, org, roles=["caico"], name="New CAICO", email="caico@newco.example")
    db.commit()
    with TestClient(world["app"]) as c:
        login_as(c, db, u)
        d = _get(c, "/me/stages")
    assert d == {"engagement": None, "stages": []}


def test_futran_staff_have_no_client_timeline(as_user):
    _get(as_user("chief@futran.demo"), "/me/stages", status=404)


def test_chief_auditor_lands_on_the_chief_auditor_home(as_user):
    me = _get(as_user("chief@futran.demo"), "/auth/me")
    assert me["home"] == "/staff/chief"
    assert "view_chief_home" in me["actions"]
    for email in ("admin@futran.demo", "auditor1@futran.demo", "qa@futran.demo", "sales@futran.demo"):
        assert "view_chief_home" not in _get(as_user(email), "/auth/me")["actions"], email


def test_engagement_dates_are_targets_for_stages_not_yet_finished(world, as_user):
    from datetime import date

    from app.engagements.models import Engagement

    db = world["db"]
    e = db.scalar(select(Engagement).where(Engagement.client_id == world["ids"]["abc"]))
    before = (e.draft_report_target, e.final_report_target)
    e.draft_report_target, e.final_report_target = date(2026, 12, 1), date(2027, 1, 15)
    db.commit()
    try:
        s = {x["number"]: x for x in _get(as_user(f"maria.lopez@{ABC}"), "/me/stages")["stages"]}
        assert s[6]["target_on"] == "2026-12-01" and s[8]["target_on"] == "2027-01-15"
        assert s[2]["target_on"] is None  # no target for a stage without a planned date
    finally:
        e.draft_report_target, e.final_report_target = before
        db.commit()
