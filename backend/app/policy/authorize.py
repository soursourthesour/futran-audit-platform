"""The single authorization entry point. Every endpoint calls `authorize` (or `get_scoped`).

Rules:
- A resource in another tenant, or an engagement a Futran user is not assigned to, is reported as
  404 (it does not exist for that user). A visible resource the user lacks rights on is 403.
- The tenant always comes from the actor's session, never from request input.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement, EngagementTeam
from app.policy.actions import Action
from app.policy.matrix import Scope, scopes_for


def is_assigned(db: Session, user_id: str, engagement_id: str) -> bool:
    return (
        db.scalar(
            select(EngagementTeam.id).where(
                EngagementTeam.engagement_id == engagement_id,
                EngagementTeam.user_id == user_id,
                EngagementTeam.deleted_at.is_(None),
            )
        )
        is not None
    )


def assigned_engagement_ids(db: Session, user_id: str) -> set[str]:
    return set(
        db.scalars(
            select(EngagementTeam.engagement_id).where(EngagementTeam.user_id == user_id, EngagementTeam.deleted_at.is_(None))
        )
    )


def sees_all_engagements(actor: Actor) -> bool:
    return actor.is_futran and bool(actor.role_names & {"chief_auditor", "admin"})


def visible_org_ids(db: Session, actor: Actor) -> set[str] | None:
    """Client org IDs this actor may see; None means every org (Chief Auditor, Admin)."""
    if not actor.is_futran:
        return {actor.organization.id}
    if sees_all_engagements(actor):
        return None
    ids = assigned_engagement_ids(db, actor.id)
    orgs = set(db.scalars(select(Engagement.client_id).where(Engagement.id.in_(ids)))) if ids else set()
    return orgs | {actor.organization.id}


def can_see_engagement(db: Session, actor: Actor, engagement: Engagement) -> bool:
    if actor.is_futran:
        return sees_all_engagements(actor) or is_assigned(db, actor.id, engagement.id)
    return engagement.client_id == actor.organization.id


def _dept_ok(actor: Actor, department_id: str | None) -> bool:
    if department_id is None:
        return False
    return any(r.scope_type == "department" and r.scope_id == department_id for r in actor.roles)


def _system_ok(actor: Actor, system_id: str | None, department_id: str | None) -> bool:
    if system_id and any(r.scope_type == "system" and r.scope_id == system_id for r in actor.roles):
        return True
    return _dept_ok(actor, department_id)


def authorize(
    db: Session,
    actor: Actor,
    action: Action,
    *,
    engagement_id: str | None = None,
    org_id: str | None = None,
    department_id: str | None = None,
    system_id: str | None = None,
) -> Engagement | None:
    """Raise NotFound/Forbidden unless `actor` may perform `action` on the given resource.

    Returns the Engagement when `engagement_id` is given (already loaded and visibility-checked).
    """
    engagement = None
    if engagement_id is not None:
        engagement = db.get(Engagement, engagement_id)
        if engagement is None or engagement.deleted_at is not None or not can_see_engagement(db, actor, engagement):
            raise NotFound()
        org_id = org_id or engagement.client_id
    if org_id is not None and not actor.is_futran and org_id != actor.organization.id:
        raise NotFound()

    scopes = scopes_for(actor.role_names, action)
    if not scopes:
        raise Forbidden()
    if actor.is_futran:
        if Scope.ALL in scopes:
            return engagement
        if Scope.ASSIGNED in scopes:
            if engagement is None or is_assigned(db, actor.id, engagement.id):
                return engagement
            raise NotFound()
        raise Forbidden()
    # client
    if Scope.ORG in scopes:
        return engagement
    if Scope.DEPT in scopes:
        # With no department named (list views), allow and let the service filter to the actor's departments.
        if (department_id is None and _any_dept_role(actor)) or _dept_ok(actor, department_id):
            return engagement
    if Scope.SYSTEM in scopes and _system_ok(actor, system_id, department_id):
        return engagement
    raise Forbidden()


def _any_dept_role(actor: Actor) -> bool:
    return any(r.scope_type == "department" for r in actor.roles)


def actor_department_ids(actor: Actor) -> set[str]:
    return {r.scope_id for r in actor.roles if r.scope_type == "department" and r.scope_id}


def get_scoped(db: Session, actor: Actor, model, obj_id: str):
    """Load a tenant-owned row by ID, as 404 when it is outside what the actor can see."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "deleted_at", None) is not None:
        raise NotFound()
    allowed = visible_org_ids(db, actor)
    if allowed is not None and obj.organization_id not in allowed:
        raise NotFound()
    return obj
