import pytest

from app.engagements.models import Engagement
from app.signoffs.models import Signature, SignOff
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import APPROVAL


@pytest.fixture
def sent(client, db, people, submitted):
    cid, e = submitted()
    login_as(client, db, people["chief"])
    client.get(f"/api/v1/clients/{cid}/package")
    assert client.post(f"/api/v1/clients/{cid}/approve", json=APPROVAL).status_code == 200
    maria = db.query(User).filter_by(email="maria@abc.test").one()
    maria.status = "active"
    db.commit()
    so = db.query(SignOff).filter_by(engagement_id=e.id, number=1).one()
    return cid, e, maria, so


def test_typed_name_must_match(client, db, sent):
    cid, e, maria, so = sent
    login_as(client, db, maria)
    r = client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "M. Lopez"})
    assert r.status_code == 422 and "Maria Lopez" in r.json()["errors"][0]["message"]
    r = client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "  maria   LOPEZ "})
    assert r.status_code == 200, r.text
    sig = db.query(Signature).filter_by(sign_off_id=so.id).one()
    assert sig.typed_name == "maria LOPEZ" and len(sig.document_sha256) == 64 and sig.role == "caico"


def test_signoff1_requires_both_parties(client, db, people, sent):
    cid, e, maria, so = sent
    login_as(client, db, maria)
    view = client.get(f"/api/v1/signoffs/{so.id}").json()
    assert view["can_sign"] is True and [p["role"] for p in view["parties"]] == ["caico", "chief_auditor"]
    assert view["document"]["pdf_file_id"]
    client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Maria Lopez"})
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Maria Lopez"}).status_code == 409  # already signed
    db.expire_all()
    assert db.get(SignOff, so.id).status == "pending" and db.get(Engagement, e.id).stage == 1
    # the preparer (an auditor) cannot sign for Futran
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Alex Auditor"}).status_code == 403
    login_as(client, db, people["chief"])
    assert client.get(f"/api/v1/signoffs/{so.id}").json()["can_sign"] is True
    r = client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Cara Chief"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    db.expire_all()
    assert db.get(Engagement, e.id).stage == 2 and db.get(Engagement, e.id).status == "in_progress"


def test_client_checklist(client, db, sent):
    cid, e, maria, so = sent
    login_as(client, db, maria)
    chk = client.get("/api/v1/me/initiation").json()
    assert [i["key"] for i in chk["items"]] == ["guide", "sign", "nominate", "departments", "users", "notice", "governance"]
    assert chk["done"] == 0 and chk["total"] == 7 and chk["requested_by"]
    assert client.post("/api/v1/me/initiation/items/guide/done").status_code == 200
    assert client.post("/api/v1/me/initiation/items/sign/done").status_code == 422  # signing is done by signing
    client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Maria Lopez"})
    chk = client.get("/api/v1/me/initiation").json()
    assert {i["key"]: i["done"] for i in chk["items"]}["sign"] is True and chk["done"] == 2
    assert chk["chief_auditor"] == "Cara Chief"
