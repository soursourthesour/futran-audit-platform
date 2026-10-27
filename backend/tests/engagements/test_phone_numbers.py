"""Contact phone numbers are stored in E.164 (fixes 2026-10-27, item 1e)."""
import pytest

from app.engagements.models import ClientContact
from tests.engagements.helpers import _new, _put
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def aud(db, matrix):
    f = make_org(db, type="futran")
    u = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    db.commit()
    return u


def _phone(db, cid, role="caico"):
    db.expire_all()
    return db.query(ClientContact).filter_by(organization_id=cid, contact_role=role, deleted_at=None).one().phone


def test_e164_number_is_stored(client, db, aud):
    login_as(client, db, aud)
    cid = _new(client)["client_id"]
    out = _put(client, cid, "contacts", {"caico": {"name": "Maria Lopez", "phone": "+1 (212) 555-0100"}})
    assert out["errors"] == []
    assert _phone(db, cid) == "+12125550100"


def test_number_without_country_code_is_refused(client, db, aud):
    login_as(client, db, aud)
    cid = _new(client)["client_id"]
    _put(client, cid, "contacts", {"caico": {"name": "Maria Lopez", "phone": "+442071838750"}})
    out = _put(client, cid, "contacts", {"caico": {"name": "Maria Lopez", "phone": "212 555 0100"}})
    assert out["errors"] == [{"field": "contacts.caico.phone", "message": "Enter the number with its country code, for example +1 212 555 0100."}]
    assert _phone(db, cid) == "+442071838750"
    for bad in ("+0 123", "+1", "+1234567890123456", "+1 212 555 0100 ext 4"):
        out = _put(client, cid, "contacts", {"caico": {"phone": bad}})
        assert out["errors"], bad


def test_an_older_number_without_a_code_still_loads_and_saves_unchanged(client, db, aud):
    login_as(client, db, aud)
    cid = _new(client)["client_id"]
    _put(client, cid, "contacts", {"caico": {"name": "Maria Lopez"}})
    c = db.query(ClientContact).filter_by(organization_id=cid, contact_role="caico").one()
    c.phone = "212-555-0100"  # stored before country codes were required
    db.commit()
    w = client.get(f"/api/v1/clients/{cid}/wizard").json()
    assert w["contacts"]["caico"]["phone"] == "212-555-0100"
    out = _put(client, cid, "contacts", {"caico": {"name": "Maria Lopez", "phone": "212-555-0100"}})
    assert out["errors"] == []
    assert _phone(db, cid) == "212-555-0100"
    out = _put(client, cid, "contacts", {"caico": {"name": "Maria Lopez", "phone": ""}})
    assert out["errors"] == [] and _phone(db, cid) is None
