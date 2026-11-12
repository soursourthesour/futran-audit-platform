"""The R5 test data hands off a won proposal for Acme Staffing LLC, the client R6b (Copilot readiness) and R7 (the G-04
group) also use: it must build on their Acme rather than skip it, keep 47 systems in the register without reusing a
reference, and add nothing the second time."""
from sqlalchemy import func, select

from app.commercial.models import Handoff
from app.demo import r5
from app.demo.r6b import seed_r6b
from app.demo.release2_r7 import seed_e2e as seed_r7
from app.register.models import RegisterSystem
from app.sales.models import Opportunity
from app.tenancy.models import Organization
from tests.factories import make_org


def _acme(db):
    return db.scalars(select(Organization).where(Organization.name == "Acme Staffing LLC")).all()


def test_r5_builds_on_the_shared_acme_and_is_idempotent(db, settings, fake_catalog):
    make_org(db, type="futran")
    seed_r6b(db, None)
    seed_r7(db, settings, None)
    out = r5.seed(db)
    db.commit()
    assert out.get("opportunity_id"), "the won proposal was not created"
    assert r5.seed(db) == {}
    db.commit()

    (acme,) = _acme(db)
    opps = db.scalars(select(Opportunity).where(Opportunity.organization_id == acme.id, Opportunity.trigger == "manual")).all()
    assert [o.id for o in opps] == [out["opportunity_id"]]
    assert db.scalar(select(func.count(Handoff.id)).where(Handoff.opportunity_id == out["opportunity_id"])) == 1
    refs = list(db.scalars(select(RegisterSystem.reference).where(RegisterSystem.organization_id == acme.id, RegisterSystem.deleted_at.is_(None))))
    assert len(refs) == 47 and len(set(refs)) == 47
    assert {"AIS-001", "AIS-002"} <= set(refs)  # R7's two AEDTs are kept
