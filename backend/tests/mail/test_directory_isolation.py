"""Security review I3: a client's directory sync changes only that client's people and users."""
from app.mail import tokens
from app.mail.directory import configure, run_directory_sync
from app.mail.models import MailConnection, UserMailConnection
from app.mail.providers import DirectoryEntry, DirectoryGroupEntry
from app.mail.providers.fake import FAKE
from tests.factories import make_org, make_user


def test_a_leaver_in_a_client_directory_does_not_disconnect_another_organisations_user(db, settings):
    FAKE.reset()
    futran = make_org(db, type="futran")
    auditor = make_user(db, futran, roles=["auditor"], email="alex@futran.test")
    db.add(UserMailConnection(organization_id=futran.id, user_id=auditor.id, provider="microsoft365", mailbox="alex@futran.test", status="connected",
                              token_encrypted="x", token_ref="y"))
    a = make_org(db, name="Client A")
    staff = make_user(db, a, roles=["contributor"], email="guest.leaver@abc.com")
    db.add(UserMailConnection(organization_id=a.id, user_id=staff.id, provider="microsoft365", mailbox="guest.leaver@abc.com", status="connected", token_encrypted="x", token_ref="y"))
    conn = MailConnection(organization_id=a.id, owner="client", provider="microsoft365", mailbox_address="ai@abc.com", status="connected", sender_mode="own")
    tokens.store(settings, conn, {"fake": True, "kind": "app", "domains": ["abc.com"]})
    db.add(conn)
    db.flush()
    groups = [DirectoryGroupEntry("g-all", "All Staff")]
    ana = DirectoryEntry(directory_id="u1", email="ana@abc.com", name="Ana", group_ids=["g-all"])
    guest = DirectoryEntry(directory_id="guest1", email="alex@futran.test", name="Alex (guest)", is_guest=True, group_ids=["g-all"])
    leaver = DirectoryEntry(directory_id="u2", email="guest.leaver@abc.com", name="Lee Leaver", group_ids=["g-all"])
    FAKE.set_directory("abc.com", [ana, guest, leaver], groups)
    ds = configure(db, None, conn, {"include_guests": True})
    run_directory_sync(db, settings, ds)
    FAKE.set_directory("abc.com", [ana], groups)  # the guest and the client's own leaver are gone
    run_directory_sync(db, settings, ds)
    futran_uc = db.query(UserMailConnection).filter_by(user_id=auditor.id).one()
    assert futran_uc.status == "connected" and futran_uc.token_encrypted == "x"  # Futran's user is not the client's to change
    own_uc = db.query(UserMailConnection).filter_by(user_id=staff.id).one()
    assert own_uc.status == "disconnected" and own_uc.token_encrypted is None  # the client's own leaver is disconnected (§27.1)
