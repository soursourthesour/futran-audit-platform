import pytest

from app.sales.models import Opportunity
from tests.factories import make_org, make_user


@pytest.fixture
def world(db):
    """Futran with a Sales Officer, a second Sales Officer, the Chief Auditor, a Futran Admin and an Auditor; a
    prospect with one opportunity owned by the first Sales Officer."""
    futran = make_org(db, type="futran")
    sales = make_user(db, futran, roles=["sales_team"], name="Rita Mehta", email="r.mehta@futransolutions.com")
    sales2 = make_user(db, futran, roles=["sales_team"], name="Sam Iyer", email="s.iyer@futransolutions.com")
    chief = make_user(db, futran, roles=["chief_auditor"], name="Cara Chief")
    admin = make_user(db, futran, roles=["admin"], name="Ada Admin")
    auditor = make_user(db, futran, roles=["auditor"], name="Al Auditor")
    acme = make_org(db, type="client", name="Acme Staffing LLC")
    client_user = make_user(db, acme, roles=["caico"], name="Cleo Client")
    opp = Opportunity(organization_id=acme.id, trigger="manual", service="LL144 readiness and Monitor", owner_id=sales.id, stage="new")
    db.add(opp)
    db.commit()
    return {"futran": futran, "sales": sales, "sales2": sales2, "chief": chief, "admin": admin, "auditor": auditor, "acme": acme,
            "client_user": client_user, "opp": opp}
