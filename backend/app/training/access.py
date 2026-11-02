"""Who runs AI literacy training (spec §21 F12, screen 33): the CAICO and Client Admin by platform role, and the person
assigned to the company-wide "AI literacy and training owner" governance role (§24.1 row 7) even without a platform role
that grants it. Every check goes through `authorize`."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor
from app.core.errors import Forbidden, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.register.models import GovernanceRoleAssignment

LITERACY_ROLE = "ai_literacy_owner"
OWNER_ACTIONS = (Action.VIEW_TRAINING, Action.MANAGE_TRAINING)


def client_org(actor: Actor):
    if actor.is_futran:
        raise NotFound()
    return actor.organization


def owner_assignments(db: Session, org_id: str) -> list[GovernanceRoleAssignment]:
    from app.regmaster.models import RoleCatalog

    role = db.scalar(select(RoleCatalog).where(RoleCatalog.code == LITERACY_ROLE))
    if role is None:
        return []
    return list(db.scalars(select(GovernanceRoleAssignment).where(
        GovernanceRoleAssignment.organization_id == org_id, GovernanceRoleAssignment.role_id == role.id, GovernanceRoleAssignment.deleted_at.is_(None),
        GovernanceRoleAssignment.register_system_id.is_(None), GovernanceRoleAssignment.status == "assigned")))


def is_literacy_owner(db: Session, actor: Actor) -> bool:
    if actor.is_futran:
        return False
    return any(actor.id in {a.user_id, a.backup_user_id, *(a.extra_user_ids or [])} for a in owner_assignments(db, actor.organization.id))


def check(db: Session, actor: Actor, action: Action) -> None:
    org = client_org(actor)
    try:
        authorize(db, actor, action, org_id=org.id)
    except Forbidden:
        if action in OWNER_ACTIONS and is_literacy_owner(db, actor):
            authorize(db, actor, Action.COMPLETE_OWN_TRAINING, org_id=org.id)  # still a signed-in member of this client
            return
        raise


def may(db: Session, actor: Actor, action: Action) -> bool:
    try:
        check(db, actor, action)
        return True
    except (Forbidden, NotFound):
        return False
