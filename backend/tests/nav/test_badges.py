"""F6: the navigation shows a count of obligations waiting for a decision, only to people who can approve them."""
from sqlalchemy import select

from app.ai.models import Obligation
from app.regmaster.seed import find_law
from tests.factories import login_as, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.regmaster.conftest import seeded  # noqa: F401

API = "/api/v1"


def _futran(db):
    from app.tenancy.models import Organization

    return db.scalar(select(Organization).where(Organization.type == "futran"))


def test_obligations_badge_counts_undecided_for_approvers_only(client, db, seeded):
    reg = find_law(db, "US-NYC", "Local Law 144")
    for status in ("suggested", "unsupported", "approved", "rejected"):
        db.add(Obligation(organization_id="futran", regulation_id=reg.id, text=f"An obligation {status}", actor="employer", status=status))
    gone = Obligation(organization_id="futran", regulation_id=reg.id, text="Withdrawn", actor="employer", status="suggested")
    db.add(gone)
    db.flush()
    from app.core.clock import utcnow

    gone.deleted_at = utcnow()
    legal = make_user(db, _futran(db), roles=["legal_reviewer"], name="Jordan Legal", email="jordan@futran.test")
    db.commit()

    login_as(client, db, legal)
    r = client.get(f"{API}/nav/badges")
    assert r.status_code == 200, r.text
    assert r.json() == {"obligations_to_review": 2}  # suggested and unsupported; not approved, rejected or deleted

    login_as(client, db, seeded["aud"])  # an auditor cannot approve obligations: no count
    r = client.get(f"{API}/nav/badges")
    assert r.status_code == 200 and r.json() == {}


def test_badges_need_a_session(client):
    assert client.get(f"{API}/nav/badges").status_code == 401
