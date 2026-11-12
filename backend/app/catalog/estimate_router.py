"""SM-15 Estimator API: Sales Officers and Sales Managers. Internal only; estimates are never sent to clients."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.catalog import estimates as est
from app.catalog import service as svc
from app.catalog.models import CatalogItem, Estimate
from app.catalog.router import item_out
from app.core.db import get_db
from app.core.errors import NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(tags=["estimator"])


def _get(db: Session, estimate_id: str) -> Estimate:
    e = db.get(Estimate, estimate_id)
    if e is None:
        raise NotFound()
    return e


@router.get("/sales/estimator")
def reference(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.USE_ESTIMATOR)
    from app.sales.models import Opportunity

    items = []
    for it in db.scalars(select(CatalogItem).where(CatalogItem.status == "active").order_by(CatalogItem.code)):
        why = est.why_not(it)
        items.append({**item_out(db, it), "can_add": why is None, "why_not": why})
    opps = [o for o in db.scalars(select(Opportunity).order_by(Opportunity.created_at.desc())) if o.stage not in ("won", "lost")]
    return {"items": items, "packages": [svc.package_out(db, p) for p in est.packages(db)], "catalog_version": svc.current_version(db),
            "opportunities": [{"id": o.id, "name": est.opportunity_label(db, o)} for o in opps], "regions": est.REGIONS, "terms": list(est.TERMS),
            "discount_limit_pct": svc.settings(db).manager_discount_limit_pct, "can_convert": est.proposal_builder() is not None, "convert_note": None
            if est.proposal_builder() else est.CONVERT_NOTE}


@router.post("/sales/estimates/preview")
def preview(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.USE_ESTIMATOR)
    return est.preview(db, body)


@router.post("/sales/estimates")
def save(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.USE_ESTIMATOR)
    return est.out(db, est.save(db, actor.user, body))


@router.get("/sales/estimates")
def list_estimates(opportunity_id: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.USE_ESTIMATOR)
    stmt = select(Estimate).order_by(Estimate.saved_at.desc())
    if opportunity_id:
        stmt = stmt.where(Estimate.opportunity_id == opportunity_id)
    latest: dict[str, Estimate] = {}
    for e in db.scalars(stmt):
        if e.thread_id not in latest or e.version > latest[e.thread_id].version:
            latest[e.thread_id] = e
    return {"items": [est.out(db, e, full=False) for e in sorted(latest.values(), key=lambda x: x.saved_at, reverse=True)]}


@router.get("/sales/estimates/{estimate_id}")
def get_estimate(estimate_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.USE_ESTIMATOR)
    return est.out(db, _get(db, estimate_id))


@router.post("/sales/estimates/{estimate_id}/convert")
def convert(estimate_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.USE_ESTIMATOR)
    return {"proposal_id": est.convert(db, actor, _get(db, estimate_id))}
