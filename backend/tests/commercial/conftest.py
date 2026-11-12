"""World for the commercial tests: Futran staff in every role that matters here, a prospect that wins, an audit client,
and stand-ins for the catalog (R1) and the accepted proposal (R4), which are built by other workstreams."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.commercial import catalog as cat
from tests.factories import login_as, make_org, make_user

ITEMS = {
    "A-02b": dict(name="Enterprise audit, 11–50 systems", billing="One-time", list_price=35000, low=30000, high=40000, engagement_type="initial_assessment",
                  deliverables="Final report (sign-off 7)"),
    "A-03": dict(name="Extra AI system", billing="One-time", list_price=750, low=600, high=900, engagement_type="initial_assessment", deliverables="One more system assessed"),
    "A-04": dict(name="Extra jurisdiction", billing="One-time", list_price=1200, engagement_type="initial_assessment"),
    "A-07": dict(name="Extra governance documents", billing="One-time", list_price=300, engagement_type="initial_assessment"),
    "A-05": dict(name="Discovery sweep", billing="One-time", list_price=1500, engagement_type="initial_assessment", deliverables="Discovered tools list (G-05)"),
    "L-01": dict(name="LL144 readiness assessment", billing="One-time", list_price=9000, engagement_type="ll144_bias_audit", deliverables="LL144 readiness memo"),
    "M-01e": dict(name="Monitor Plus, 11–50 systems", billing="Annual", periods_per_year=1, list_price=36000, entitlement_key="ai_systems",
                  included_quantities={"ai_systems": 50, "seats": 5, "advisor_hours": 10}),
    "M-11a": dict(name="Tracing module", billing="Annual", periods_per_year=1, list_price=1500, entitlement_key="tracing_systems", included_quantities={"tracing_systems": 1}),
    "M-13": dict(name="Advisor hours bank", billing="One-time", list_price=300, entitlement_key="advisor_hours"),
    "M-13x": dict(name="Advisor hours over the bank", billing="One-time", list_price=325),
    "M-12a": dict(name="Incident response retainer", billing="Monthly", periods_per_year=12, list_price=1000),
    "M-12b": dict(name="Incident response, activated (per hour)", billing="One-time", list_price=350),
    "X-01": dict(name="Fractional AI Governance Officer", billing="Monthly", periods_per_year=12, list_price=6000, included_quantities={"advisor_hours": 16}),
    "M-14a": dict(name="API access", billing="Annual", periods_per_year=1, list_price=5000, entitlement_key="api_access", sellable_status="roadmap"),
}


@pytest.fixture
def fake_catalog(monkeypatch):
    items = {c: cat.Item(code=c, **v) for c, v in ITEMS.items()}
    monkeypatch.setattr(cat, "items_by_codes", lambda db, codes: {c: items[c] for c in codes if c in items})
    monkeypatch.setattr(cat, "get_item", lambda db, code: items.get(code))
    monkeypatch.setattr(cat, "current_version", lambda db: 3)
    return items


def line(code, qty, unit, periods=None, value=None, description=None):
    item = ITEMS.get(code, {})
    periods = periods if periods is not None else item.get("periods_per_year")
    recurring = item.get("billing", "One-time") != "One-time"
    v = value if value is not None else unit * qty * ((periods or 1) if recurring else 1)
    return SimpleNamespace(id=f"pl-{code}", catalog_code=code, description=description or item.get("name", code), deliverables_text=item.get("deliverables"),
                           qty=qty, unit_price_used=unit, periods_per_year=periods, line_value=v, removed_reason=None)


@pytest.fixture
def cw(db, client):
    from app.core.clock import today
    from app.engagements.models import Engagement, EngagementTeam
    from app.sales.models import Opportunity

    f = make_org(db, type="futran")
    ns = SimpleNamespace(client=client, db=db, futran=f)
    ns.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    ns.fadmin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    ns.sales = make_user(db, f, roles=["sales_team"], name="Raj Mehta", email="raj@futran.test")
    ns.sales2 = make_user(db, f, roles=["sales_team"], name="Sue Seller", email="sue@futran.test")
    ns.em = make_user(db, f, roles=["engagement_manager"], name="Eve Manager", email="eve@futran.test")
    ns.auditor = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    ns.prospect = make_org(db, name="Acme Staffing LLC", status="prospect")
    ns.opp = Opportunity(organization_id=ns.prospect.id, trigger="manual", service="Initial assessment and monitoring", owner_id=ns.sales.id, stage="proposal", value=116760)
    db.add(ns.opp)
    # an audit client already in fieldwork, for G-02 and G-03
    ns.org = make_org(db, name="Harbor Health Group", status="active")
    ns.caico = make_user(db, ns.org, roles=["caico"], name="Maria Lopez", email="maria@harbor.example")
    ns.client_admin = make_user(db, ns.org, roles=["client_admin"], name="Sam Okafor", email="sam@harbor.example")
    e = Engagement(organization_id=ns.org.id, client_id=ns.org.id, name="Harbor Health AI audit", status="in_progress", stage=5, audit_ref="FSL-AI-AUD-2026-901")
    db.add(e)
    db.flush()
    for u, role in ((ns.auditor, "auditor"), (ns.em, "engagement_manager")):
        db.add(EngagementTeam(organization_id=ns.org.id, engagement_id=e.id, user_id=u.id, role=role))
    db.commit()
    ns.engagement = e
    ns.today = today()
    ns.as_ = lambda user: login_as(client, db, user)
    return ns


def proposal_for(cw, lines, **terms):
    p = SimpleNamespace(id="prop-1", opportunity_id=cw.opp.id, version=1, catalog_version=3, discount_recurring_pct=0, terms={"term_months": 12, **terms},
                        lines=lines, totals={})
    a = SimpleNamespace(id="acc-1", proposal_id=p.id, name="Dana Diaz", title="COO", email="dana@acme.example", po_number="PO-7788",
                        accepted_at=None, authorised_confirmed=True)
    return p, a


STANDARD_LINES = lambda: [  # noqa: E731
    line("A-02b", 1, 35000), line("A-05", 3, 1500), line("L-01", 1, 9000), line("M-01e", 1, 36000), line("M-11a", 2, 1500),
    line("M-13", 20, 300), line("M-12a", 1, 1000, value=12000),
]


@pytest.fixture
def start_day():
    return date(2026, 11, 2)
