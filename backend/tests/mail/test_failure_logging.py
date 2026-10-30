"""Security review: failed attempts are logged (§26.7) even though the request reports an error."""
import pytest

from app.mail import tokens
from app.mail.models import AdminLogEntry, MailConnection
from app.mail.providers import ProviderError
from app.mail.providers.fake import FAKE, FakeAdapter
from tests.factories import login_as, make_org, make_user


@pytest.fixture(autouse=True)
def _reset():
    FAKE.reset()
    yield
    FAKE.reset()


def _connected(client, db, settings):
    make_org(db, type="futran")
    org = make_org(db, name="ABC")
    admin = make_user(db, org, roles=["client_admin"], email="cleo@abc.com")
    conn = MailConnection(organization_id=org.id, owner="client", provider="microsoft365", mailbox_address="ai@abc.com", status="connected", sender_mode="own")
    tokens.store(settings, conn, {"fake": True, "kind": "app", "domains": ["abc.com"]})
    db.add(conn)
    db.commit()
    login_as(client, db, admin)
    return org


def test_a_failed_test_email_is_logged(client, db, settings):
    org = _connected(client, db, settings)
    FAKE.fail_next = 1
    r = client.post("/api/v1/mail/client/test", json={"to": "it@abc.com"})
    assert r.status_code == 409, r.text
    db.expire_all()
    entry = db.query(AdminLogEntry).filter_by(organization_id=org.id, category="send", action="test").one()
    assert "failed" in entry.summary


def test_a_failed_manual_directory_sync_is_logged(client, db, settings, monkeypatch):
    org = _connected(client, db, settings)

    def down(self, g, **kw):
        raise ProviderError("Directory unavailable.")

    monkeypatch.setattr(FakeAdapter, "list_people", down)
    r = client.post("/api/v1/mail/client/directory/sync")
    assert r.status_code == 409, r.text
    db.expire_all()
    assert db.query(AdminLogEntry).filter_by(organization_id=org.id, category="directory", action="sync_failed").count() == 1
