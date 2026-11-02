"""The monitoring check registry (§21 F3): each workstream registers its own checks; a run records one result per
object a check looked at."""
import pytest

from app.monitoring import registry
from app.monitoring.registry import CheckOutcome, register_check
from tests.factories import make_org


@pytest.fixture
def scratch_registry(monkeypatch):
    monkeypatch.setattr(registry, "CHECKS", {})
    return registry


def test_register_check_records_its_metadata(scratch_registry):
    register_check("demo_check", "Demo check", "high", "monthly", "org", lambda db, org: [])
    c = scratch_registry.CHECKS["demo_check"]
    assert (c.code, c.description, c.severity, c.frequency, c.applies_to) == ("demo_check", "Demo check", "high", "monthly", "org")


def test_register_check_refuses_an_unknown_severity_or_scope(scratch_registry):
    with pytest.raises(ValueError):
        register_check("x", "X", "urgent", "monthly", "org", lambda db, org: [])
    with pytest.raises(ValueError):
        register_check("y", "Y", "high", "monthly", "planet", lambda db, org: [])


def test_registering_the_same_code_twice_keeps_one_check(scratch_registry):
    register_check("dup", "First", "low", "monthly", "org", lambda db, org: [])
    register_check("dup", "Second", "low", "monthly", "org", lambda db, org: [])
    assert scratch_registry.CHECKS["dup"].description == "Second"


def test_check_outcome_refuses_an_unknown_status():
    CheckOutcome("o1", "Object", "attention", "Due soon", "/x")
    with pytest.raises(ValueError):
        CheckOutcome("o1", "Object", "broken", "", None)


def test_sync_writes_one_monitor_check_row_per_registered_check(db, scratch_registry):
    from app.monitoring.models import MonitorCheck

    register_check("a_check", "A", "high", "monthly", "org", lambda db, org: [])
    register_check("b_check", "B", "low", "monthly", "system", lambda db, org: [])
    scratch_registry.sync_checks(db)
    scratch_registry.sync_checks(db)
    rows = {c.code: c for c in db.query(MonitorCheck).all()}
    assert set(rows) == {"a_check", "b_check"} and rows["b_check"].applies_to == "system"


def test_organization_has_a_nullable_subscription_plan(db):
    org = make_org(db)
    assert org.subscription_plan is None
    org.subscription_plan = "monitor"
    db.flush()

