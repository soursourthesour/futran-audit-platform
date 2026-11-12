"""Release 2 §4.1: the sales roles. `sales_team` keeps its key and is shown as Sales Officer; Sales Manager, Pricing
Approver and Price List Owner are Futran roles the Futran Admin assigns; nobody sees opportunity values who is not on
the sales side or the Chief Auditor."""
import pytest

from app.policy.actions import Action as A
from app.policy.homes import home_for
from app.policy.matrix import MATRIX, Scope as S
from app.policy.roles import FUTRAN_ROLES, ROLE_LABELS, Role as R
from tests.factories import login_as, make_user
from tests.wsd_world import lit  # noqa: F401

SALES_ROLES = ("sales_team", "sales_manager", "pricing_approver", "price_list_owner")


def test_labels_and_keys():
    assert ROLE_LABELS["sales_team"] == "Sales Officer"
    assert ROLE_LABELS["sales_manager"] == "Sales Manager"
    assert ROLE_LABELS["pricing_approver"] == "Pricing Approver"
    assert ROLE_LABELS["price_list_owner"] == "Price List Owner"
    assert {str(r) for r in FUTRAN_ROLES} >= set(SALES_ROLES)


def test_sales_officer_and_manager_land_on_the_sales_home():
    assert home_for({"sales_team"}, True) == "/sales"
    assert home_for({"sales_manager"}, True) == "/sales"
    assert home_for({"sales_team", "sales_manager"}, True) == "/sales"
    assert home_for({"chief_auditor", "sales_manager"}, True) == "/staff/chief"  # the role with more authority wins


@pytest.mark.parametrize("role,home", [("sales_team", "/sales"), ("sales_manager", "/sales"), ("pricing_approver", "/sales/approvals"),
                                       ("price_list_owner", "/staff/admin/catalog")])
def test_every_sales_role_alone_has_a_home_it_can_open(role, home):
    """No sales role falls through to /audits ("no Futran role yet")."""
    from app.policy.actions import Action

    assert home_for({role}, True) == home
    needs = {"/sales": Action.VIEW_SALES_HOME, "/sales/approvals": Action.DECIDE_PROPOSAL_APPROVALS, "/staff/admin/catalog": Action.VIEW_CATALOG}[home]
    assert MATRIX[R(role)].get(needs, S.NONE) != S.NONE


def test_the_ceo_with_both_pricing_roles_keeps_the_price_list_home():
    assert home_for({"price_list_owner", "pricing_approver"}, True) == "/staff/admin/catalog"


def test_manager_can_do_everything_an_officer_can_and_reassign():
    officer = {a for a, s in MATRIX[R.SALES_TEAM].items() if s != S.NONE}
    manager = {a for a, s in MATRIX[R.SALES_MANAGER].items() if s != S.NONE}
    assert officer <= manager
    assert MATRIX[R.SALES_MANAGER][A.REASSIGN_OPPORTUNITIES] == S.ALL
    assert MATRIX[R.SALES_MANAGER][A.VIEW_TEAM_PIPELINE] == S.ALL
    assert MATRIX[R.SALES_TEAM].get(A.REASSIGN_OPPORTUNITIES, S.NONE) == S.NONE
    assert MATRIX[R.SALES_TEAM][A.VIEW_SALES_HOME] == S.ALL


def test_chief_auditor_reads_the_pipeline_and_still_alone_approves_offers():
    assert MATRIX[R.CHIEF_AUDITOR][A.VIEW_OPPORTUNITIES] == S.ALL
    holders = {r for r, acts in MATRIX.items() if acts.get(A.APPROVE_OPPORTUNITY, S.NONE) != S.NONE}
    assert holders == {R.CHIEF_AUDITOR}


@pytest.mark.parametrize("role", ["auditor", "qa_reviewer", "engagement_manager", "legal_reviewer"])
def test_audit_roles_never_see_opportunities_or_their_values(role):
    acts = MATRIX.get(R(role), {})
    for a in (A.VIEW_OPPORTUNITIES, A.WORK_OPPORTUNITIES, A.VIEW_SALES_HOME, A.VIEW_TEAM_PIPELINE):
        assert acts.get(a, S.NONE) == S.NONE


def test_auditor_is_refused_the_sales_api(client, db, lit):
    login_as(client, db, lit["aud"])
    for path in ("/api/v1/opportunities", "/api/v1/opportunities/export.csv"):
        assert client.get(path).status_code == 403, path


def test_admin_assigns_the_new_sales_roles(client, db, lit):
    login_as(client, db, lit["admin"])
    r = client.post("/api/v1/admin/users", json={"name": "Mia Manager", "email": "mia@futran.test", "roles": ["sales_team", "sales_manager", "pricing_approver"]})
    assert r.status_code in (200, 201), r.text
    assert set(r.json()["role_labels"]) == {"Sales Officer", "Sales Manager", "Pricing Approver"}


def test_officer_cannot_hand_someone_elses_opportunity_to_another_rep_but_a_manager_can(client, db, lit):
    from app.sales.service import open_from_trigger

    futran = db.get(type(lit["abc"]), lit["sales"].organization_id)
    rep2 = make_user(db, futran, roles=["sales_team"], name="Rae Rep", email="rae@futran.test")
    mgr = make_user(db, futran, roles=["sales_manager"], name="Mia Manager", email="mia@futran.test")
    o = open_from_trigger(db, lit["nw"].id, "case", "c1", service="Bias audit", why_now="Case", owner_id=rep2.id)
    free = open_from_trigger(db, lit["nw"].id, "case", "c2", service="Readiness", why_now="Case")
    db.commit()
    login_as(client, db, lit["sales"])
    assert client.patch(f"/api/v1/opportunities/{o.id}", json={"owner_id": lit["sales"].id}).status_code == 403
    assert client.patch(f"/api/v1/opportunities/{free.id}", json={"owner_id": lit["sales"].id}).status_code == 200  # take an unowned one
    login_as(client, db, mgr)
    r = client.patch(f"/api/v1/opportunities/{o.id}", json={"owner_id": mgr.id})
    assert r.status_code == 200 and r.json()["owner_name"] == "Mia Manager"  # a Sales Manager can own opportunities
