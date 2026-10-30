"""Directory sync and reply sync (spec §26.2)."""
from datetime import timedelta

import pytest

from app.attestation.models import Attestation
from app.core.clock import set_now, utcnow
from app.mail import tokens
from app.mail.directory import configure, run_directory_sync, sync_due
from app.mail.groups import add_member, create_group
from app.mail.models import AdminLogEntry, DirectoryGroup, DirectoryPerson, MailConnection, MailGroupMember, MailRecipient, MailReply, UserMailConnection
from app.mail.people import find_person
from app.mail.providers import DirectoryEntry, DirectoryGroupEntry
from app.mail.providers.fake import FAKE
from app.mail.replies import run_reply_sync
from app.mail.sending import send_to_groups
from tests.factories import make_department, make_org, make_user


@pytest.fixture(autouse=True)
def _reset():
    FAKE.reset()
    yield
    set_now(None)


@pytest.fixture
def org(db):
    make_org(db, type="futran")
    return make_org(db, type="client")


@pytest.fixture
def conn(db, settings, org):
    c = MailConnection(organization_id=org.id, owner="client", provider="microsoft365", mailbox_address="ai-governance@abc.com", status="connected", sender_mode="own")
    tokens.store(settings, c, {"fake": True, "kind": "app", "domains": ["abc.com"]})
    db.add(c)
    db.flush()
    return c


def _dir(people, groups=None):
    FAKE.set_directory("abc.com", people, groups or [DirectoryGroupEntry("g-all", "All Staff"), DirectoryGroupEntry("g-hr", "HR Team")])


def _p(i, name, dept="Human Resources", groups=("g-all",), **kw):
    return DirectoryEntry(directory_id=f"u{i}", email=f"{name.split()[0].lower()}@abc.com", name=name, department=dept, group_ids=list(groups), **kw)


def test_directory_sync_imports_people_departments_and_groups(db, settings, org, conn):
    hr = make_department(db, org, name="Human Resources")
    _dir([_p(1, "Ana Ruiz", groups=("g-all", "g-hr")), _p(2, "Ben Ode", dept="Finance"), _p(3, "Gus Guest", is_guest=True)])
    ds = configure(db, None, conn, {"schedule": "daily"})
    run_directory_sync(db, settings, ds)
    ana = find_person(db, org.id, "ana@abc.com")
    assert ana.department_id == hr.id and ana.source == "directory" and set(ana.directory_group_ids) == {"g-all", "g-hr"}
    assert find_person(db, org.id, "gus@abc.com") is None  # guests are left out unless asked for
    assert ds.people == 2 and ds.joined == 2 and ds.status == "ok"
    assert "Finance" in ds.report["unmatched_departments"]
    assert {g.name for g in db.query(DirectoryGroup).filter_by(organization_id=org.id)} == {"All Staff", "HR Team"}
    assert db.query(AdminLogEntry).filter_by(organization_id=org.id, category="directory").count() == 1


def test_scope_group_limits_who_is_imported(db, settings, org, conn):
    _dir([_p(1, "Ana Ruiz"), _p(2, "Ben Ode", groups=("g-hr",))])
    ds = configure(db, None, conn, {"scope_group": "g-all"})
    run_directory_sync(db, settings, ds)
    assert find_person(db, org.id, "ben@abc.com") is None and find_person(db, org.id, "ana@abc.com") is not None


def test_leavers_are_removed_from_groups_but_their_answers_are_kept(db, settings, org, conn):
    hr = make_department(db, org, name="Human Resources")
    admin = make_user(db, org, roles=["client_admin"], name="Cleo Admin", email="cleo@abc.com")
    ben_user = make_user(db, org, roles=["contributor"], name="Ben Ode", email="ben@abc.com")
    db.add(UserMailConnection(organization_id=org.id, user_id=ben_user.id, provider="microsoft365", mailbox="ben@abc.com", status="connected"))
    _dir([_p(1, "Ana Ruiz"), _p(2, "Ben Ode")])
    ds = configure(db, None, conn, {})
    run_directory_sync(db, settings, ds)
    ben = find_person(db, org.id, "ben@abc.com")
    g = create_group(db, admin, org.id, name="AI-EUAct", source="manual")
    add_member(db, admin, g, person_id=ben.id)
    from app.engagements.models import Engagement
    from app.attestation.models import AttestationCampaign

    e = Engagement(organization_id=org.id, client_id=org.id, name="Audit", status="active", stage=3)
    db.add(e)
    db.flush()
    c = AttestationCampaign(organization_id=org.id, engagement_id=e.id, policy_version="1.0", launched_at=utcnow(), closes_at=utcnow() + timedelta(days=5), department_ids=[hr.id], link_token="t")
    db.add(c)
    db.flush()
    db.add(Attestation(organization_id=org.id, campaign_id=c.id, engagement_id=e.id, respondent_name="Ben Ode", respondent_email="ben@abc.com", department_id=hr.id, uses_ai=False,
                       submitted_at=utcnow()))
    db.flush()
    _dir([_p(1, "Ana Ruiz", dept="Finance")])  # Ben left; Ana moved department
    run_directory_sync(db, settings, ds)
    assert ben.status == "left" and ben.left_at is not None
    assert db.query(MailGroupMember).filter_by(group_id=g.id, deleted_at=None).count() == 0
    assert db.query(Attestation).filter_by(respondent_email="ben@abc.com").count() == 1
    assert db.query(UserMailConnection).filter_by(user_id=ben_user.id).one().status == "disconnected"
    assert (ds.left, ds.changed) == (1, 1)


def test_disabled_accounts_count_as_leavers(db, settings, org, conn):
    _dir([_p(1, "Ana Ruiz"), _p(2, "Ben Ode", enabled=False)])
    run_directory_sync(db, settings, configure(db, None, conn, {}))
    assert find_person(db, org.id, "ben@abc.com") is None or find_person(db, org.id, "ben@abc.com").status == "left"


def test_sync_runs_daily_by_default(db, settings, org, conn):
    ds = configure(db, None, conn, {})
    assert sync_due(ds, utcnow())
    _dir([_p(1, "Ana Ruiz")])
    run_directory_sync(db, settings, ds)
    assert not sync_due(ds, utcnow() + timedelta(hours=23))
    assert sync_due(ds, utcnow() + timedelta(hours=24, minutes=1))


def _sent(db, settings, org, conn):
    admin = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com")
    _dir([_p(1, "Ana Ruiz"), _p(2, "Ben Ode")])
    run_directory_sync(db, settings, configure(db, None, conn, {}))
    g = create_group(db, admin, org.id, name="Two", source="manual")
    for e in ("ana@abc.com", "ben@abc.com"):
        add_member(db, admin, g, person_id=find_person(db, org.id, e).id)
    return send_to_groups(db, settings, admin, organization_id=org.id, group_ids=[g.id], template_key="dept_head_approval")


def test_replies_on_platform_threads_are_attached_and_bounces_update_status(db, settings, org, conn):
    s = _sent(db, settings, org, conn)
    ana = db.query(MailRecipient).filter_by(send_id=s.id, email="ana@abc.com").one()
    ben = db.query(MailRecipient).filter_by(send_id=s.id, email="ben@abc.com").one()
    ref = [m.message.subject for m in FAKE.sent][0].rsplit("[", 1)[1].rstrip("]")
    FAKE.add_reply(ana.provider_thread_id, from_address="ana@abc.com", subject=f"RE: Please approve [{ref}]", body="Approved from my side.")
    FAKE.add_reply(ana.provider_thread_id, from_address="ana@abc.com", subject="Unrelated subject", body="no reference")
    FAKE.add_reply(ben.provider_thread_id, from_address="postmaster@abc.com", subject=f"Undeliverable: Please approve [{ref}]", body="could not be delivered")
    assert run_reply_sync(db, settings, utcnow()) == 2
    assert run_reply_sync(db, settings, utcnow()) == 0  # not stored twice
    replies = db.query(MailReply).all()
    assert {r.kind for r in replies} == {"reply", "bounce"}
    assert ben.status == "bounced"


def test_out_of_office_replies_are_marked_and_do_not_count_as_answers(db, settings, org, conn):
    s = _sent(db, settings, org, conn)
    ana = db.query(MailRecipient).filter_by(send_id=s.id, email="ana@abc.com").one()
    ref = FAKE.sent[0].message.subject.rsplit("[", 1)[1].rstrip("]")
    FAKE.add_reply(ana.provider_thread_id, from_address="ana@abc.com", subject=f"Automatic reply: Please approve [{ref}]", body="I am away", auto_reply=True)
    run_reply_sync(db, settings, utcnow())
    assert ana.out_of_office is True and ana.status == "sent"
    assert db.query(MailReply).one().kind == "out_of_office"
