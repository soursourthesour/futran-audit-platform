"""The R7 demo step builds the G-04 group, the G-10 vault and the G-11 partners, and running it twice adds nothing."""
from sqlalchemy import func, select

from app.demo.release2_r7 import seed_e2e
from app.hierarchy import service as h
from app.partners.models import Commission, Partner
from app.tenancy.models import Organization
from app.vault import service as vault
from tests.factories import make_org


def test_demo_step_is_complete_and_idempotent(db, settings):
    make_org(db, type="futran")
    out = seed_e2e(db, settings, None)
    db.commit()
    seed_e2e(db, settings, None)
    db.commit()
    acme = db.get(Organization, out["acme"])
    assert len(h.children(db, acme.id)) == 4 and h.ll144_end_client_count(db, acme.id) == 2
    metro = db.get(Organization, out["metro"])
    items = vault.countdown(db, settings, metro)
    assert items and any(i["hold"] == "LH-001" for i in items) and any(i["hold"] is None for i in items)
    assert db.scalar(select(func.count(Partner.id))) == 4
    assert sorted(c.status for c in db.scalars(select(Commission))) == ["due", "paid"]
