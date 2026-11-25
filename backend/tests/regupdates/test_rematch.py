"""BUG-08: regulatory updates reach clients set up before the law library, and earlier updates are re-matched when a
client's applicability or geography arrives later."""
import pytest
from sqlalchemy import select

from app.engagements.models import ClientLocation
from app.impact.models import ReassessmentTrigger
from app.register.models import RegisterSystem
from app.regmaster.models import ClientGeography, ClientLawApplicability
from app.regupdates.models import RegulatoryAlert
from tests.factories import make_org
from tests.regupdates.conftest import nyc_enforcement, publish


@pytest.fixture
def world(world, db):
    """As on a live install: the regulatory master (scope tests, roles) is seeded."""
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(db)
    db.commit()
    return world


def _meridian(db, w, with_location=True):
    """A client set up before the law library: a New York City site, a hiring system, no geographies, no applicability."""
    org = make_org(db, name="Meridian Bank")
    if with_location:
        db.add(ClientLocation(organization_id=org.id, site_name="Head office", city="New York", subdivision_code="US-NY", country_code="US",
                              jurisdiction_ids=[w["j"]["US-NYC"].id, w["j"]["US-NY"].id, w["j"]["US"].id]))
    s = RegisterSystem(organization_id=org.id, reference="AIS-001", name="Applicant ranking", type="vendor_app", sourcing="vendor",
                       purpose="Ranks job applicants before recruiter review", decision_impact="consequential", stage="live")
    db.add(s)
    db.commit()
    assert db.scalar(select(ClientGeography.id).where(ClientGeography.organization_id == org.id)) is None
    assert db.scalar(select(ClientLawApplicability.id).where(ClientLawApplicability.organization_id == org.id)) is None
    return org, s


def _alert(db, uid, org_id):
    return db.scalar(select(RegulatoryAlert).where(RegulatoryAlert.update_id == uid, RegulatoryAlert.organization_id == org_id, RegulatoryAlert.deleted_at.is_(None)))


def test_publishing_builds_missing_applicability_first_so_older_clients_are_matched(client, db, world):
    org, s = _meridian(db, world)
    d = publish(client, db, world, nyc_enforcement(world))
    a = _alert(db, d["id"], org.id)
    assert a is not None and a.affected_system_ids == [s.id]
    assert db.scalar(select(ClientLawApplicability.id).where(ClientLawApplicability.organization_id == org.id)) is not None
    assert db.scalar(select(ReassessmentTrigger.id).where(ReassessmentTrigger.register_system_id == s.id, ReassessmentTrigger.source_ref == f"update:{d['id']}")) is not None
    assert {a.organization_id for a in db.scalars(select(RegulatoryAlert).where(RegulatoryAlert.update_id == d["id"]))} == {world["abc"].id, org.id}


def test_an_earlier_update_is_matched_when_the_client_gains_a_geography(client, db, world):
    from app.regmaster import engine

    org, s = _meridian(db, world, with_location=False)
    d = publish(client, db, world, nyc_enforcement(world))
    assert _alert(db, d["id"], org.id) is None  # nothing tells the platform where Meridian operates yet
    engine.add_geography(db, org.id, world["j"]["US-NYC"].id, "office", world["chief"].id)
    db.commit()
    a = _alert(db, d["id"], org.id)
    assert a is not None and a.affected_system_ids == [s.id]
    # review 11-25 #7: a late re-match adds the alert but raises no reassessment trigger, which would reopen verified
    # audit answers for an update published before; the alert asks for review and a person raises a trigger if needed
    assert db.scalar(select(ReassessmentTrigger.id).where(ReassessmentTrigger.register_system_id == s.id, ReassessmentTrigger.source_ref == f"update:{d['id']}")) is None
    engine.run(db, org.id)  # running again adds nothing
    assert len(db.scalars(select(RegulatoryAlert).where(RegulatoryAlert.update_id == d["id"], RegulatoryAlert.organization_id == org.id)).all()) == 1


def test_an_update_on_a_law_is_matched_when_the_law_comes_into_scope_later(client, db, world):
    org, _ = _meridian(db, world, with_location=False)
    d = publish(client, db, world, nyc_enforcement(world, regulation_id=world["ll144"].id, jurisdiction_id=None, affected_features=[]))
    assert _alert(db, d["id"], org.id) is None
    from app.regmaster import engine

    engine.add_geography(db, org.id, world["j"]["US-NYC"].id, "office", world["chief"].id)
    db.commit()
    row = db.scalar(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org.id, ClientLawApplicability.regulation_id == world["ll144"].id))
    assert row is not None and row.in_scope
    assert _alert(db, d["id"], org.id) is not None


def test_the_publisher_is_told_which_clients_cannot_be_matched(client, db, world):
    org, _ = _meridian(db, world, with_location=False)
    d = publish(client, db, world, nyc_enforcement(world))
    assert [c["name"] for c in d["unmatched_clients"]] == ["Meridian Bank"]
    assert "geograph" in d["unmatched_clients"][0]["reason"].lower()
    from app.audit_log.models import AuditLog

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "regupdate.publish"))
    assert entry.after["unmatched_clients"] == [org.id]


def test_rematch_all_catches_up_clients_whose_applicability_already_exists(client, db, world):
    """The laptop case: ABC's applicability was built by opening its page, after the updates were published."""
    from app.regupdates.service import rematch_all

    org, s = _meridian(db, world, with_location=False)
    d = publish(client, db, world, nyc_enforcement(world))
    db.add(ClientGeography(organization_id=org.id, jurisdiction_id=world["j"]["US-NYC"].id, basis="office"))  # written directly: no hook runs
    db.commit()
    assert _alert(db, d["id"], org.id) is None
    added = rematch_all(db)
    db.commit()
    assert added == {org.id: 1}
    assert _alert(db, d["id"], org.id).affected_system_ids == [s.id]
    assert rematch_all(db) == {}


def test_withdrawn_and_watch_updates_are_not_rematched(client, db, world):
    from app.regmaster import engine

    org, _ = _meridian(db, world, with_location=False)
    w = publish(client, db, world, nyc_enforcement(world, watch=True, change_type="pending_bill", title="A bill"))
    engine.add_geography(db, org.id, world["j"]["US-NYC"].id, "office", world["chief"].id)
    db.commit()
    assert _alert(db, w["id"], org.id) is None


def test_a_new_geography_alone_triggers_a_rematch(db, world, monkeypatch):
    """No law changes scope (New York State adds nothing to New York City), yet the client is matched again."""
    from app.regmaster import engine
    from app.regupdates import service

    org, _ = _meridian(db, world, with_location=False)
    engine.add_geography(db, org.id, world["j"]["US-NYC"].id, "office", None)
    calls = []
    monkeypatch.setattr(service, "rematch_org", lambda db, org_id, actor_id=None: calls.append(org_id) or [])
    engine.run(db, org.id)
    assert calls == []  # nothing changed
    engine.add_geography(db, org.id, world["j"]["US-NY"].id, "office", None)
    assert calls == [org.id]


def test_rematch_dry_run_saves_nothing(client, db, world, monkeypatch, capsys):
    """BUG-K03: the dry run of `rematch-reg-updates` said "nothing saved" but kept the applicability and geographies it
    built. On SQLite a savepoint opened with no transaction open becomes the transaction, and releasing it commits."""
    import types

    from sqlalchemy import func

    from app import cli

    org, s = _meridian(db, world)
    counts = lambda: (db.scalar(select(func.count(ClientLawApplicability.id))), db.scalar(select(func.count(ClientGeography.id))),  # noqa: E731
                      db.scalar(select(func.count(RegulatoryAlert.id))))
    db.commit()
    before = counts()
    monkeypatch.setattr(cli, "_session", lambda: (None, db))
    assert cli.cmd_rematch_reg_updates(types.SimpleNamespace(apply=False)) == 0
    assert "Dry run: nothing saved." in capsys.readouterr().out
    db.expire_all()
    assert counts() == before
    assert db.scalar(select(ClientLawApplicability.id).where(ClientLawApplicability.organization_id == org.id)) is None
