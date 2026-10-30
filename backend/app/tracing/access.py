"""Who may use the tracing add-on on a system, and whether the add-on covers it (spec §27.3, §27.8).

The tenant is always the signed-in user's organization. Every check goes through `authorize`. The AI Incident Response
Lead is a governance role (§24.1 row 6), not a platform role: a person assigned to it (company-wide or on the system) may
read the Tracing tab and work on incidents even without a platform role that grants it.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor
from app.core.errors import Forbidden, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.register.models import GovernanceRoleAssignment, RegisterSystem
from app.tracing.models import AddonSubscription

INCIDENT_LEAD_ROLE = "incident_response_lead"
LEAD_ACTIONS = (Action.VIEW_TRACING, Action.MANAGE_INCIDENTS)


def client_org(actor: Actor):
    if actor.is_futran:
        raise NotFound()  # a client screen: Futran sees the request only as an Opportunity
    return actor.organization


def is_incident_lead(db: Session, actor: Actor, s: RegisterSystem) -> bool:
    from app.regmaster.models import RoleCatalog

    role = db.scalar(select(RoleCatalog).where(RoleCatalog.code == INCIDENT_LEAD_ROLE))
    if role is None:
        return False
    rows = db.scalars(select(GovernanceRoleAssignment).where(
        GovernanceRoleAssignment.organization_id == s.organization_id, GovernanceRoleAssignment.role_id == role.id, GovernanceRoleAssignment.deleted_at.is_(None),
        GovernanceRoleAssignment.status == "assigned", (GovernanceRoleAssignment.register_system_id.is_(None)) | (GovernanceRoleAssignment.register_system_id == s.id)))
    return any(actor.id in {r.user_id, r.backup_user_id, *(r.extra_user_ids or [])} for r in rows)


def incident_leads(db: Session, org_id: str, s: RegisterSystem | None = None) -> list[str]:
    from app.regmaster.models import RoleCatalog

    role = db.scalar(select(RoleCatalog).where(RoleCatalog.code == INCIDENT_LEAD_ROLE))
    if role is None:
        return []
    stmt = select(GovernanceRoleAssignment).where(GovernanceRoleAssignment.organization_id == org_id, GovernanceRoleAssignment.role_id == role.id,
                                                  GovernanceRoleAssignment.deleted_at.is_(None), GovernanceRoleAssignment.status == "assigned")
    ids: list[str] = []
    for r in db.scalars(stmt):
        if r.register_system_id is None or (s is not None and r.register_system_id == s.id):
            ids += [i for i in (r.user_id, r.backup_user_id, *(r.extra_user_ids or [])) if i and i not in ids]
    return ids


def load_system(db: Session, actor: Actor, system_id: str) -> RegisterSystem:
    """The system, as 404 when it is outside the actor's organization or (for a Department Head) department."""
    org = client_org(actor)
    s = db.get(RegisterSystem, system_id)
    if s is None or s.deleted_at is not None or s.organization_id != org.id:
        raise NotFound()
    depts = departments_for(actor, Action.VIEW_TRACING)
    if depts and not s.company_wide and s.department_id not in depts and not is_incident_lead(db, actor, s):
        raise NotFound()
    return s


def check(db: Session, actor: Actor, action: Action, s: RegisterSystem) -> None:
    org = client_org(actor)
    try:
        if s.company_wide and departments_for(actor, action) is not None:
            raise Forbidden("Company-wide tools are handled by the AI Compliance Officer.")
        authorize(db, actor, action, org_id=org.id, department_id=s.department_id)
    except Forbidden:
        if action in LEAD_ACTIONS and is_incident_lead(db, actor, s):
            return
        raise


def may(db: Session, actor: Actor, action: Action, s: RegisterSystem) -> bool:
    try:
        check(db, actor, action, s)
    except (Forbidden, NotFound):
        return False
    return True


# ---- what the add-on covers
def subscriptions(db: Session, org_id: str, statuses=("requested", "active")) -> list[AddonSubscription]:
    return list(db.scalars(select(AddonSubscription).where(AddonSubscription.organization_id == org_id, AddonSubscription.addon == "tracing",
                                                           AddonSubscription.deleted_at.is_(None), AddonSubscription.status.in_(statuses)).order_by(AddonSubscription.requested_at)))


def covers(sub: AddonSubscription, s: RegisterSystem) -> bool:
    if sub.plan == "enterprise":
        return True
    if sub.plan == "tier_2_3" and s.risk_tier in (2, 3):
        return True
    return s.id in (sub.ai_system_ids or [])


def state_for(db: Session, s: RegisterSystem, subs: list[AddonSubscription] | None = None) -> tuple[str, AddonSubscription | None]:
    """("active", sub) when an active subscription covers the system, ("requested", sub) while one waits for approval, else ("locked", None)."""
    subs = subscriptions(db, s.organization_id) if subs is None else subs
    active = next((x for x in subs if x.status == "active" and covers(x, s)), None)
    if active is not None:
        return "active", active
    req = next((x for x in subs if x.status == "requested" and covers(x, s)), None)
    return ("requested", req) if req is not None else ("locked", None)
