"""G-11 Partners and referrals (`/staff/partners`). Sales Manager and Futran Admin manage; the Sales Officer sees partners
and referrals without commission values; the Chief Auditor reads; Auditors see nothing."""
from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.commercial.access import futran_only, may
from app.core.db import get_db
from app.core.errors import NotFound
from app.files import router as files_router
from app.files.models import FileObject
from app.partners import service as svc
from app.partners.models import Commission, Partner
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(tags=["partners"])


class PartnerIn(BaseModel):
    name: str = Field(max_length=200)
    type: str = Field(max_length=20)
    rate_pct: float | None = None
    agreement_label: str | None = Field(default=None, max_length=120)
    contact_name: str | None = Field(default=None, max_length=160)
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)


class PartnerPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    type: str | None = Field(default=None, max_length=20)
    rate_pct: float | None = None
    agreement_label: str | None = Field(default=None, max_length=120)
    contact_name: str | None = Field(default=None, max_length=160)
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, max_length=10)


class ReferralIn(BaseModel):
    direction: str = Field(max_length=3)
    organization_id: str | None = None
    opportunity_id: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class VoidIn(BaseModel):
    reason: str = Field(max_length=300)


def _screen(db: Session, actor: Actor) -> dict:
    money = may(db, actor, Action.VIEW_COMMISSIONS)
    return svc.screen(db, money=money) | {"can": {"manage": may(db, actor, Action.MANAGE_PARTNERS), "settle": may(db, actor, Action.SETTLE_COMMISSIONS), "see_money": money}}


def _auth(db: Session, actor: Actor, action: Action) -> None:
    futran_only(actor)
    authorize(db, actor, action)


@router.get("/staff/partners")
def list_partners(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _auth(db, actor, Action.VIEW_PARTNERS)
    return _screen(db, actor)


@router.post("/staff/partners")
def add_partner(body: PartnerIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _auth(db, actor, Action.MANAGE_PARTNERS)
    svc.create_partner(db, actor.user, body.model_dump())
    return _screen(db, actor)


@router.patch("/staff/partners/{partner_id}")
def edit_partner(partner_id: str, body: PartnerPatch, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _auth(db, actor, Action.MANAGE_PARTNERS)
    svc.update_partner(db, actor.user, svc.get_partner(db, partner_id), body.model_dump(exclude_unset=True))
    return _screen(db, actor)


@router.post("/staff/partners/{partner_id}/agreement")
async def upload_agreement(partner_id: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor),
                           db: Session = Depends(get_db, scope="function")):
    from app.files.service import upload

    _auth(db, actor, Action.MANAGE_PARTNERS)
    p = svc.get_partner(db, partner_id)
    f = upload(db, request.app.state.settings, actor.user, data=await file.read(), filename=file.filename or "agreement", content_type=file.content_type,
               organization_id=p.organization_id, linked_type="partner_agreement", linked_id=p.id)
    p.agreement_file_id, p.updated_by = f.id, actor.id
    return _screen(db, actor)


@router.post("/staff/partners/{partner_id}/referrals")
def add_referral(partner_id: str, body: ReferralIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _auth(db, actor, Action.MANAGE_PARTNERS)
    svc.record_referral(db, actor.user, svc.get_partner(db, partner_id), direction=body.direction, organization_id=body.organization_id,
                        opportunity_id=body.opportunity_id, note=body.note)
    return _screen(db, actor)


def _commission(db: Session, cid: str) -> Commission:
    c = db.get(Commission, cid)
    if c is None or c.deleted_at is not None:
        raise NotFound()
    return c


@router.post("/staff/partners/commissions/{commission_id}/paid")
def paid(commission_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _auth(db, actor, Action.SETTLE_COMMISSIONS)
    svc.mark_paid(db, actor.user, _commission(db, commission_id))
    return _screen(db, actor)


@router.post("/staff/partners/commissions/{commission_id}/void")
def void(commission_id: str, body: VoidIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _auth(db, actor, Action.SETTLE_COMMISSIONS)
    svc.void(db, actor.user, _commission(db, commission_id), body.reason)
    return _screen(db, actor)


@router.get("/staff/partners/options")
def options(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Clients and open opportunities to attach a referral to."""
    from app.sales.models import Opportunity
    from app.tenancy.models import Organization

    _auth(db, actor, Action.MANAGE_PARTNERS)
    orgs = db.scalars(select(Organization).where(Organization.type == "client", Organization.deleted_at.is_(None)).order_by(Organization.name))
    opps = db.execute(select(Opportunity, Organization.name).join(Organization, Organization.id == Opportunity.organization_id)
                      .where(Opportunity.stage.not_in(["lost"])).order_by(Opportunity.created_at.desc()).limit(300))
    return {"clients": [{"id": o.id, "name": o.name} for o in orgs],
            "opportunities": [{"id": o.id, "label": f"{name}: {o.service}"} for o, name in opps]}


def _agreement_access(db: Session, actor: Actor, f: FileObject) -> None:
    """A partner agreement holds the commission terms: the same people who see commissions download it."""
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.VIEW_COMMISSIONS)
    if db.get(Partner, f.linked_id or "") is None:
        raise NotFound()


files_router.FILE_ACCESS["partner_agreement"] = _agreement_access
