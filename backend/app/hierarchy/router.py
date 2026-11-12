"""G-04 client hierarchy: Futran (`/staff/clients/:id/entities`) and the client CAICO's group view and consent (`/group`)."""
from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.commercial.access import futran_only, may
from app.core.db import get_db
from app.core.errors import NotFound
from app.hierarchy import service as h
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization

router = APIRouter(tags=["client hierarchy"])


class EntityIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    relationship: str = Field(max_length=20)
    parent_id: str | None = None
    industry: str | None = Field(default=None, max_length=80)
    hq_city: str | None = Field(default=None, max_length=120)
    hq_state: str | None = Field(default=None, max_length=120)


class LinkIn(BaseModel):
    child_id: str
    relationship: str = Field(max_length=20)


class RelationshipIn(BaseModel):
    relationship: str = Field(max_length=20)


class ScopeIn(BaseModel):
    ll144_in_scope: bool = False
    aedt_system_ids: list[str] = Field(default_factory=list, max_length=50)
    roles_note: str | None = Field(default=None, max_length=300)
    own_public_summary: bool = False
    vendor_allows_summary: bool = False


def _client(db: Session, actor: Actor, action: Action, client_id: str) -> Organization:
    """Futran staff with the action at ALL scope (Chief Auditor, Futran Admin) reach every client; nobody else does."""
    futran_only(actor)
    authorize(db, actor, action)
    return h.load_client(db, client_id)


def _in_group(db: Session, root_client: Organization, entity_id: str) -> Organization:
    o = h.load_client(db, entity_id)
    if h.group_root(db, o).id != h.group_root(db, root_client).id:
        raise NotFound()
    return o


def _tree(db: Session, actor: Actor, org: Organization) -> dict:
    return h.futran_tree(db, org) | {"can_manage": may(db, actor, Action.MANAGE_CLIENT_HIERARCHY)}


@router.get("/staff/clients/{client_id}/entities")
def get_tree(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _tree(db, actor, _client(db, actor, Action.VIEW_CLIENT_HIERARCHY, client_id))


@router.post("/staff/clients/{client_id}/entities")
def add_entity(client_id: str, body: EntityIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(db, actor, Action.MANAGE_CLIENT_HIERARCHY, client_id)
    parent = _in_group(db, org, body.parent_id) if body.parent_id else org
    child = h.add_entity(db, actor.user, parent, body.name, body.relationship, industry=body.industry, hq_city=body.hq_city, hq_state=body.hq_state)
    return {"id": child.id, "tree": _tree(db, actor, org)}


@router.post("/staff/clients/{client_id}/entities/import")
async def import_entities(client_id: str, apply: bool = False, file: UploadFile = File(...), actor: Actor = Depends(current_actor),
                          db: Session = Depends(get_db, scope="function")):
    """Import end-clients from CSV: a preview first (apply=false), then the same file with apply=true."""
    org = _client(db, actor, Action.MANAGE_CLIENT_HIERARCHY, client_id)
    return h.import_end_clients(db, actor.user, org, await file.read(), apply=apply)


@router.post("/staff/clients/{client_id}/entities/link")
def link_entity(client_id: str, body: LinkIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    parent = _client(db, actor, Action.MANAGE_CLIENT_HIERARCHY, client_id)
    h.link(db, actor.user, parent, h.load_client(db, body.child_id), body.relationship)
    return _tree(db, actor, parent)


@router.patch("/staff/entities/{entity_id}")
def patch_entity(entity_id: str, body: RelationshipIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    child = _client(db, actor, Action.MANAGE_CLIENT_HIERARCHY, entity_id)
    h.set_relationship(db, actor.user, child, body.relationship)
    return _tree(db, actor, child)


@router.post("/staff/entities/{entity_id}/unlink")
def unlink_entity(entity_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    child = _client(db, actor, Action.MANAGE_CLIENT_HIERARCHY, entity_id)
    parent = db.get(Organization, child.parent_id) if child.parent_id else None
    h.unlink(db, actor.user, child)
    return _tree(db, actor, parent or child)


@router.put("/staff/entities/{entity_id}/ll144")
def put_scope(entity_id: str, body: ScopeIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    child = _client(db, actor, Action.MANAGE_CLIENT_HIERARCHY, entity_id)
    h.set_scope(db, actor.user, child, body.model_dump())
    return _tree(db, actor, child)


# ---- client side: the CAICO's own group. The tenant is the session's organization, never a request parameter.
def _own(db: Session, actor: Actor, action: Action) -> Organization:
    if actor.is_futran:
        raise NotFound()
    authorize(db, actor, action, org_id=actor.organization.id)
    return actor.organization


@router.get("/group")
def my_group(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _own(db, actor, Action.VIEW_GROUP)
    return h.client_group(db, actor.user, org) | {"can_give_consent": may(db, actor, Action.GIVE_ROLLUP_CONSENT, org_id=org.id)}


@router.post("/group/consent")
def consent(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _own(db, actor, Action.GIVE_ROLLUP_CONSENT)
    h.give_consent(db, actor.user, org)
    return h.client_group(db, actor.user, org)


@router.post("/group/consent/revoke")
def revoke(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _own(db, actor, Action.GIVE_ROLLUP_CONSENT)
    h.revoke_consent(db, actor.user, org)
    return h.client_group(db, actor.user, org)
