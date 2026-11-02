"""Reassessment triggers (spec §21 F8): raise_trigger is the one entry point used by register edits, published
regulatory updates, the 12-month schedule and failed monitoring checks (WS-J)."""
import pytest
from sqlalchemy import select

from app.impact.models import ReassessmentTrigger
from app.impact.triggers import raise_trigger
from app.notifications.models import Notification


def test_raise_trigger_opens_a_trigger_on_the_register_system(db, lit):
    t = raise_trigger(db, lit["screening"].id, type="vendor_change", source="manual", detail="Vendor sold the product to another company")
    db.commit()
    assert t.status == "open" and t.type == "vendor_change" and t.source == "manual"
    assert t.organization_id == lit["abc"].id and t.register_system_id == lit["screening"].id
    assert t.detail == "Vendor sold the product to another company" and t.detected_at is not None


def test_the_same_open_trigger_is_not_raised_twice(db, lit):
    a = raise_trigger(db, lit["screening"].id, type="failed_monitor_check", source="monitor", source_ref="check:bias_overdue")
    b = raise_trigger(db, lit["screening"].id, type="failed_monitor_check", source="monitor", source_ref="check:bias_overdue")
    c = raise_trigger(db, lit["screening"].id, type="failed_monitor_check", source="monitor", source_ref="check:other")
    db.commit()
    assert a.id == b.id and c.id != a.id
    assert len(db.scalars(select(ReassessmentTrigger)).all()) == 2


def test_a_resolved_trigger_does_not_block_a_new_one(db, lit):
    a = raise_trigger(db, lit["screening"].id, type="version_change", source="manual")
    a.status = "resolved"
    db.flush()
    b = raise_trigger(db, lit["screening"].id, type="version_change", source="manual")
    assert b.id != a.id


def test_unknown_type_or_source_is_refused(db, lit):
    with pytest.raises(ValueError):
        raise_trigger(db, lit["screening"].id, type="moon_phase", source="manual")
    with pytest.raises(ValueError):
        raise_trigger(db, lit["screening"].id, type="vendor_change", source="rumour")


def test_retired_or_unknown_systems_get_no_trigger(db, lit):
    assert raise_trigger(db, lit["retired"].id, type="vendor_change", source="manual") is None
    assert raise_trigger(db, "no-such-system", type="vendor_change", source="manual") is None


def test_the_compliance_officer_is_notified(db, lit):
    raise_trigger(db, lit["chatbot"].id, type="new_data_category", source="register_edit", detail="Data used: added Health information")
    db.commit()
    n = db.scalars(select(Notification).where(Notification.user_id == lit["maria"].id)).all()
    assert len(n) == 1 and "Website chatbot" in n[0].title and n[0].link == f"/register/{lit['chatbot'].id}"


def test_a_trigger_reopens_the_affected_sections_of_a_current_assessment(db, lit, audited):
    t = raise_trigger(db, lit["screening"].id, type="new_data_category", source="register_edit")
    db.commit()
    data, incidents = audited["responses"]["5.1.01"], audited["responses"]["8.3.01"]
    db.refresh(data), db.refresh(incidents), db.refresh(audited["system"])
    assert data.verified_at is None and data.verified_by is None  # 5.1 must be verified again
    assert incidents.verified_at is not None  # 8.3 is not affected by a new data category
    assert audited["system"].status == "in_review"
    assert t.reopened == [{"engagement_id": audited["engagement"].id, "ai_system_id": audited["system"].id, "reference": "SYS-001",
                           "sections": ["5.1", "5.1a", "5.2", "5.3"], "answers_reopened": 1}]


def test_a_locked_or_closed_assessment_is_never_reopened(db, lit, audited):
    audited["system"].status = "locked"
    db.commit()
    t = raise_trigger(db, lit["screening"].id, type="new_data_category", source="register_edit")
    db.refresh(audited["responses"]["5.1.01"])
    assert audited["responses"]["5.1.01"].verified_at is not None and t.reopened == []
