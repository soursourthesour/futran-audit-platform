"""World for the proposal tests: Futran staff in every role that touches a proposal, the starter price list, a prospect
with an opportunity, and an audit client in fieldwork (for the independence rules)."""
from types import SimpleNamespace

import pytest

from tests.factories import login_as, make_org, make_user


def add_item(db, code, **kw):
    from app.catalog.models import CatalogItem

    spec = {"product": "Audit", "name": code, "billing": "one_time", "periods_per_year": 1, "basis": "$", "price_status": "approved",
            "sellable_status": "available", "included_quantities": {}, "applies_to": [], "remediation_of": [], "version_no": 1, **kw}
    it = CatalogItem(code=code, **spec)
    db.add(it)
    db.flush()
    return it


@pytest.fixture
def pw(db, client):
    from app.catalog.seed import seed_starter
    from app.engagements.models import Engagement
    from app.sales.models import Opportunity

    f = make_org(db, type="futran")
    seed_starter(db)
    ns = SimpleNamespace(db=db, client=client, futran=f)
    ns.sales = make_user(db, f, roles=["sales_team"], name="Raj Mehta", email="raj@futran.test")
    ns.sales2 = make_user(db, f, roles=["sales_team"], name="Sue Seller", email="sue@futran.test")
    ns.manager = make_user(db, f, roles=["sales_manager"], name="Mia Manager", email="mia@futran.test")
    ns.approver = make_user(db, f, roles=["pricing_approver"], name="Cara Ceo", email="ceo@futran.test")
    ns.chief = make_user(db, f, roles=["chief_auditor"], name="Chris Chief", email="chief@futran.test")
    ns.admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    ns.auditor = make_user(db, f, roles=["auditor"], name="Al Auditor", email="al@futran.test")
    ns.prospect = make_org(db, name="Acme Staffing LLC", status="prospect")
    ns.opp = Opportunity(organization_id=ns.prospect.id, trigger="manual", service="LL144 and AI governance", owner_id=ns.sales.id, stage="new")
    db.add(ns.opp)
    ns.audit_client = make_org(db, name="Harbor Health Group", status="active")
    ns.engagement = Engagement(organization_id=ns.audit_client.id, client_id=ns.audit_client.id, name="Harbor Health AI audit", status="in_progress", stage=5,
                               audit_ref="FSL-AI-AUD-2026-777")
    db.add(ns.engagement)
    ns.audit_opp = Opportunity(organization_id=ns.audit_client.id, trigger="manual", service="Policy drafting", owner_id=ns.sales.id, stage="new")
    db.add(ns.audit_opp)
    db.commit()
    ns.as_ = lambda user: login_as(client, db, user)
    return ns


@pytest.fixture
def estimate(db, pw):
    from app.catalog import estimates

    e = estimates.save(db, pw.sales, {"name": "Acme first look", "opportunity_id": pw.opp.id, "package": "governed",
                                      "lines": [{"code": "A-02b", "qty": 1}, {"code": "A-05", "qty": 3, "edited_price": 1200}, {"code": "M-03a", "qty": 1}],
                                      "discount_recurring_pct": 5})
    db.commit()
    return e
