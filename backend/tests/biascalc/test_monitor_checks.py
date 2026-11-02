"""Monitoring checks registered by WS-K: "Tier 3 system with no bias test in 12 months" and "LL144 bias audit older than 12 months"."""
from datetime import date, timedelta

from sqlalchemy import select

from app.laws.models import Regulation
from app.monitoring.registry import CHECKS, load_checks
from app.register.models import BiasTest, RegisterSystem, RegisterSystemLaw
from tests.factories import make_org


def _check(code):
    load_checks()
    return CHECKS[code]


def _system(db, org, ref, name, tier=3, stage="live"):
    s = RegisterSystem(organization_id=org.id, reference=ref, name=name, type="vendor_app", sourcing="vendor", stage=stage, risk_tier=tier)
    db.add(s)
    db.flush()
    return s


def _test(db, s, days_ago, tester="independent"):
    db.add(BiasTest(organization_id=s.organization_id, register_system_id=s.id, tested_on=date.today() - timedelta(days=days_ago), tester_type=tester, result="passed"))
    db.flush()


def test_both_checks_are_registered():
    load_checks()
    assert {"tier3_no_bias_test_12m", "ll144_bias_audit_older_12m"} <= set(CHECKS)
    assert CHECKS["tier3_no_bias_test_12m"].applies_to == "system" and CHECKS["ll144_bias_audit_older_12m"].severity == "high"


def test_tier3_systems_need_a_bias_test_in_the_last_12_months(db):
    org = make_org(db)
    fresh, stale, never = _system(db, org, "AIS-001", "Résumé screener"), _system(db, org, "AIS-002", "Attrition model"), _system(db, org, "AIS-003", "Interview scorer")
    _system(db, org, "AIS-004", "Chat assistant", tier=2)
    _system(db, org, "AIS-005", "Old screener", stage="retired")
    _test(db, fresh, 30)
    _test(db, stale, 400)
    out = {o.object_label: o for o in _check("tier3_no_bias_test_12m").fn(db, org)}
    assert set(out) == {"AIS-001 Résumé screener", "AIS-002 Attrition model", "AIS-003 Interview scorer"}
    assert out["AIS-001 Résumé screener"].status == "healthy"
    assert out["AIS-002 Attrition model"].status == "failed" and out["AIS-002 Attrition model"].register_system_id == stale.id
    assert out["AIS-003 Interview scorer"].status == "failed" and out["AIS-003 Interview scorer"].detail == "No bias test recorded"
    assert out["AIS-002 Attrition model"].action_link == f"/register/{stale.id}"


def test_ll144_systems_need_an_independent_audit_within_a_year(db, matrix):
    org = make_org(db)
    ll144 = next(r for r in db.scalars(select(Regulation)) if "144" in (r.short_name or "") and "Local Law" in (r.short_name or "") or (r.label or "") == "NYC LL144")
    a, b, c, d = (_system(db, org, f"AIS-00{i}", n) for i, n in enumerate(("Screener", "Ranker", "Scheduler", "Vendor-only"), start=1))
    for s in (a, b, c, d):
        db.add(RegisterSystemLaw(organization_id=org.id, register_system_id=s.id, regulation_id=ll144.id, status="active"))
    _test(db, a, 100)
    _test(db, b, 350)
    _test(db, d, 30, tester="vendor")  # a vendor's own test is not the independent bias audit
    out = {o.object_label: o.status for o in _check("ll144_bias_audit_older_12m").fn(db, org)}
    assert out == {"AIS-001 Screener": "healthy", "AIS-002 Ranker": "attention", "AIS-003 Scheduler": "failed", "AIS-004 Vendor-only": "failed"}
