"""S1 opportunities (spec §27.5). Sales Team and Chief Auditor; only the Chief Auditor approves offers to audit clients."""
import csv
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.clock import today, utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Invalid, NotFound
from app.core.models import column_snapshot
from app.litigation.service import TYPE_LABELS
from app.notifications.service import notify
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.sales.models import ACTIVITY_KINDS, SERVICE_KINDS, STAGES, TRIGGER_LABELS, Opportunity, OpportunityActivity
from app.sales.service import can_send_offer, check_independence, is_current_audit_client, log
from app.tenancy.models import Organization, User
from app.tenancy.service import roles_of

router = APIRouter(tags=["opportunities"])

STAGE_LABELS = {"new": "New", "contacted": "Contacted", "proposal": "Proposal", "won": "Won", "lost": "Lost"}


def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def opp_out(db: Session, o: Opportunity) -> dict:
    org = db.get(Organization, o.organization_id)
    if o.needs_ca_approval:
        approval = {"approved": "Approved", "declined": "Declined"}.get(o.ca_decision or "", "Requested" if o.approval_requested_at else "Needed")
    else:
        approval = "Not needed"
    return {
        "id": o.id, "organization_id": o.organization_id, "client_name": org.name if org else "", "trigger": o.trigger,
        "trigger_label": TRIGGER_LABELS.get(o.trigger, o.trigger), "trigger_ref": o.trigger_ref, "service": o.service, "service_kind": o.service_kind,
        "why_now": o.why_now, "value": o.value, "owner_id": o.owner_id, "owner_name": _name(db, o.owner_id), "stage": o.stage,
        "stage_label": STAGE_LABELS.get(o.stage, o.stage), "next_step": o.next_step,
        "system_types": [TYPE_LABELS.get(t, t) for t in o.system_types or []], "system_count": len(o.system_ids or []),
        "addon_status": o.addon_status, "needs_ca_approval": o.needs_ca_approval, "approval": approval, "ca_decision": o.ca_decision,
        "ca_approved_by_name": _name(db, o.ca_approved_by), "ca_approved_at": o.ca_approved_at.isoformat() if o.ca_approved_at else None,
        "ca_note": o.ca_note, "can_send_offer": can_send_offer(o), "approval_requested_at": o.approval_requested_at.isoformat() if o.approval_requested_at else None,
        "created_at": o.created_at.isoformat(), "closed_at": o.closed_at.isoformat() if o.closed_at else None,
    }


def _get(db: Session, oid: str) -> Opportunity:
    o = db.get(Opportunity, oid)
    if o is None:
        raise NotFound()
    return o


def _owners(db: Session, futran_org_id: str) -> list[User]:
    users = db.scalars(select(User).where(User.organization_id == futran_org_id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name))
    return [u for u in users if {r.role for r in roles_of(db, u.id)} & {"sales_team", "chief_auditor"}]


def _check_owner(db: Session, actor: Actor, owner_id: str | None) -> None:
    if owner_id and owner_id not in {u.id for u in _owners(db, actor.organization.id)}:
        raise Invalid(errors=[{"field": "owner_id", "message": "Choose someone on the Sales Team or a Chief Auditor."}])


def _kpis(db: Session) -> dict:
    rows = list(db.scalars(select(Opportunity)))
    now = utcnow()
    q_start_month = 3 * ((now.month - 1) // 3) + 1
    open_ = [o for o in rows if o.stage not in ("won", "lost")]
    return {
        "open": len(open_),
        "created_by_triggers_this_month": sum(o.trigger != "manual" and o.created_at.year == now.year and o.created_at.month == now.month for o in rows),
        "waiting_approval": sum(o.needs_ca_approval and o.ca_decision is None for o in open_),
        "pipeline_value": sum(o.value or 0 for o in open_),
        "won_this_quarter": sum(o.stage == "won" and o.closed_at is not None and o.closed_at.year == now.year and o.closed_at.month >= q_start_month for o in rows),
    }


@router.get("/opportunities")
def list_opps(trigger: str | None = None, stage: str | None = None, owner: str | None = None, q: str | None = None,
              actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_OPPORTUNITIES)
    stmt = select(Opportunity)
    if trigger:
        stmt = stmt.where(Opportunity.trigger.in_(trigger.split(",")))
    if stage:
        stmt = stmt.where(Opportunity.stage.in_(stage.split(",")))
    if owner == "me":
        stmt = stmt.where(Opportunity.owner_id == actor.id)
    items = [opp_out(db, o) for o in db.scalars(stmt.order_by(Opportunity.created_at.desc()))]
    if q:
        needle = q.casefold()
        items = [i for i in items if needle in f"{i['client_name']} {i['service']} {i['why_now'] or ''}".casefold()]
    clients = [{"id": o.id, "name": o.name} for o in db.scalars(select(Organization).where(Organization.type == "client", Organization.deleted_at.is_(None)).order_by(Organization.name))]
    return {
        "items": items, "kpis": _kpis(db), "owners": [{"id": u.id, "name": u.name} for u in _owners(db, actor.organization.id)], "clients": clients,
        "triggers": [{"value": k, "label": v} for k, v in TRIGGER_LABELS.items()], "stages": [{"value": k, "label": v} for k, v in STAGE_LABELS.items()],
        "can_approve": Action.APPROVE_OPPORTUNITY in _actions(db, actor),
    }


def _actions(db: Session, actor: Actor) -> set[Action]:
    out = set()
    for a in (Action.APPROVE_OPPORTUNITY, Action.WORK_OPPORTUNITIES):
        try:
            authorize(db, actor, a)
            out.add(a)
        except Exception:
            pass
    return out


@router.get("/opportunities/export.csv")
def export(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_OPPORTUNITIES)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Client", "Trigger", "Service", "Why now", "Value (USD)", "Owner", "Stage", "Next step", "Chief Auditor approval"])
    for o in db.scalars(select(Opportunity).order_by(Opportunity.created_at.desc())):
        x = opp_out(db, o)
        w.writerow([x["client_name"], x["trigger_label"], x["service"], x["why_now"] or "", x["value"] or "", x["owner_name"] or "", x["stage_label"], x["next_step"] or "", x["approval"]])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="opportunities.csv"'})


class OppIn(BaseModel):
    organization_id: str
    service: str = Field(min_length=2, max_length=200)
    service_kind: str = "other"
    why_now: str = Field(default="", max_length=300)
    value: int | None = Field(default=None, ge=0)
    owner_id: str | None = None
    next_step: str | None = Field(default=None, max_length=300)

    @field_validator("service_kind")
    @classmethod
    def _kind(cls, v):
        if v not in SERVICE_KINDS:
            raise ValueError("Unknown service type.")
        return v


@router.post("/opportunities")
def create_opp(body: OppIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    org = db.get(Organization, body.organization_id)
    if org is None or org.type != "client":
        raise Invalid(errors=[{"field": "organization_id", "message": "Choose a client."}])
    owner = body.owner_id or actor.id
    _check_owner(db, actor, owner)
    check_independence(db, org.id, body.service_kind)
    o = Opportunity(organization_id=org.id, trigger="manual", service=body.service, service_kind=body.service_kind, why_now=body.why_now, value=body.value,
                    owner_id=owner, next_step=body.next_step, needs_ca_approval=is_current_audit_client(db, org.id), created_by=actor.id)
    db.add(o)
    db.flush()
    audit.record(db, actor_id=actor.id, action="opportunity.create", obj=o, after=column_snapshot(o), request=request, organization_id=actor.organization.id, summary=f"Opportunity for {org.name}: {o.service}")
    return opp_out(db, o)


@router.get("/opportunities/{opp_id}")
def get_opp(opp_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_OPPORTUNITIES)
    o = _get(db, opp_id)
    acts = db.scalars(select(OpportunityActivity).where(OpportunityActivity.opportunity_id == o.id).order_by(OpportunityActivity.at.desc()))
    return opp_out(db, o) | {"activities": [{"id": a.id, "kind": a.kind, "summary": a.summary, "by": _name(db, a.by_id), "at": a.at.isoformat()} for a in acts]}


class OppPatch(BaseModel):
    stage: str | None = None
    owner_id: str | None = None
    next_step: str | None = Field(default=None, max_length=300)
    value: int | None = Field(default=None, ge=0)
    service: str | None = Field(default=None, min_length=2, max_length=200)

    @field_validator("stage")
    @classmethod
    def _stage(cls, v):
        if v is not None and v not in STAGES:
            raise ValueError("Unknown stage.")
        return v


def _patch(db: Session, actor: Actor, o: Opportunity, body: OppPatch) -> None:
    data = body.model_dump(exclude_unset=True)
    if "owner_id" in data:
        _check_owner(db, actor, data["owner_id"])
    if "stage" in data and data["stage"] != o.stage:
        if data["stage"] == "proposal" and not can_send_offer(o):
            raise Conflict("This client is a current audit client. The Chief Auditor approves the offer before a proposal goes out.")
        log(db, o, "stage", f"Stage changed from {STAGE_LABELS[o.stage]} to {STAGE_LABELS[data['stage']]}", actor.id)
        o.closed_at = utcnow() if data["stage"] in ("won", "lost") else None
    for k, v in data.items():
        setattr(o, k, v)


@router.patch("/opportunities/{opp_id}")
def patch_opp(opp_id: str, body: OppPatch, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    before = column_snapshot(o)
    _patch(db, actor, o, body)
    db.flush()
    audit.record(db, actor_id=actor.id, action="opportunity.update", obj=o, before=before, after=column_snapshot(o), request=request, organization_id=actor.organization.id, summary=f"Updated opportunity: {o.service}")
    return opp_out(db, o)


class BulkIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    owner_id: str | None = None
    stage: str | None = None


@router.post("/opportunities/bulk")
def bulk(body: BulkIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    patch = OppPatch(**{k: v for k, v in {"owner_id": body.owner_id, "stage": body.stage}.items() if v is not None})
    n = 0
    for oid in body.ids:
        o = db.get(Opportunity, oid)
        if o is None:
            continue
        _patch(db, actor, o, patch)
        n += 1
    audit.record(db, actor_id=actor.id, action="opportunity.bulk_update", object_type="Opportunity", request=request, organization_id=actor.organization.id, summary=f"Updated {n} opportunities")
    return {"changed": n}


class ActivityIn(BaseModel):
    kind: str
    summary: str = Field(min_length=2, max_length=4000)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in ACTIVITY_KINDS:
            raise ValueError("Choose call, email, meeting, note, proposal or outcome.")
        return v


@router.post("/opportunities/{opp_id}/activities")
def add_activity(opp_id: str, body: ActivityIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    if body.kind == "proposal" and not can_send_offer(o):
        raise Conflict("This client is a current audit client. The Chief Auditor approves the offer before a proposal goes out.")
    a = log(db, o, body.kind, body.summary, actor.id)
    if o.stage == "new" and body.kind in ("call", "email", "meeting"):
        o.stage = "contacted"
    return {"id": a.id}


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/opportunities/{opp_id}/request-approval")
def request_approval(opp_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    if not o.needs_ca_approval:
        raise Conflict("This client is not a current audit client; no approval is needed.")
    o.approval_requested_at = utcnow()
    org = db.get(Organization, o.organization_id)
    log(db, o, "approval_requested", body.note or "Approval requested", actor.id)
    chiefs = [u for u in db.scalars(select(User).where(User.organization_id == actor.organization.id, User.deleted_at.is_(None))) if "chief_auditor" in {r.role for r in roles_of(db, u.id)}]
    notify(db, chiefs, "opportunity_approval", f"Approve an offer to {org.name}", f"{actor.user.name} asks to offer “{o.service}”. {body.note}".strip(), link=f"/opportunities?open={o.id}")
    return opp_out(db, o)


class DecisionIn(BaseModel):
    decision: str
    note: str = Field(default="", max_length=2000)

    @field_validator("decision")
    @classmethod
    def _d(cls, v):
        if v not in ("approve", "decline"):
            raise ValueError("Approve or decline.")
        return v


@router.post("/opportunities/{opp_id}/approve")
def decide(opp_id: str, body: DecisionIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.APPROVE_OPPORTUNITY)
    o = _get(db, opp_id)
    check_independence(db, o.organization_id, o.service_kind)  # approval never overrides the independence rule
    o.ca_decision = "approved" if body.decision == "approve" else "declined"
    o.ca_approved_by, o.ca_approved_at, o.ca_note = actor.id, utcnow(), body.note or None
    log(db, o, "approved" if body.decision == "approve" else "declined", body.note or ("Offer approved" if body.decision == "approve" else "Offer declined"), actor.id)
    audit.record(db, actor_id=actor.id, action=f"opportunity.{o.ca_decision}", obj=o, request=request, organization_id=actor.organization.id, summary=f"Offer {o.ca_decision}: {o.service}")
    if o.owner_id and o.owner_id != actor.id:
        notify(db, [db.get(User, o.owner_id)], "opportunity_decided", f"Offer {o.ca_decision}: {o.service}", body.note or None, link=f"/opportunities?open={o.id}")
    return opp_out(db, o)


class ProposalIn(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)


@router.post("/opportunities/{opp_id}/send-proposal")
def send_proposal(opp_id: str, body: ProposalIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    if not can_send_offer(o):
        raise Conflict("This client is a current audit client. The Chief Auditor approves the offer before it is sent.")
    check_independence(db, o.organization_id, o.service_kind)
    log(db, o, "proposal", body.summary, actor.id)
    if o.stage in ("new", "contacted"):
        o.stage = "proposal"
    audit.record(db, actor_id=actor.id, action="opportunity.proposal", obj=o, request=request, organization_id=actor.organization.id, summary=f"Proposal logged: {o.service}")
    return opp_out(db, o)
