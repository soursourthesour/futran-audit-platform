"""Client "What this means for you" (/updates), the deadline calendar and the weekly digest (claim-once, off by default)."""
from datetime import date, datetime

from sqlalchemy import select

from app.mail.models import OutboxMessage
from app.regmaster.models import ClientLawApplicability, LawVersion
from app.regupdates.models import UpdateDigestRun
from app.regupdates.service import calendar, run_weekly_digest
from tests.factories import login_as, make_department, make_user
from tests.regupdates.conftest import nyc_enforcement, publish

MONDAY = datetime(2026, 11, 2, 10, 0)


def test_the_caico_sees_published_updates_for_the_company_with_systems_and_to_dos(client, db, world):
    publish(client, db, world, nyc_enforcement(world))
    publish(client, db, world, nyc_enforcement(world, change_type="pending_bill", watch=True, title="A watch item", affected_features=[]))
    login_as(client, db, world["legal"])
    client.post("/api/v1/reg/updates", json=nyc_enforcement(world, title="An unpublished draft"))
    login_as(client, db, world["maria"])
    r = client.get("/api/v1/updates")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["title"] for i in items] == ["State Comptroller audit finds weak enforcement of the AI hiring law"]
    assert items[0]["systems"][0]["name"] == "Résumé screening"
    assert items[0]["todos"][0]["text"] == "Confirm the bias audit is less than 12 months old"


def test_another_client_sees_nothing_and_futran_cannot_use_the_client_view(client, db, world):
    publish(client, db, world, nyc_enforcement(world))
    nw_caico = make_user(db, world["nw"], roles=["caico"], name="Nora North", email="nora@nw.test")
    login_as(client, db, nw_caico)
    assert client.get("/api/v1/updates").json()["items"] == []
    login_as(client, db, world["chief"])
    assert client.get("/api/v1/updates").status_code == 404


def test_a_department_lead_sees_only_updates_on_their_departments_systems(client, db, world):
    hr = make_department(db, world["abc"], name="Human Resources")
    ops = make_department(db, world["abc"], name="Operations")
    world["screening"].department_id = hr.id
    hal = make_user(db, world["abc"], roles=[("dept_compliance_lead", "department", hr.id)], name="Hal Lead", email="hal@abc.test")
    olga = make_user(db, world["abc"], roles=[("dept_compliance_lead", "department", ops.id)], name="Olga Ops", email="olga@abc.test")
    db.commit()
    publish(client, db, world, nyc_enforcement(world))
    login_as(client, db, hal)
    assert len(client.get("/api/v1/updates").json()["items"]) == 1
    login_as(client, db, olga)
    assert client.get("/api/v1/updates").json()["items"] == []


def test_the_calendar_lists_future_dates_of_laws_in_scope_and_of_published_updates(client, db, world):
    law = world["ll144"]
    v = LawVersion(regulation_id=law.id, version_no=1, status="enacted_not_in_force", effective_on=date(2027, 1, 1), compliance_on=date(2027, 7, 1))
    old = LawVersion(regulation_id=law.id, version_no=0, status="in_force", effective_on=date(2023, 1, 1))
    db.add_all([v, old])
    db.flush()
    db.add(ClientLawApplicability(organization_id=world["abc"].id, regulation_id=law.id, law_version_id=v.id, in_scope=True, reason_text="NYC"))
    db.commit()
    publish(client, db, world, nyc_enforcement(world, change_type="effective_date", title="Obligations begin", effective_on="2027-03-01"))
    rows = calendar(db, [world["abc"].id], on=date(2026, 11, 2))
    assert [(r["date"], r["what"]) for r in rows] == [("2027-01-01", "Takes effect"), ("2027-03-01", "Effective date"), ("2027-07-01", "Compliance date")]
    assert calendar(db, [world["nw"].id], on=date(2026, 11, 2)) == []
    login_as(client, db, world["chief"])
    r = client.get("/api/v1/reg/updates/calendar").json()["rows"]
    assert r[0]["clients"] == [{"id": world["abc"].id, "name": "ABC Corp"}]


def test_the_digest_is_off_until_the_chief_auditor_turns_it_on(client, db, world, settings):
    publish(client, db, world, nyc_enforcement(world))
    assert run_weekly_digest(db, settings, MONDAY) == 0
    login_as(client, db, world["legal"])
    assert client.put(f"/api/v1/reg/updates/digest/{world['abc'].id}", json={"enabled": True}).status_code in (403, 404)
    login_as(client, db, world["chief"])
    assert client.put(f"/api/v1/reg/updates/digest/{world['abc'].id}", json={"enabled": True}).json()["enabled"] is True
    assert run_weekly_digest(db, settings, MONDAY) == 1
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.subject.like("Weekly regulatory digest%")))
    assert msg is not None and "maria@abc.test" in msg.to and "State Comptroller audit" in msg.body_text


def test_the_digest_is_sent_once_a_week_and_only_with_something_new(client, db, world, settings):
    from app.regupdates.service import set_digest

    publish(client, db, world, nyc_enforcement(world))
    set_digest(db, world["chief"], world["abc"].id, True)
    db.commit()
    assert run_weekly_digest(db, settings, MONDAY) == 1
    assert run_weekly_digest(db, settings, datetime(2026, 11, 4, 10, 0)) == 0  # same week: claimed
    assert run_weekly_digest(db, settings, datetime(2026, 11, 9, 10, 0)) == 0  # next week, nothing new
    runs = db.scalars(select(UpdateDigestRun).order_by(UpdateDigestRun.week_start)).all()
    assert [r.status for r in runs] == ["sent", "nothing_new"]


def test_a_withdrawn_update_needs_a_reason_and_disappears_for_the_client(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world))
    assert client.post(f"/api/v1/reg/updates/{d['id']}/withdraw", json={}).status_code == 422
    r = client.post(f"/api/v1/reg/updates/{d['id']}/withdraw", json={"reason": "The audit figures were misquoted."})
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    login_as(client, db, world["maria"])
    assert client.get("/api/v1/updates").json()["items"] == []
