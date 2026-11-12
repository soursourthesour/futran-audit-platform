"""G-10 Evidence vault and retention (`/staff/clients/:id/vault`). Chief Auditor and Futran Admin. The Chief Auditor
places and releases legal holds; either sets the retention tier."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.commercial.access import futran_only, may
from app.core.clock import today
from app.core.db import get_db
from app.core.errors import NotFound
from app.engagements.models import Engagement
from app.hierarchy.service import load_client
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization, User
from app.vault import register  # noqa: F401  legal holds feed G-01 usage
from app.vault import service as vault
from app.vault.models import TIERS, LegalHold, RetentionPolicy

router = APIRouter(tags=["evidence vault"])


class TierIn(BaseModel):
    years: int
    reason: str | None = Field(default=None, max_length=300)


class HoldIn(BaseModel):
    name: str = Field(max_length=200)
    matter_ref: str | None = Field(default=None, max_length=200)
    reason: str = Field(max_length=4000)
    scope: dict = Field(default_factory=dict)


class ReleaseIn(BaseModel):
    reason: str = Field(max_length=4000)


def _client(db: Session, actor: Actor, action: Action, client_id: str) -> Organization:
    futran_only(actor)
    authorize(db, actor, action)
    return load_client(db, client_id)


def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def _hold_out(db: Session, h: LegalHold) -> dict:
    return {"id": h.id, "ref": h.ref, "name": h.name, "matter_ref": h.matter_ref, "reason": h.reason, "scope": h.scope, "scope_label": vault.scope_label(db, h),
            "set_by": _name(db, h.set_by), "set_at": h.set_at.isoformat(), "active": h.released_at is None,
            "released_at": h.released_at.isoformat() if h.released_at else None, "released_by": _name(db, h.released_by), "release_reason": h.release_reason}


def _storage(db: Session, org: Organization) -> dict:
    used = vault.storage_used_gb(db, org.id)
    limit = code = measured_on = None
    try:
        from app.commercial import plans
        from app.commercial.models import OrderLine

        sub = plans.current_subscription(db, org.id)
        ents = plans.entitlements(db, sub).get("vault_gb", []) if sub else []
        if ents:
            limit = sum(e.limit for e in ents)
            ol = db.get(OrderLine, ents[0].source_order_line_id) if ents[0].source_order_line_id else None
            code = ol.catalog_code if ol else None
        rec = plans.latest_usage(db, org.id).get("vault_gb")
        measured_on = rec[1].isoformat() if rec else None
    except Exception:  # noqa: BLE001  the plan module is optional here; storage still shows
        pass
    return {"used_gb": used, "limit_gb": limit, "plan_code": code, "measured_on": measured_on,
            "pct": round(100 * used / limit) if limit else None}


def _view(db: Session, actor: Actor, request: Request, org: Organization) -> dict:
    from app.systems.models import AISystem

    settings = request.app.state.settings
    p = vault.current_policy(db, org.id)
    history = list(db.scalars(select(RetentionPolicy).where(RetentionPolicy.organization_id == org.id).order_by(RetentionPolicy.created_at.desc()).limit(10)))
    items = vault.countdown(db, settings, org, today())
    hs = vault.holds(db, org.id)
    engs = list(db.scalars(select(Engagement).where(Engagement.client_id == org.id, Engagement.deleted_at.is_(None)).order_by(Engagement.created_at)))
    systems = list(db.scalars(select(AISystem).where(AISystem.organization_id == org.id, AISystem.deleted_at.is_(None)).order_by(AISystem.reference_id)))
    eng_names = {e.id: e.name for e in engs}
    return {
        "client": {"id": org.id, "name": org.name},
        "storage": _storage(db, org),
        "retention": {"years": p.years if p else settings.retention_years_default, "is_default": p is None, "tiers": list(TIERS),
                      "kept_longer_by_letter": vault.kept_longer_by_letter(db, settings, org.id, p.years if p else settings.retention_years_default),
                      "effective_from": p.effective_from.isoformat() if p else None, "set_by": _name(db, p.set_by) if p else None, "reason": p.reason if p else None,
                      "history": [{"years": r.years, "effective_from": r.effective_from.isoformat(), "set_by": _name(db, r.set_by), "reason": r.reason} for r in history]},
        "holds": [_hold_out(db, h) for h in hs],
        "active_holds": sum(1 for h in hs if h.released_at is None),
        "countdown": {"items": items, "total": len(items), "held": sum(1 for i in items if i["hold"]), "will_delete": sum(1 for i in items if not i["hold"])},
        "scope_options": {"engagements": [{"id": e.id, "name": e.name, "audit_ref": e.audit_ref} for e in engs],
                          "systems": [{"id": s.id, "name": s.name, "reference": s.reference_id, "engagement": eng_names.get(s.engagement_id)} for s in systems]},
        "can": {"set_tier": may(db, actor, Action.SET_RETENTION_TIER), "manage_holds": may(db, actor, Action.MANAGE_LEGAL_HOLDS)},
    }


@router.get("/staff/clients/{client_id}/vault")
def get_vault(client_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _view(db, actor, request, _client(db, actor, Action.VIEW_VAULT, client_id))


@router.put("/staff/clients/{client_id}/vault/retention")
def put_tier(client_id: str, body: TierIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(db, actor, Action.SET_RETENTION_TIER, client_id)
    vault.set_tier(db, actor.user, org, body.years, body.reason, request.app.state.settings)
    return _view(db, actor, request, org)


@router.post("/staff/clients/{client_id}/vault/holds")
def post_hold(client_id: str, body: HoldIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(db, actor, Action.MANAGE_LEGAL_HOLDS, client_id)
    vault.place_hold(db, actor.user, org, name=body.name, matter_ref=body.matter_ref, reason=body.reason, scope=body.scope)
    return _view(db, actor, request, org)


@router.post("/staff/clients/{client_id}/vault/holds/{hold_id}/release")
def post_release(client_id: str, hold_id: str, body: ReleaseIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(db, actor, Action.MANAGE_LEGAL_HOLDS, client_id)
    h = db.get(LegalHold, hold_id)
    if h is None or h.organization_id != org.id or h.deleted_at is not None:
        raise NotFound()
    vault.release_hold(db, actor.user, h, body.reason)
    return _view(db, actor, request, org)
