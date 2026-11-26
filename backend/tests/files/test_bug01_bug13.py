"""BUG-13: the size message does not report a measured size. BUG-01: a stored file missing from storage is a clean 410."""
import logging
from pathlib import Path

import pytest

from app.core.errors import Invalid
from app.files.service import StoredFileMissing, read, upload
from tests.factories import login_as
from tests.files.test_files import world  # noqa: F401

MISSING = "The stored file is missing. Ask Futran to upload it again."


def test_the_size_message_does_not_give_a_measured_size(db, settings, world):
    with pytest.raises(Invalid) as exc:
        upload(db, settings, world["caico_a"], data=b"x" * (50 * 1024 * 1024 + 1), filename="big.pdf", content_type="application/pdf", organization_id=world["a"].id)
    assert exc.value.detail == "This file is over the 50 MB limit."


def _upload_then_lose(db, settings, world):
    f = upload(db, settings, world["caico_a"], data=b"%PDF-1.4 letter", filename="letter.pdf", content_type="application/pdf", organization_id=world["a"].id,
               engagement_id=world["e"].id, linked_type="evidence", linked_id="g1")
    db.commit()
    Path(settings.file_store.partition(":")[2], f.storage_key).unlink()
    return f


def test_reading_a_missing_stored_file_raises_a_plain_message_and_logs_it(db, settings, world, caplog):
    f = _upload_then_lose(db, settings, world)
    with caplog.at_level(logging.WARNING), pytest.raises(StoredFileMissing) as exc:
        read(settings, f)
    assert exc.value.status_code == 410 and exc.value.detail == MISSING
    assert isinstance(exc.value, OSError)  # callers that already treat an unreadable file as OSError keep working
    assert any(f.id in r.getMessage() for r in caplog.records)


def test_downloading_a_missing_stored_file_is_a_410_not_a_server_error(client, db, settings, world):
    client.app.state.settings = settings
    f = _upload_then_lose(db, settings, world)
    login_as(client, db, world["caico_a"])
    r = client.get(f"/api/v1/files/{f.id}")
    assert r.status_code == 410 and r.json()["detail"] == MISSING
