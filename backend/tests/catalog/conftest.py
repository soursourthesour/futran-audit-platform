import pytest

from app.tenancy.models import Organization
from tests.factories import make_org, make_user


@pytest.fixture
def futran(db):
    org = make_org(db, type="futran")
    db.commit()
    return org


@pytest.fixture
def seeded(db, futran):
    from app.catalog.seed import seed_starter

    seed_starter(db)
    db.commit()
    return db


@pytest.fixture
def staff(db, futran):
    """One person per role that touches the price list."""
    people = {
        "owner": make_user(db, futran, roles=["price_list_owner"], name="Pat President", email="president@futran.test"),
        "owner2": make_user(db, futran, roles=["price_list_owner", "pricing_approver"], name="Cara Ceo", email="ceo@futran.test"),
        "admin": make_user(db, futran, roles=["admin"], name="Ada Admin", email="ada@futran.test"),
        "chief": make_user(db, futran, roles=["chief_auditor"], name="Chris Chief", email="chief@futran.test"),
        "sales": make_user(db, futran, roles=["sales_team"], name="Sam Seller", email="sam@futran.test"),
        "manager": make_user(db, futran, roles=["sales_manager"], name="Mia Manager", email="mia@futran.test"),
        "auditor": make_user(db, futran, roles=["auditor"], name="Al Auditor", email="al@futran.test"),
    }
    client_org = make_org(db, type="client", name="Client Co")
    people["client"] = make_user(db, client_org, roles=["caico"], name="Cleo Client", email="cleo@client.test")
    db.commit()
    return people
