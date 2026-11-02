"""Monitoring checks registered by WS-K (wave 3 plan): "Tier 3 system with no bias test in 12 months" and "LL144 bias
audit older than 12 months", from the client's register. Read only.

LL144 § 5-301(a): an employer "may not use or continue to use an AEDT if more than one year has passed since the most
recent bias audit". Only an independent auditor's test counts as the bias audit; a test is due again 365 days after it.
"""
from datetime import timedelta

from sqlalchemy import func, select

from app.core.clock import today
from app.laws.models import Regulation
from app.monitoring.registry import CheckOutcome, register_check
from app.register.models import BiasTest, RegisterSystem, RegisterSystemLaw
from app.reports.service import LL144

YEAR_DAYS = 365
SOON_DAYS = 30


def _systems(db, org, *extra):
    return db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org.id, RegisterSystem.deleted_at.is_(None), RegisterSystem.stage != "retired", *extra)
                      .order_by(RegisterSystem.reference))


def _last(db, s, *extra):
    return db.scalar(select(func.max(BiasTest.tested_on)).where(BiasTest.register_system_id == s.id, BiasTest.deleted_at.is_(None), *extra))


def _label(s) -> str:
    return f"{s.reference} {s.name}"


def tier3_no_bias_test(db, org) -> list[CheckOutcome]:
    out = []
    for s in _systems(db, org, RegisterSystem.risk_tier == 3):
        last = _last(db, s)
        if last is None:
            status, detail = "failed", "No bias test recorded"
        elif last < today() - timedelta(days=YEAR_DAYS):
            status, detail = "failed", f"Last bias test {last:%d %b %Y}, more than 12 months ago"
        else:
            status, detail = "healthy", f"Last bias test {last:%d %b %Y}"
        out.append(CheckOutcome(s.id, _label(s), status, detail, f"/register/{s.id}", action="start_reassessment" if status != "healthy" else None, register_system_id=s.id))
    return out


def ll144_audit_age(db, org) -> list[CheckOutcome]:
    regs = [r.id for r in db.scalars(select(Regulation)) if LL144.search(f"{r.short_name or ''} {r.citation or ''} {r.label or ''}")]
    if not regs:
        return []
    ids = set(db.scalars(select(RegisterSystemLaw.register_system_id).where(RegisterSystemLaw.organization_id == org.id, RegisterSystemLaw.regulation_id.in_(regs),
                                                                              RegisterSystemLaw.status != "removed", RegisterSystemLaw.deleted_at.is_(None))))
    out = []
    for s in _systems(db, org, RegisterSystem.id.in_(ids)) if ids else []:
        last = _last(db, s, BiasTest.tester_type == "independent")
        if last is None:
            status, detail = "failed", "No independent bias audit recorded"
        else:
            due = last + timedelta(days=YEAR_DAYS)
            if due < today():
                status, detail = "failed", f"Bias audit of {last:%d %b %Y} expired on {due:%d %b %Y}"
            elif due <= today() + timedelta(days=SOON_DAYS):
                status, detail = "attention", f"Bias audit of {last:%d %b %Y} expires on {due:%d %b %Y}"
            else:
                status, detail = "healthy", f"Bias audit of {last:%d %b %Y}, valid until {due:%d %b %Y}"
        out.append(CheckOutcome(s.id, _label(s), status, detail, f"/register/{s.id}", action="request_report" if status != "healthy" else None, register_system_id=s.id))
    return out


register_check("tier3_no_bias_test_12m", "Tier 3 system with no bias test in 12 months", "high", "monthly", "system", tier3_no_bias_test)
register_check("ll144_bias_audit_older_12m", "LL144 bias audit older than 12 months", "high", "monthly", "system", ll144_audit_age)
