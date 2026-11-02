"""The 12-month reassessment schedule (spec §21 F8) on a register system that Futran audits.

A Futran engagement assessing the system is an assessment: the year runs from it, and an engagement still in progress
is the reassessment, so the schedule neither raises a trigger nor clears the auditor's verification of its answers."""
from datetime import date, datetime

from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.core.clock import set_now
from app.impact.models import ReassessmentTrigger
from app.impact.schedule import last_assessed, run_reassessment_schedule
from app.impact.triggers import raise_trigger


def _triggers(db, sid):
    return db.scalars(select(ReassessmentTrigger).where(ReassessmentTrigger.register_system_id == sid).order_by(ReassessmentTrigger.detected_at)).all()


def _verified(db, audited):
    out = []
    for r in audited["responses"].values():
        db.refresh(r)
        out.append((r.verified_by, r.verified_at))
    return out


def test_the_first_daily_run_leaves_a_system_under_audit_alone(db, lit, audited, settings):
    lit["screening"].live_since = date(2025, 6, 1)
    db.commit()
    assert run_reassessment_schedule(db, settings, datetime(2026, 11, 2, 10)) == 0
    db.commit()
    assert _triggers(db, lit["screening"].id) == []
    assert all(by == lit["aud"].id and at is not None for by, at in _verified(db, audited))
    db.refresh(audited["system"])
    assert audited["system"].status == "scored"


def test_an_engagement_in_progress_for_over_a_year_is_still_the_reassessment(db, lit, audited, settings):
    lit["screening"].live_since = date(2024, 1, 1)
    audited["engagement"].approved_at = datetime(2025, 9, 1)
    db.commit()
    assert run_reassessment_schedule(db, settings, datetime(2026, 11, 2, 10)) == 0
    assert _triggers(db, lit["screening"].id) == []


def test_a_completed_engagement_counts_as_the_last_assessment(db, lit, audited, settings):
    from app.scoring.models import SystemRiskScore

    s = lit["screening"]
    s.live_since = date(2024, 1, 1)
    e, sysrow = audited["engagement"], audited["system"]
    e.status, e.approved_at, e.completed_at, sysrow.status = "completed", datetime(2025, 11, 20), datetime(2026, 3, 2, 9), "locked"
    db.add(SystemRiskScore(organization_id=s.organization_id, engagement_id=e.id, ai_system_id=sysrow.id, seq=1, methodology_version="1.0",
                           created_at=datetime(2026, 2, 10), locked_at=datetime(2026, 3, 1, 15)))
    db.commit()
    assert last_assessed(db, s) == date(2026, 3, 2)
    assert run_reassessment_schedule(db, settings, datetime(2026, 11, 2, 10)) == 0
    assert run_reassessment_schedule(db, settings, datetime(2027, 3, 2, 10)) == 1
    assert _triggers(db, s.id)[0].detail == "Last assessed 2 March 2026"


def test_a_twelve_month_trigger_never_clears_verification_in_a_current_engagement(db, lit, audited):
    t = raise_trigger(db, lit["screening"].id, type="twelve_months", source="schedule", source_ref="12m:2026-06-01")
    db.commit()
    assert t.reopened == []
    assert all(at is not None for _by, at in _verified(db, audited))
    db.refresh(audited["system"])
    assert audited["system"].status == "scored"


def test_the_audit_entry_records_whose_verification_a_trigger_cleared(db, lit, audited):
    r = audited["responses"]["5.1.01"]
    was = r.verified_at
    t = raise_trigger(db, lit["screening"].id, type="new_data_category", source="register_edit")
    db.commit()
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "reassessment.trigger", AuditLog.object_id == t.id))
    assert entry.before == {"verified": [{"response_id": r.id, "ai_system_id": audited["system"].id, "verified_by": lit["aud"].id,
                                          "verified_at": was.isoformat()}]}


def test_a_dismissed_twelve_month_trigger_is_not_raised_again_the_next_day(db, lit, settings):
    from app.impact.lifecycle import act

    s = lit["screening"]
    s.live_since = date(2025, 6, 1)
    db.commit()
    try:
        set_now(datetime(2026, 11, 2, 10))
        assert run_reassessment_schedule(db, settings, datetime(2026, 11, 2, 10)) == 1
        act(db, lit["maria"], _triggers(db, s.id)[0], s, "dismiss", "Reviewed in the current audit")
        db.commit()
        set_now(datetime(2026, 11, 3, 10))
        assert run_reassessment_schedule(db, settings, datetime(2026, 11, 3, 10)) == 0
        assert run_reassessment_schedule(db, settings, datetime(2027, 11, 2, 10)) == 1  # the next cycle: 12 months after the dismissal
    finally:
        set_now(None)
    assert len(_triggers(db, s.id)) == 2


def test_a_twelve_month_trigger_closed_without_a_date_still_counts_for_its_cycle(db, lit, settings):
    s = lit["screening"]
    s.live_since = date(2025, 6, 1)
    db.commit()
    assert run_reassessment_schedule(db, settings, datetime(2026, 11, 2, 10)) == 1
    t = _triggers(db, s.id)[0]
    t.status, t.resolution_note = "dismissed", "Reviewed in the current audit"
    db.commit()
    assert run_reassessment_schedule(db, settings, datetime(2026, 11, 3, 10)) == 0
    assert len(_triggers(db, s.id)) == 1
