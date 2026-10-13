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
from app.policy.matrix import MATRIX, Scope
from app.policy.roles import Role


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


def _role_scope(role: str, action: Action) -> Scope:
    try:
        return MATRIX.get(Role(role), {}).get(action, Scope.NONE)
    except ValueError:
        return Scope.NONE


def authorize(
    db: Session,
    actor: Actor,
    action: Action,
    *,
    engagement_id: str | None = None,
    org_id: str | None = None,
    department_id: str | None = None,
    system_id: str | None = None,
    list_view: bool = False,
) -> Engagement | None:
    """Raise NotFound/Forbidden unless `actor` may perform `action` on the given resource.

    Each role assignment only lends its own scope: a Contributor assignment in Finance never satisfies
    a Department Compliance Lead permission for Finance. `list_view=True` allows an ASSIGNED/DEPT
    permission with no specific resource; the caller must then filter rows itself.
    Returns the Engagement when `engagement_id` is given.
    """
    engagement = None
    if engagement_id is not None:
        engagement = db.get(Engagement, engagement_id)
        if engagement is None or engagement.deleted_at is not None or not can_see_engagement(db, actor, engagement):
            raise NotFound()
        org_id = org_id or engagement.client_id
    if org_id is not None:
        allowed = visible_org_ids(db, actor)
        if allowed is not None and org_id not in allowed:
            raise NotFound()

    granted = False
    for ra in actor.roles:
        scope = _role_scope(ra.role, action)
        if scope == Scope.NONE:
            continue
        if actor.is_futran:
            if scope == Scope.ALL:
                granted = True
            elif scope == Scope.ASSIGNED:
                if engagement is not None:
                    granted = is_assigned(db, actor.id, engagement.id)
                elif org_id is not None:
                    granted = True  # org already checked against visible_org_ids
                else:
                    granted = list_view
        else:
            if scope == Scope.ORG:
                granted = True
            elif scope == Scope.DEPT:
                if ra.scope_type == "department":
                    granted = (department_id is None and list_view) or ra.scope_id == department_id
            elif scope == Scope.SYSTEM:
                if ra.scope_type == "system":
                    granted = (system_id is None and list_view) or ra.scope_id == system_id
                elif ra.scope_type == "department":
                    granted = (department_id is None and list_view) or (department_id is not None and ra.scope_id == department_id)
        if granted:
            return engagement
    raise Forbidden()


def departments_for(actor: Actor, action: Action) -> set[str] | None:
    """For client list views: the departments whose rows `actor` may see for `action`; None = the whole org."""
    out: set[str] = set()
    for ra in actor.roles:
        scope = _role_scope(ra.role, action)
        if scope == Scope.ORG:
            return None
        if scope in (Scope.DEPT, Scope.SYSTEM) and ra.scope_type == "department" and ra.scope_id:
            out.add(ra.scope_id)
    return out


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
    eng_id = getattr(obj, "engagement_id", None)
    if eng_id is not None:
        eng = db.get(Engagement, eng_id)
        if eng is None or not can_see_engagement(db, actor, eng):
            raise NotFound()
    return obj
