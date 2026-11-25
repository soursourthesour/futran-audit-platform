"""The permission matrix, cell by cell, on a real database (spec §5, §6; app/policy/matrix.py).

For every role and every action, `authorize` is called in each resource context below, as a real user with a real role
assignment, in a world with Futran and two client tenants. The expected outcome comes from the scope definitions in
matrix.py's docstring and the authorize.py rules (a resource outside what the user may see is 404, a visible resource
without the right is 403), written out here independently of authorize's code.

Pinned invariants from the spec (separation of duties, Sales and Auditor exclusions) are checked against the matrix
separately, so a matrix edit that breaks one fails here even when authorize does exactly what the matrix says.
"""
from datetime import datetime, timedelta

import pytest

from app.auth.deps import Actor
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement, EngagementTeam
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.policy.matrix import MATRIX, Scope
from app.policy.roles import CLIENT_ROLES, FUTRAN_ROLES, Role
from app.tenancy.service import roles_of
from tests.factories import make_department, make_org, make_user

GRANT, DENY, HIDDEN = "grant", "403", "404"
SEES_ALL = {Role.CHIEF_AUDITOR, Role.ADMIN}
SYSTEM_ID, OTHER_SYSTEM_ID = "sys-in-scope-0000-0000-000000000001", "sys-out-of-scope-0000-0000-000000002"


def scope(role: Role, action: Action) -> Scope:
    return MATRIX.get(role, {}).get(action, Scope.NONE)


@pytest.fixture
def world(db):
    f = make_org(db, type="futran")
    a = make_org(db, name="Alpha Insurance")
    b = make_org(db, name="Bravo Health")
    d1, d2 = make_department(db, a, name="Underwriting"), make_department(db, a, name="Claims")
    make_department(db, b, name="Nursing")
    db.flush()

    def eng(org, status, stage=5, **kw):
        e = Engagement(organization_id=org.id, client_id=org.id, name=f"{org.name} {status}", status=status, stage=stage, **kw)
        db.add(e)
        db.flush()
        return e

    w = {"futran": f, "a": a, "b": b, "d1": d1, "d2": d2,
         "e_a": eng(a, "in_progress"), "e_a_draft": eng(a, "draft", stage=1), "e_b": eng(b, "in_progress")}
    users = {}
    for r in FUTRAN_ROLES:
        u = make_user(db, f, roles=[r.value], name=f"F {r.value}", email=f"{r.value}@futran.test")
        db.add(EngagementTeam(organization_id=a.id, engagement_id=w["e_a"].id, user_id=u.id, role=r.value))
        users[r] = u
    for r in CLIENT_ROLES:
        if r in (Role.DEPT_COMPLIANCE_LEAD, Role.CONTRIBUTOR):
            spec = (r.value, "department", d1.id)
        else:
            spec = r.value
        users[r] = make_user(db, a, roles=[spec], name=f"A {r.value}", email=f"{r.value}@alpha.test")
    # a Contributor assigned to one AI system rather than a department (SYSTEM scope)
    users["contributor_system"] = make_user(db, a, roles=[(Role.CONTRIBUTOR.value, "system", SYSTEM_ID)], name="A sys contributor", email="sys@alpha.test")
    db.commit()
    w["users"] = users
    return w


def actor(db, user) -> Actor:
    from app.tenancy.models import Organization

    return Actor(user=user, organization=db.get(Organization, user.organization_id), roles=roles_of(db, user.id))


def outcome(db, act: Actor, action: Action, **kw) -> str:
    try:
        authorize(db, act, action, **kw)
        return GRANT
    except NotFound:
        return HIDDEN
    except Forbidden:
        return DENY


# ---------------------------------------------------------------- expected outcomes, per context
def futran_contexts(w):
    """(name, authorize kwargs, expected(role, scope))."""
    def if_(cond):
        return GRANT if cond else DENY

    return [
        ("assigned engagement", {"engagement_id": w["e_a"].id}, lambda r, s: if_(s in (Scope.ALL, Scope.ASSIGNED))),
        ("unassigned engagement", {"engagement_id": w["e_b"].id}, lambda r, s: if_(s == Scope.ALL) if r in SEES_ALL else HIDDEN),
        ("platform, no resource", {}, lambda r, s: if_(s == Scope.ALL)),
        ("list view", {"list_view": True}, lambda r, s: if_(s in (Scope.ALL, Scope.ASSIGNED))),
        ("assigned client org", {"org_id": w["a"].id}, lambda r, s: if_(s in (Scope.ALL, Scope.ASSIGNED))),
        ("unassigned client org", {"org_id": w["b"].id}, lambda r, s: if_(s == Scope.ALL) if r in SEES_ALL else HIDDEN),
    ]


def client_contexts(w, assignment: str):
    """assignment: 'org', 'department' (D1) or 'system' (SYSTEM_ID)."""
    def if_(cond):
        return GRANT if cond else DENY

    dept, system = assignment == "department", assignment == "system"
    return [
        ("own org", {"org_id": w["a"].id}, lambda s: if_(s == Scope.ORG)),
        ("own org, list view", {"org_id": w["a"].id, "list_view": True},
         lambda s: if_(s == Scope.ORG or (s == Scope.DEPT and dept) or (s == Scope.SYSTEM and (dept or system)))),
        ("own department", {"org_id": w["a"].id, "department_id": w["d1"].id},
         lambda s: if_(s == Scope.ORG or (s in (Scope.DEPT, Scope.SYSTEM) and dept))),
        ("other department", {"org_id": w["a"].id, "department_id": w["d2"].id}, lambda s: if_(s == Scope.ORG)),
        ("own system", {"org_id": w["a"].id, "system_id": SYSTEM_ID}, lambda s: if_(s == Scope.ORG or (s == Scope.SYSTEM and system))),
        ("other system", {"org_id": w["a"].id, "system_id": OTHER_SYSTEM_ID}, lambda s: if_(s == Scope.ORG)),
        ("own open engagement", {"engagement_id": w["e_a"].id}, lambda s: if_(s == Scope.ORG)),
        ("own draft engagement", {"engagement_id": w["e_a_draft"].id}, lambda s: HIDDEN),
        ("other tenant org", {"org_id": w["b"].id}, lambda s: HIDDEN),
        ("other tenant engagement", {"engagement_id": w["e_b"].id}, lambda s: HIDDEN),
    ]


CLIENT_SUBJECTS = [(r, r) for r in sorted(CLIENT_ROLES)] + [(Role.CONTRIBUTOR, "contributor_system")]


@pytest.mark.parametrize("role", sorted(FUTRAN_ROLES), ids=str)
def test_futran_role_cells(db, world, role):
    act = actor(db, world["users"][role])
    wrong, n = [], 0
    for action in Action:
        s = scope(role, action)
        for name, kw, expect in futran_contexts(world):
            want, got = expect(role, s), outcome(db, act, action, **kw)
            if action == Action.VIEW_DISCOVERY_PEOPLE and s == Scope.ASSIGNED and name == "list view":
                want = DENY  # names behind a discovered tool always need the client whose open engagement it is
            n += 1
            if want != got:
                wrong.append(f"{role}/{action} [{name}] matrix={s}: expected {want}, got {got}")
    assert not wrong, "\n".join(wrong[:40])
    assert n == len(Action) * 6


@pytest.mark.parametrize("role,user_key", CLIENT_SUBJECTS, ids=lambda v: str(v))
def test_client_role_cells(db, world, role, user_key):
    user = world["users"][user_key]
    act = actor(db, user)
    assignment = act.roles[0].scope_type if act.roles[0].scope_type in ("department", "system") else "org"
    wrong = []
    for action in Action:
        s = scope(role, action)
        for name, kw, expect in client_contexts(world, assignment):
            want, got = expect(s), outcome(db, act, action, **kw)
            if want != got:
                wrong.append(f"{user_key}/{action} [{name}] matrix={s}: expected {want}, got {got}")
    assert not wrong, "\n".join(wrong[:40])


def test_role_assignment_lends_only_its_own_scope(db, world):
    """A Contributor assignment in Underwriting does not lend a Department Compliance Lead permission for Underwriting
    to a user who is Department Compliance Lead of Claims (authorize docstring)."""
    u = make_user(db, world["a"], roles=[(Role.CONTRIBUTOR.value, "department", world["d1"].id), (Role.DEPT_COMPLIANCE_LEAD.value, "department", world["d2"].id)],
                  name="Two Hats", email="two.hats@alpha.test")
    db.commit()
    act = actor(db, u)
    assert scope(Role.DEPT_COMPLIANCE_LEAD, Action.RESPOND_FINDINGS) == Scope.DEPT and scope(Role.CONTRIBUTOR, Action.RESPOND_FINDINGS) == Scope.NONE
    assert outcome(db, act, Action.RESPOND_FINDINGS, org_id=world["a"].id, department_id=world["d2"].id) == GRANT
    assert outcome(db, act, Action.RESPOND_FINDINGS, org_id=world["a"].id, department_id=world["d1"].id) == DENY


def test_discovery_people_need_an_open_engagement(db, world):
    """VIEW_DISCOVERY_PEOPLE at ASSIGNED scope: only while the auditor is on the client's open engagement."""
    c = make_org(db, name="Charlie Retail")
    done = Engagement(organization_id=c.id, client_id=c.id, name="Charlie 2025", status="completed", stage=9, completed_at=datetime.utcnow() - timedelta(days=30))
    db.add(done)
    db.flush()
    aud = world["users"][Role.AUDITOR]
    db.add(EngagementTeam(organization_id=c.id, engagement_id=done.id, user_id=aud.id, role="auditor"))
    db.commit()
    act = actor(db, aud)
    assert outcome(db, act, Action.VIEW_DISCOVERY_PEOPLE, org_id=c.id) == DENY
    assert outcome(db, act, Action.VIEW_DISCOVERY_PEOPLE, org_id=world["a"].id) == GRANT
    assert outcome(db, act, Action.VIEW_INVENTORY, org_id=c.id) == GRANT  # other ASSIGNED actions keep the closed engagement


def test_unknown_or_removed_roles_grant_nothing(db, world):
    u = make_user(db, world["a"], roles=[], name="No Role", email="none@alpha.test")
    db.commit()
    act = actor(db, u)
    assert all(outcome(db, act, a, org_id=world["a"].id) == DENY for a in Action)


# ---------------------------------------------------------------- matrix shape and pinned spec rules
def test_scope_kinds_match_role_kinds():
    """A Futran role with ORG/DEPT/SYSTEM, or a client role with ALL/ASSIGNED, is a dead cell: authorize ignores it."""
    bad = [(r, a, s) for r, m in MATRIX.items() for a, s in m.items()
           if (r in FUTRAN_ROLES and s in (Scope.ORG, Scope.DEPT, Scope.SYSTEM)) or (r in CLIENT_ROLES and s in (Scope.ALL, Scope.ASSIGNED))]
    assert bad == []
    assert set(MATRIX) == set(Role)


def holders(action: Action) -> set[Role]:
    return {r for r, m in MATRIX.items() if m.get(action, Scope.NONE) != Scope.NONE}


JUDGMENT = [Action.PROPOSE_TIER, Action.SET_FINAL_TIER, Action.OVERRIDE_FINAL_TIER, Action.RECORD_FINDINGS, Action.APPROVE_FINDINGS,
            Action.SCORE_SYSTEM, Action.REVIEW_SCORE_OVERRIDE, Action.VERIFY_REMEDIATION, Action.CLOSE_REMEDIATION]


@pytest.mark.parametrize("action", JUDGMENT, ids=str)
def test_admin_never_holds_tier_or_finding_actions(action):
    """§6 rule 1: Admin can never create, edit or approve findings or risk tiers."""
    assert Role.ADMIN not in holders(action)


@pytest.mark.parametrize("action,allowed", [
    (Action.PROPOSE_TIER, {Role.CAICO, Role.DEPT_COMPLIANCE_LEAD}),  # §6 rule 3: the client proposes
    (Action.SET_FINAL_TIER, {Role.AUDITOR}),  # only an assigned Auditor sets the final tier
    (Action.OVERRIDE_FINAL_TIER, {Role.CHIEF_AUDITOR}),  # only the Chief Auditor overrides
    (Action.VERIFY_REMEDIATION, {Role.AUDITOR}),  # §6 rule 6
    (Action.CLOSE_REMEDIATION, {Role.CHIEF_AUDITOR}),
    (Action.SIGN_EU_CLASSIFICATION, {Role.LEGAL_REVIEWER}),  # spec B8
    (Action.SIGN_FINAL_REPORT, {Role.CHIEF_AUDITOR}),
    (Action.MANAGE_FUTRAN_USERS, {Role.ADMIN}),
    (Action.VIEW_BENCHMARKS, {Role.CHIEF_AUDITOR}),  # benchmarks name the client
], ids=lambda v: str(v) if isinstance(v, str) else None)
def test_pinned_holders(action, allowed):
    assert holders(action) == allowed


def test_clients_never_write_findings():
    """§6 rule 5: clients respond to findings but never edit them."""
    for a in (Action.RECORD_FINDINGS, Action.APPROVE_FINDINGS, Action.SET_FINAL_TIER, Action.OVERRIDE_FINAL_TIER, Action.SCORE_SYSTEM):
        assert not holders(a) & CLIENT_ROLES, a


def test_department_leads_never_see_individual_attestations():
    """§6 rule 8: Department Compliance Leads see department totals only."""
    assert Role.DEPT_COMPLIANCE_LEAD not in holders(Action.VIEW_INDIVIDUAL_ATTESTATIONS)
    assert Role.CONTRIBUTOR not in holders(Action.VIEW_INDIVIDUAL_ATTESTATIONS)


SALES_ROLES = {Role.SALES_TEAM, Role.SALES_MANAGER, Role.PRICING_APPROVER, Role.PRICE_LIST_OWNER}
AUDIT_WORK = [Action.VIEW_ENGAGEMENT, Action.VIEW_EVIDENCE, Action.UPLOAD_EVIDENCE, Action.RECORD_FINDINGS, Action.APPROVE_FINDINGS, Action.VIEW_FINDINGS_RESPONSES,
              Action.VIEW_SCORES, Action.SCORE_SYSTEM, Action.VIEW_FINAL_REPORT, Action.SIGN_FINAL_REPORT, Action.VIEW_INDIVIDUAL_ATTESTATIONS, Action.VIEW_GOVERNANCE,
              Action.VIEW_INVENTORY, Action.EDIT_REGISTER]


@pytest.mark.parametrize("action", AUDIT_WORK, ids=str)
def test_sales_roles_hold_no_audit_work(action):
    """matrix.py WS-D: the Sales Team holds no engagement, evidence, finding, score or report permission."""
    assert not holders(action) & SALES_ROLES


@pytest.mark.parametrize("action", [Action.VIEW_ENGAGEMENT_FEES, Action.VIEW_COMMISSIONS, Action.VIEW_MARGINS], ids=str)
def test_auditors_never_see_money(action):
    """Release 2 B2: fee, commission and margin values are never shown to Auditors or QA."""
    assert not holders(action) & {Role.AUDITOR, Role.QA_REVIEWER}


def test_cell_count():
    cells = len(Role) * len(Action)
    contexts = len(FUTRAN_ROLES) * len(Action) * 6 + (len(CLIENT_ROLES) + 1) * len(Action) * 10
    print(f"\nmatrix cells: {cells} ({sum(len(m) for m in MATRIX.values())} granted); authorize calls checked: {contexts}")
    assert cells == 16 * len(Action)


def _unenforced_actions() -> list[str]:
    """Matrix actions that no code outside app/policy ever checks (by Action.NAME or by its value)."""
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[2] / "app"
    src = "".join(p.read_text(encoding="utf-8") for p in app_dir.rglob("*.py") if "policy" not in p.relative_to(app_dir).parts[:1])
    return [a.name for a in Action if not re.search(rf"\b(?:Action|A)\.{a.name}\b", src) and not re.search(rf"[\"']{a.value}[\"']", src)]


@pytest.mark.xfail(strict=True, reason="FINDING Y02: 8 matrix actions are granted but no route checks them; e.g. sign-offs are signed on VIEW_ENGAGEMENT plus has_role, so SIGN_CLIENT_SIGNOFF and SIGN_FINAL_REPORT govern nothing")
def test_every_matrix_action_is_enforced_somewhere():
    assert _unenforced_actions() == []
