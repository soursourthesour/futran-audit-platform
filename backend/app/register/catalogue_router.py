"""The Futran Admin's AI model list in reference data (11-03 C12)."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth.deps import Actor, current_actor
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.register import catalogue as cat
from sqlalchemy.orm import Session

router = APIRouter(tags=["register"])


class VendorIn(BaseModel):
    name: str | None = None
    active: bool | None = None
    source_url: str | None = None


class ModelIn(BaseModel):
    vendor_id: str | None = None
    name: str | None = None
    active: bool | None = None


class DecideIn(BaseModel):
    accept: bool


def _admin(db: Session, actor: Actor) -> None:
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.MANAGE_REFERENCE_DATA)


@router.get("/admin/model-catalogue")
def get_catalogue(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _admin(db, actor)
    return cat.admin_page(db)


@router.post("/admin/model-catalogue/vendors")
def post_vendor(body: VendorIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _admin(db, actor)
    v = cat.add_vendor(db, actor.user, body.name or "", body.source_url)
    return {"id": v.id, "code": v.code, "name": v.name, "active": v.active}


@router.patch("/admin/model-catalogue/vendors/{vendor_id}")
def patch_vendor(vendor_id: str, body: VendorIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _admin(db, actor)
    v = cat.edit_vendor(db, actor.user, cat.get_vendor(db, vendor_id), body.model_dump(exclude_unset=True))
    return {"id": v.id, "code": v.code, "name": v.name, "active": v.active}


@router.post("/admin/model-catalogue/models")
def post_model(body: ModelIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _admin(db, actor)
    m = cat.add_model(db, actor.user, cat.get_vendor(db, body.vendor_id or ""), body.name or "")
    return {"id": m.id, "name": m.name, "active": m.active}


@router.patch("/admin/model-catalogue/models/{model_id}")
def patch_model(model_id: str, body: ModelIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _admin(db, actor)
    m = cat.edit_model(db, actor.user, cat.get_model(db, model_id), body.model_dump(exclude_unset=True, exclude={"vendor_id"}))
    return {"id": m.id, "name": m.name, "active": m.active}


@router.post("/admin/model-catalogue/proposals/{proposal_id}/decide")
def post_decide(proposal_id: str, body: DecideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _admin(db, actor)
    p = cat.decide(db, actor.user, cat.get_proposal(db, proposal_id), body.accept)
    return {"id": p.id, "status": p.status}


@router.post("/admin/model-catalogue/check")
def post_check(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Run the monthly check now. It does not use up the month's scheduled check."""
    _admin(db, actor)
    cat.run_monthly(db, request.app.state.settings, utcnow(), request.app.state, manual_by=actor.user)
    return cat.admin_page(db)
