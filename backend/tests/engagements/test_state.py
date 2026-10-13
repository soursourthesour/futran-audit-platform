import re

import pytest

from app.core.clock import set_now
from app.core.errors import Conflict, Invalid
from app.engagements.service import create_engagement, transition
from tests.factories import make_org, make_user


@pytest.fixture
def setup(db):
    f = make_org(db, type="futran")
    aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@f.test")
    chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@f.test")
    client = make_org(db, name="ABC Corp")
    return aud, chief, client


def test_audit_ref_format(db, setup):
    from datetime import datetime

    aud, _, client = setup
    set_now(datetime(2026, 10, 13, 9, 0))
    try:
        e1 = create_engagement(db, aud, client, name="ABC Corp AI audit 2026")
        e2 = create_engagement(db, aud, client, name="Second")
    finally:
        set_now(None)
    assert e1.audit_ref == "FSL-AI-AUD-2026-001" and e2.audit_ref == "FSL-AI-AUD-2026-002"
    assert re.fullmatch(r"FSL-AI-AUD-\d{4}-\d{3}", e1.audit_ref)
    assert e1.status == "draft" and e1.stage == 1 and e1.created_by == aud.id and e1.organization_id == client.id


def test_happy_path_transitions(db, setup):
    aud, chief, client = setup
    e = create_engagement(db, aud, client, name="x")
    for s in ("pending_approval", "initiated", "in_progress", "completed", "archived"):
        transition(db, chief if s == "initiated" else aud, e, s)
        assert e.status == s
    assert e.approved_by == chief.id and e.approved_at is not None and e.completed_at is not None


def test_cannot_skip_status(db, setup):
    aud, _, client = setup
    e = create_engagement(db, aud, client, name="x")
    with pytest.raises(Conflict) as exc:
        transition(db, aud, e, "initiated")
    assert "Draft" in exc.value.detail and "Initiated" in exc.value.detail
    assert e.status == "draft"


def test_return_to_author_requires_comment(db, setup):
    aud, chief, client = setup
    e = create_engagement(db, aud, client, name="x")
    transition(db, aud, e, "pending_approval")
    with pytest.raises(Invalid):
        transition(db, chief, e, "draft")
    with pytest.raises(Invalid):
        transition(db, chief, e, "draft", comment="   ")
    transition(db, chief, e, "draft", comment="Add the Chicago office.")
    assert e.status == "draft" and e.returned_comment == "Add the Chicago office."
    transition(db, aud, e, "pending_approval")
    assert e.returned_comment == "Add the Chicago office."  # kept for the record until approved


def test_preparer_cannot_approve_own_engagement(db, setup):
    from app.core.errors import Forbidden

    _, chief, client = setup
    e = create_engagement(db, chief, client, name="x")
    transition(db, chief, e, "pending_approval")
    with pytest.raises(Forbidden):
        transition(db, chief, e, "initiated")
