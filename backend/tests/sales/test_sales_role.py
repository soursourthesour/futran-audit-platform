"""§27.5: the Sales Team role — what it can and cannot do."""
import pytest
from sqlalchemy import select

from app.policy.actions import Action as A
from app.policy.matrix import MATRIX, Scope as S
from app.policy.roles import FUTRAN_ROLES, ROLE_LABELS, Role as R
from app.tenancy.models import Organization
from tests.factories import login_as, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401

CAN = [A.VIEW_LITIGATION, A.VIEW_OPPORTUNITIES, A.WORK_OPPORTUNITIES]
CANNOT = [
    A.VIEW_FINDINGS_RESPONSES, A.RECORD_FINDINGS, A.VIEW_EVIDENCE, A.VIEW_SCORES, A.VIEW_FINAL_REPORT,
    A.VIEW_ENGAGEMENT, A.VIEW_INVENTORY, A.MANAGE_LITIGATION, A.APPROVE_OPPORTUNITY, A.MANAGE_REFERENCE_DATA,
    A.RUN_LAW_REFRESH, A.MANAGE_SYSTEMS, A.CREATE_CLIENT_ENGAGEMENT, A.MANAGE_CLIENT_ALERTS,
]


def test_sales_team_is_a_futran_role():
    assert R.SALES_TEAM in FUTRAN_ROLES
    assert ROLE_LABELS["sales_team"] == "Sales Team"


@pytest.mark.parametrize("action", CAN)
def test_sales_can(action):
    assert MATRIX[R.SALES_TEAM][action] == S.ALL


@pytest.mark.parametrize("action", CANNOT)
def test_sales_cannot(action):
    assert MATRIX[R.SALES_TEAM].get(action, S.NONE) == S.NONE


def test_only_chief_auditor_approves_offers():
    holders = {r for r, acts in MATRIX.items() if acts.get(A.APPROVE_OPPORTUNITY, S.NONE) != S.NONE}
    assert holders == {R.CHIEF_AUDITOR}


@pytest.fixture
def sales(db, people):
    futran = db.get(Organization, people["chief"].organization_id)
    u = make_user(db, futran, roles=["sales_team"], name="Sam Seller", email="sam@futran.test")
    db.commit()
    return u


def test_admin_can_give_a_user_the_sales_role(client, db, people):
    futran = db.get(Organization, people["chief"].organization_id)
    admin = make_user(db, futran, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    db.commit()
    login_as(client, db, admin)
    r = client.post("/api/v1/admin/users", json={"name": "Sid Sales", "email": "sid@futran.test", "roles": ["sales_team"]})
    assert r.status_code in (200, 201), r.text


def test_sales_is_refused_audit_findings_evidence_scores_and_reports(client, db, live, sales):
    cid, e, maria = live
    login_as(client, db, sales)
    for path in (f"/clients/{cid}/findings", f"/clients/{cid}/report", f"/clients/{cid}/scorecard", f"/clients/{cid}/document-requests"):
        r = client.get(f"/api/v1{path}")
        assert r.status_code in (403, 404), (path, r.status_code)


def test_sales_sees_litigation_and_opportunities(client, db, people, sales):
    login_as(client, db, sales)
    assert client.get("/api/v1/litigation").status_code == 200
    assert client.get("/api/v1/opportunities").status_code == 200


def test_sales_cannot_edit_cases_or_laws(client, db, people, sales):
    login_as(client, db, sales)
    assert client.post("/api/v1/litigation", json={"name": "A v. B", "area": "Hiring", "stage": "filed"}).status_code == 403
    assert client.post("/api/v1/laws", json={"jurisdiction_code": "US-IL", "short_name": "X"}).status_code == 403
