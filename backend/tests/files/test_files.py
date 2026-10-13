import hashlib
import re

import pytest

from app.audit_log.models import AuditLog
from app.core.errors import Invalid
from app.engagements.models import EngagementTeam
from app.engagements.service import create_engagement
from app.files.service import upload
from app.files.storage import get_storage
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def world(db, settings, tmp_path):
    settings.file_store = f"local:{tmp_path}"
    f = make_org(db, type="futran")
    aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@f.test")
    a = make_org(db, name="ABC Corp")
    b = make_org(db, name="XYZ Ltd")
    caico_a = make_user(db, a, roles=["caico"], name="Maria Lopez", email="maria@abc.test")
    caico_b = make_user(db, b, roles=["caico"], name="Ben Other", email="ben@xyz.test")
    e = create_engagement(db, aud, a, name="ABC audit")
    e.status = "initiated"  # clients see an engagement only after it is sent
    db.add(EngagementTeam(organization_id=a.id, engagement_id=e.id, user_id=aud.id, role="auditor"))
    db.flush()
    return {"aud": aud, "a": a, "b": b, "caico_a": caico_a, "caico_b": caico_b, "e": e}


def test_upload_records_sha256(db, settings, world):
    data = b"model card v3"
    f = upload(db, settings, world["caico_a"], data=data, filename="Model card.pdf", content_type="application/pdf", organization_id=world["a"].id, engagement_id=world["e"].id, linked_type="evidence", linked_id="x")
    assert f.sha256 == hashlib.sha256(data).hexdigest() and f.size == len(data) and f.scan_status == "not_scanned"
    assert re.fullmatch(rf"{world['a'].id}/\d{{4}}/[0-9a-f-]{{36}}-Model_card\.pdf", f.storage_key)
    assert get_storage(settings).get(f.storage_key) == data


def test_upload_rejects_over_50mb(db, settings, world):
    with pytest.raises(Invalid) as exc:
        upload(db, settings, world["caico_a"], data=b"x" * (50 * 1024 * 1024 + 1), filename="big.pdf", content_type="application/pdf", organization_id=world["a"].id)
    assert "50 MB" in exc.value.detail


def test_upload_rejects_unsupported_type_and_infected(db, settings, world):
    with pytest.raises(Invalid):
        upload(db, settings, world["caico_a"], data=b"MZ", filename="setup.exe", content_type="application/octet-stream", organization_id=world["a"].id)
    eicar = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    with pytest.raises(Invalid) as exc:
        upload(db, settings, world["caico_a"], data=eicar, filename="notes.txt", content_type="text/plain", organization_id=world["a"].id)
    assert "virus" in exc.value.detail.lower()


def test_storage_rejects_path_traversal(db, settings, world):
    f = upload(db, settings, world["caico_a"], data=b"x", filename="../../etc/passwd.txt", content_type="text/plain", organization_id=world["a"].id)
    assert ".." not in f.storage_key and f.filename == "passwd.txt"
    with pytest.raises(ValueError):
        get_storage(settings).get("../outside")


def test_file_download_cross_tenant_404(client, db, settings, world):
    client.app.state.settings = settings
    f = upload(db, settings, world["caico_a"], data=b"policy", filename="policy.pdf", content_type="application/pdf", organization_id=world["a"].id, engagement_id=world["e"].id, linked_type="evidence", linked_id="g1")
    db.commit()
    login_as(client, db, world["caico_b"])
    assert client.get(f"/api/v1/files/{f.id}").status_code == 404
    login_as(client, db, world["caico_a"])
    r = client.get(f"/api/v1/files/{f.id}")
    assert r.status_code == 200 and r.content == b"policy"
    assert 'attachment; filename="policy.pdf"' in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_evidence_view_audited(client, db, settings, world):
    client.app.state.settings = settings
    f = upload(db, settings, world["caico_a"], data=b"bias report", filename="bias.pdf", content_type="application/pdf", organization_id=world["a"].id, engagement_id=world["e"].id, linked_type="evidence", linked_id="ev1")
    db.commit()
    login_as(client, db, world["aud"])
    assert client.get(f"/api/v1/files/{f.id}").status_code == 200
    logs = db.query(AuditLog).filter_by(action="file.view", object_id=f.id).all()
    assert len(logs) == 1 and logs[0].actor_id == world["aud"].id
