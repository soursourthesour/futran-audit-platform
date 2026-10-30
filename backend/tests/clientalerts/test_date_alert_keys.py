"""Deadline alerts (§27.6: 90 and 30 days before) go once per law, date and mark: a new version of the law with the
same date, or a Reference data edit that replaces the law's row, does not send "90 days to ..." again."""
from datetime import date, timedelta

from sqlalchemy import select

from app.clientalerts.models import AlertSend
from app.clientalerts.service import queue_effective_dates
from app.regmaster.models import ClientLawApplicability
from app.regmaster.versioning import clone_version
from tests.clientalerts.test_client_alerts import law  # noqa: F401


def _in_scope(db, lit, reg, v):
    db.add(ClientLawApplicability(organization_id=lit["abc"].id, regulation_id=reg.id, law_version_id=v.id, in_scope=True))
    db.commit()


def test_new_version_with_the_same_date_does_not_resend(db, lit, law, settings):
    reg, v, _pc = law
    _in_scope(db, lit, reg, v)
    day90 = v.compliance_on - timedelta(days=90)
    assert len(queue_effective_dates(db, settings, day90)) == 1
    v2 = clone_version(db, v, summary="Typo fixed in a requirement")
    reg.current_version_id = v2.id
    db.commit()
    assert queue_effective_dates(db, settings, day90 + timedelta(days=3)) == []


def test_new_date_sends_again(db, lit, law, settings):
    reg, v, _pc = law
    _in_scope(db, lit, reg, v)
    assert len(queue_effective_dates(db, settings, v.compliance_on - timedelta(days=90))) == 1
    v2 = clone_version(db, v, summary="Compliance date moved")
    v2.compliance_on = v.compliance_on + timedelta(days=10)
    reg.current_version_id = v2.id
    db.commit()
    assert len(queue_effective_dates(db, settings, v2.compliance_on - timedelta(days=89))) == 1


def test_reference_data_edit_does_not_resend(db, lit, law, settings):
    from app.laws.service import edit_law
    from app.regmaster.seed import ensure_versions

    reg, v, _pc = law
    _in_scope(db, lit, reg, v)
    day90 = v.compliance_on - timedelta(days=90)
    assert len(queue_effective_dates(db, settings, day90)) == 1
    edit_law(db, lit["admin"], reg.id, {"enforcer": "Department of Labor"})
    db.flush()
    ensure_versions(db)
    db.commit()
    assert queue_effective_dates(db, settings, day90 + timedelta(days=1)) == []


def test_alerts_written_with_the_old_key_are_honoured(db, lit, law, settings):
    """Sends queued before the fix were keyed on the version id."""
    from app.clientalerts.service import rule_for

    reg, v, _pc = law
    _in_scope(db, lit, reg, v)
    rule = rule_for(db, "effective_date")
    db.add(AlertSend(alert_rule_id=rule.id, organization_id=lit["abc"].id, change_ref=f"date:{v.id}:90", headline="Old", status="sent"))
    db.commit()
    assert queue_effective_dates(db, settings, v.compliance_on - timedelta(days=90)) == []


def test_removed_applicability_and_replaced_rows_are_skipped(db, lit, law, settings):
    from app.core.clock import utcnow

    reg, v, _pc = law
    _in_scope(db, lit, reg, v)
    row = db.scalar(select(ClientLawApplicability).where(ClientLawApplicability.regulation_id == reg.id))
    row.deleted_at = utcnow()
    db.commit()
    assert queue_effective_dates(db, settings, v.compliance_on - timedelta(days=90)) == []
