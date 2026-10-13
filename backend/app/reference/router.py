from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Conflict, Invalid, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.reference.jurisdictions import by_code, resolve_jurisdictions, upsert_city
from app.reference.models import Jurisdiction, JurisdictionMembership

router = APIRouter(prefix="/jurisdictions", tags=["reference"])


class JurisdictionIn(BaseModel):
    name: str
    level: str  # state | city | country | supranational
    parent_code: str | None = None
    code: str | None = None
    aliases: list[str] = []
    member_of: list[str] = []


class JurisdictionPatch(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    active: bool | None = None
    member_of: list[str] | None = None


def j_out(j: Jurisdiction, parent_code: str | None = None) -> dict:
    return {"id": j.id, "code": j.code, "name": j.name, "level": j.level, "parent_code": parent_code, "has_laws": j.has_laws, "aliases": j.aliases or [], "active": j.active, "feature_notes": j.feature_notes or {}}


@router.get("")
def list_jurisdictions(level: str | None = None, parent: str | None = None, has_laws: bool | None = None, q: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    stmt = select(Jurisdiction).where(Jurisdiction.active.is_(True))
    if level:
        stmt = stmt.where(Jurisdiction.level == level)
    if parent:
        p = by_code(db, parent.upper())
        if p is None:
            raise NotFound()
        stmt = stmt.where(Jurisdiction.parent_id == p.id)
    if has_laws is not None:
        stmt = stmt.where(Jurisdiction.has_laws.is_(has_laws))
    if q:
        stmt = stmt.where(func.lower(Jurisdiction.name).like(f"%{q.lower()}%"))
    parents = dict(db.execute(select(Jurisdiction.id, Jurisdiction.code)).all()) if (has_laws or q) else {}
    rows = db.scalars(stmt.order_by(Jurisdiction.name).limit(2000))
    return [j_out(j, parents.get(j.parent_id)) for j in rows]


@router.get("/resolve")
def resolve(country: str, subdivision: str | None = None, city: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return [j_out(j) for j in resolve_jurisdictions(db, country, subdivision, city)]


@router.post("")
def add_jurisdiction(body: JurisdictionIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_REFERENCE_DATA)
    if body.level == "city":
        if not body.parent_code:
            raise Invalid(errors=[{"field": "parent_code", "message": "Choose the state or province the city is in."}])
        try:
            j = upsert_city(db, body.parent_code.upper(), body.name.strip(), code=body.code, aliases=body.aliases or [body.name], actor_id=actor.id)
        except ValueError as exc:
            raise Invalid(str(exc))
    else:
        if body.level not in ("state", "country", "supranational"):
            raise Invalid(errors=[{"field": "level", "message": "Level must be supranational, country, state or city."}])
        code = (body.code or "").upper().strip()
        if not code:
            raise Invalid(errors=[{"field": "code", "message": "Give the jurisdiction a code, for example GB-SCT."}])
        if by_code(db, code):
            raise Conflict(f"A jurisdiction with code {code} already exists.")
        parent = by_code(db, body.parent_code.upper()) if body.parent_code else None
        j = Jurisdiction(code=code, name=body.name.strip(), level=body.level, parent_id=parent.id if parent else None, aliases=body.aliases, updated_by=actor.id)
        db.add(j)
        db.flush()
    _set_memberships(db, j, body.member_of)
    audit.record(db, actor_id=actor.id, action="jurisdiction.add", object_type="Jurisdiction", object_id=j.id, organization_id=actor.organization.id, after=j_out(j), summary=f"Added jurisdiction {j.name} ({j.code})")
    return j_out(j)


@router.patch("/{code}")
def patch_jurisdiction(code: str, body: JurisdictionPatch, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_REFERENCE_DATA)
    j = by_code(db, code.upper())
    if j is None:
        raise NotFound()
    before = j_out(j)
    if body.name is not None:
        j.name = body.name.strip()
    if body.aliases is not None:
        j.aliases = body.aliases
    if body.active is not None:
        j.active = body.active
    if body.member_of is not None:
        _set_memberships(db, j, body.member_of)
    j.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="jurisdiction.edit", object_type="Jurisdiction", object_id=j.id, organization_id=actor.organization.id, before=before, after=j_out(j))
    return j_out(j)


def _set_memberships(db: Session, j: Jurisdiction, groups: list[str]) -> None:
    if not groups:
        return
    for g in groups:
        grp = by_code(db, g.upper())
        if grp is None or grp.level != "supranational":
            raise Invalid(errors=[{"field": "member_of", "message": f"{g} is not a supranational group."}])
        exists = db.scalar(select(JurisdictionMembership).where(JurisdictionMembership.member_id == j.id, JurisdictionMembership.group_id == grp.id))
        if not exists:
            db.add(JurisdictionMembership(member_id=j.id, group_id=grp.id))
    db.flush()
