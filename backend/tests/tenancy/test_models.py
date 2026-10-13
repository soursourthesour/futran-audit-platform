import pytest

from app.core.errors import Conflict
from app.tenancy.service import create_organization, create_user, next_client_ref


def test_client_ref_sequence(db):
    a = create_organization(db, name="ABC Corp", type="client")
    b = create_organization(db, name="BCD Inc", type="client")
    assert a.client_ref == "FUT-0001"
    assert b.client_ref == "FUT-0002"
    assert next_client_ref(db) == "FUT-0003"


def test_futran_org_has_no_client_ref_and_self_tenant(db):
    f = create_organization(db, name="Futran Solutions", type="futran")
    assert f.client_ref is None
    assert f.organization_id == f.id


def test_user_email_unique_case_insensitive(db):
    org = create_organization(db, name="ABC Corp", type="client")
    create_user(db, org, name="Priya Shah", email="A@x.com")
    with pytest.raises(Conflict):
        create_user(db, org, name="Someone Else", email="a@x.com")


def test_user_email_stored_lowercase_trimmed(db):
    org = create_organization(db, name="ABC Corp", type="client")
    u = create_user(db, org, name="Priya Shah", email="  Priya.Shah@ABC.com ")
    assert u.email == "priya.shah@abc.com"
    assert u.status == "invited"
    assert u.organization_id == org.id
