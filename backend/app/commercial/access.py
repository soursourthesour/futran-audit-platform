"""Authorization for commercial screens. Every endpoint goes through `authorize`.

Sales roles hold their commercial actions at ALL scope but are on no engagement team, so `authorize` with a resource
would hide every client from them. When a person holds the action at ALL scope we authorize the action alone and load
the row ourselves; otherwise (an Engagement Manager on the team) we authorize against the engagement as usual.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.deps import Actor
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import _role_scope, authorize
from app.policy.matrix import Scope
from app.tenancy.models import Organization


def holds_all(actor: Actor, action: Action) -> bool:
    return actor.is_futran and any(_role_scope(r.role, action) == Scope.ALL for r in actor.roles)


def may(db: Session, actor: Actor, action: Action, **kw) -> bool:
    try:
        if holds_all(actor, action):
            authorize(db, actor, action)
        else:
            authorize(db, actor, action, **kw)
        return True
    except (Forbidden, NotFound):
        return False


def futran_only(actor: Actor) -> None:
    if not actor.is_futran:
        raise NotFound()


def engagement_for(db: Session, actor: Actor, action: Action, engagement_id: str) -> Engagement:
    futran_only(actor)
    e = db.get(Engagement, engagement_id)
    if e is None or e.deleted_at is not None:
        raise NotFound()
    if holds_all(actor, action):
        authorize(db, actor, action)
    else:
        authorize(db, actor, action, engagement_id=e.id)
    return e


def client_for(db: Session, actor: Actor, action: Action, client_id: str) -> Organization:
    futran_only(actor)
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at is not None:
        raise NotFound()
    if holds_all(actor, action):
        authorize(db, actor, action)
    else:
        authorize(db, actor, action, org_id=org.id)
    return org
