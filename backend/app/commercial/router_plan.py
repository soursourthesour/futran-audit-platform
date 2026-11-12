"""G-01 Plans, entitlements and usage (`/staff/clients/:id/plan`) and the billing export. Futran Admin edits and runs
the export; the Chief Auditor and Sales Manager read."""
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.commercial import plans
from app.commercial.access import client_for, futran_only, may
from app.commercial.models import BillingExportRun
from app.core.db import get_db
from app.core.errors import NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization

router = APIRouter(tags=["plans"])


class PlanSettingsIn(BaseModel):
    tier: str | None = Field(default=None, max_length=60)
    term_end_on: date | None = None
    auto_renew: bool | None = None
    data_region: str | None = Field(default=None, max_length=4)
    migration_ticket: str | None = Field(default=None, max_length=80)
    support_level: str | None = Field(default=None, max_length=30)
    onboarding_fee_waived: bool | None = None


class ExportIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    client_id: str | None = None


def _view(db: Session, actor: Actor, org: Organization) -> dict:
    return plans.plan_view(db, org) | {"can_edit": may(db, actor, Action.MANAGE_CLIENT_PLAN, org_id=org.id),
                                       "can_export": may(db, actor, Action.RUN_BILLING_EXPORT, org_id=org.id)}


@router.get("/staff/clients/{client_id}/plan")
def get_plan(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _view(db, actor, client_for(db, actor, Action.VIEW_CLIENT_PLAN, client_id))


@router.patch("/staff/clients/{client_id}/plan")
def patch_plan(client_id: str, body: PlanSettingsIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_for(db, actor, Action.MANAGE_CLIENT_PLAN, client_id)
    plans.update_settings(db, actor.user, org, body.model_dump(exclude_unset=True))
    return _view(db, actor, org)


def _run_out(db: Session, r: BillingExportRun) -> dict:
    org = db.get(Organization, r.client_id) if r.client_id else None
    return {"id": r.id, "period": r.period, "client_id": r.client_id, "client_name": org.name if org else None, "rows": r.rows, "run_at": r.run_at.isoformat(), "status": r.status}


@router.get("/staff/billing-export")
def list_exports(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    futran_only(actor)
    authorize(db, actor, Action.RUN_BILLING_EXPORT)
    from sqlalchemy import select

    return [_run_out(db, r) for r in db.scalars(select(BillingExportRun).order_by(BillingExportRun.run_at.desc()).limit(50))]


@router.post("/staff/billing-export")
def run_export(body: ExportIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    futran_only(actor)
    if body.client_id:
        client_for(db, actor, Action.RUN_BILLING_EXPORT, body.client_id)
    else:
        authorize(db, actor, Action.RUN_BILLING_EXPORT)
    return _run_out(db, plans.run_export(db, actor.user, body.period, body.client_id))


@router.get("/staff/billing-export/{run_id}.csv")
def download(run_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    futran_only(actor)
    authorize(db, actor, Action.RUN_BILLING_EXPORT)
    r = db.get(BillingExportRun, run_id)
    if r is None:
        raise NotFound()
    org = db.get(Organization, r.client_id) if r.client_id else None
    name = f"billing-{r.period}-{(org.client_ref if org else 'all-clients')}.csv"
    return Response(r.content or "", media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})
