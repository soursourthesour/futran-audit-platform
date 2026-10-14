import pytest

from sqlalchemy import select

from app.engagements.models import Engagement
from app.tenancy.models import User
from tests.engagements.helpers import _new, complete
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def people(db, matrix):
    from app.reference.catalogs import load_catalogs
    from app.reference.templates import load_templates

    load_templates(db)
    load_catalogs(db)
    f = make_org(db, type="futran")
    p = {
        "aud": make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test"),
        "aud2": make_user(db, f, roles=["auditor"], name="Bea Auditor", email="bea@futran.test"),
        "chief": make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test"),
        "chief2": make_user(db, f, roles=["chief_auditor"], name="Dan Chief", email="dan@futran.test"),
        "em": make_user(db, f, roles=["engagement_manager"], name="Eli Manager", email="eli@futran.test"),
    }
    db.commit()
    return p


@pytest.fixture
def submitted(client, db, people, settings, tmp_path):
    """A complete engagement submitted by Alex for Cara's approval. Returns (client_id, engagement)."""
    settings.file_store = f"local:{tmp_path}"
    client.app.state.settings = settings

    def make(admin_same=True):
        login_as(client, db, people["aud"])
        cid = _new(client)["client_id"]
        complete(client, cid, people, admin_same=admin_same)
        r = client.post(f"/api/v1/clients/{cid}/submit")
        assert r.status_code == 200, r.text
        db.expire_all()
        return cid, db.query(Engagement).filter_by(client_id=cid).one()

    return make


APPROVAL = {"client_message": "We look forward to working with you.", "checklist": {"scope_ok": True, "no_conflict": True, "letter_previewed": True}}


@pytest.fixture
def live(client, db, people, submitted):
    """An approved engagement with Maria (CAICO and Client Admin) active."""
    cid, e = submitted()
    login_as(client, db, people["chief"])
    client.get(f"/api/v1/clients/{cid}/package")
    assert client.post(f"/api/v1/clients/{cid}/approve", json=APPROVAL).status_code == 200
    maria = db.scalar(select(User).where(User.email == "maria@abc.test"))
    maria.status = "active"
    db.commit()
    from app.signoffs.models import SignOff

    so = db.scalar(select(SignOff).where(SignOff.engagement_id == e.id))
    login_as(client, db, maria)
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Maria Lopez"}).status_code == 200
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Cara Chief"}).status_code == 200
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 2
    return cid, e, maria
