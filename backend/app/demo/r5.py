"""Release 2 R5 test data for the browser tests (test mode only): a won proposal handed off to delivery, a client on an
ordered Monitor Plus plan with usage measured, an hours bank, an incident retainer and a change order waiting for the
client. Prices and quantities are the ones the SM-13, G-01, G-02 and G-03 designs show; the accepted proposal is a
stand-in until the proposals workstream (R4) is in place."""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import today, utcnow

CLIENT = "Acme Staffing LLC"
SERVICE = "Initial assessment, LL144 and monitoring"
SYSTEMS = 47


def _line(code: str, qty: float, unit: float, periods: int | None, description: str, value: float | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=f"demo-{code}", catalog_code=code, description=description, deliverables_text=None, qty=qty, unit_price_used=unit, periods_per_year=periods,
                           line_value=value if value is not None else unit * qty * (periods or 1), removed_reason=None)


def seed(db: Session) -> dict:
    from app.commercial import commercials, handoff, plans
    from app.engagements.models import Engagement, EngagementTeam
    from app.register.models import RegisterSystem
    from app.sales.models import Opportunity
    from app.tenancy.models import Organization, User
    from app.tenancy.service import create_organization

    # Acme Staffing LLC is shared with the R6b (Copilot readiness) and R7 (group) test data, as in the designs: use the
    # client when it is already there. The won proposal is made once, so this step is skipped when its opportunity exists.
    org = db.scalar(select(Organization).where(Organization.name == CLIENT, Organization.deleted_at.is_(None)))
    if org is not None and db.scalar(select(Opportunity.id).where(Opportunity.organization_id == org.id, Opportunity.service == SERVICE)) is not None:
        return {}
    user = lambda email: db.scalar(select(User).where(User.email == email))  # noqa: E731
    sales, manager, auditor = user("sales@futran.demo"), user("manager@futran.demo"), user("auditor1@futran.demo")
    if org is None:
        org = create_organization(db, name=CLIENT, type="client", status="prospect", hq_city="New York", hq_state="NY", hq_country="US")
    opp = Opportunity(organization_id=org.id, trigger="manual", service=SERVICE, owner_id=sales.id if sales else None, stage="proposal",
                      value=116760, created_by=sales.id if sales else None)
    db.add(opp)
    db.flush()
    lines = [
        _line("A-02b", 1, 35000, None, "Audit, 11–50 systems"), _line("A-05", 3, 1500, None, "Shadow AI discovery sweep"),
        _line("A-06b", 1, 4000, None, "Attestation, 251–1,000"), _line("L-01", 1, 8500, None, "LL144 Readiness Assessment"),
        _line("M-01e", 1, 36000, 1, "Monitor Plus, 11–50 systems"), _line("M-03a", 1, 4200, 4, "Alert packs, 1–3 states"),
        _line("M-11a", 2, 3000, 1, "Tracing module"), _line("M-13", 20, 0, None, "Advisor hours bank (20 h)", value=0),
        _line("M-12b", 1, 350, None, "Incident response, activated (per hour)", value=0),
    ]
    proposal = SimpleNamespace(id=f"demo-proposal-{org.id}", opportunity_id=opp.id, version=1, catalog_version=None, discount_recurring_pct=0,
                               terms={"term_months": 12, "data_region": "us", "support_level": "Business hours", "onboarding_fee_waived": True}, lines=lines)
    acceptance = SimpleNamespace(id=None, name="Dana Diaz", title="COO", email="dana.diaz@acmestaffing.example", po_number="PO-4471", accepted_at=utcnow())
    h = handoff.create_from_acceptance(db, proposal, acceptance, sales)
    audit_e = db.scalar(select(Engagement).where(Engagement.client_id == org.id, Engagement.type == "initial_assessment"))
    for u, role in ((manager, "engagement_manager"), (auditor, "auditor")):
        if u is not None and audit_e is not None:
            db.add(EngagementTeam(organization_id=org.id, engagement_id=audit_e.id, user_id=u.id, role=role, created_by=u.id))
    # 47 systems in the register (Monitor Plus, 11–50 band), counting any the other test data already put there
    taken = set(db.scalars(select(RegisterSystem.reference).where(RegisterSystem.organization_id == org.id)))  # references are never reused
    live = db.scalar(select(func.count(RegisterSystem.id)).where(RegisterSystem.organization_id == org.id, RegisterSystem.deleted_at.is_(None))) or 0
    n = 0
    while live < SYSTEMS:
        n += 1
        if f"AIS-{n:03d}" not in taken:
            live += 1
            db.add(RegisterSystem(organization_id=org.id, reference=f"AIS-{n:03d}", name=f"AI system {n}", type="other", sourcing="vendor", stage="live"))
    db.flush()
    plans.run_daily_usage(db, None, utcnow())
    co = None
    if audit_e is not None and manager is not None:
        try:
            co = commercials.raise_change_order(db, manager, audit_e, code="A-08a", qty=1, reason="A vendor tool found in the discovery sweep that was not in the original scope.")
        except Exception:  # the starter price list may not hold A-08a
            co = None
    db.flush()
    return {"opportunity_id": opp.id, "client_id": org.id, "handoff_id": h.id, "engagement_id": audit_e.id if audit_e else None, "change_order_id": co.id if co else None,
            "as_of": today().isoformat()}
