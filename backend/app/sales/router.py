"""S1 opportunities (spec §27.5) and the Release 2 sales desk (spec §4.1-4.3, SM-01 to SM-04). Sales Officers, Sales
Managers and the Chief Auditor; only the Chief Auditor approves offers to audit clients."""
import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.clock import today, utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.models import column_snapshot
from app.litigation.service import TYPE_LABELS
from app.notifications.service import notify
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.auth.deps import get_settings_dep
from app.sales import desk, independence
from app.sales.models import (ACTIVITY_KINDS, CONTACT_ROLES, INDUSTRIES, LOST_REASONS, OPEN_STAGES, PRODUCTS, SEGMENTS, SERVICE_KINDS, SIZE_BANDS, SOURCES, STAGE_LABELS,
                              STAGES, TRIGGER_EVENTS, TRIGGER_LABELS, Opportunity, OpportunityActivity, OpportunityContact)
from app.sales.prospects import create_prospect, domain_of, find_duplicates, kind_of
from app.sales.service import can_send_offer, check_independence, is_current_audit_client, log
from app.tenancy.models import Organization, User
from app.tenancy.service import roles_of

router = APIRouter(tags=["opportunities"])



def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def _company(org: Organization | None) -> dict:
    if org is None:
        return {"id": None, "name": "", "kind": "client"}
    return {"id": org.id, "name": org.name, "kind": kind_of(org), "website": org.website, "industry": org.industry, "size_band": org.employee_band,
            "hq": ", ".join(x for x in (org.hq_city, org.hq_state, org.hq_country) if x)}


def _iso(v) -> str | None:
    return v.isoformat() if v is not None else None


def flag_of(db: Session, o: Opportunity) -> tuple[bool, str | None]:
    """The stored independence flag, or for a row saved before Release 2 (flag never stored) the flag computed now.
    Reading never writes."""
    if o.independence_flag is not None:
        return bool(o.independence_flag), o.independence_reason
    flag, why = independence.flag_for(db, o.organization_id)
    return flag, why or None


def needs_approval(db: Session, o: Opportunity) -> bool:
    """Chief Auditor approval (spec §4.7): a current audit client, or a logged opportunity whose company is flagged."""
    return is_current_audit_client(db, o.organization_id) or (o.trigger == "manual" and flag_of(db, o)[0])


def opp_out(db: Session, o: Opportunity, touches: dict | None = None) -> dict:
    org = db.get(Organization, o.organization_id)
    if touches is None:
        touches = desk.last_touches(db, [o.id])
    flag, flag_reason = flag_of(db, o)
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
        # Release 2 (spec §4.11)
        "name": o.name or o.service, "company": _company(org), "is_automatic": o.trigger != "manual", "source": o.source,
        "source_label": SOURCES.get(o.source or "", "Automatic trigger" if o.trigger != "manual" else None), "partner_id": o.partner_id, "partner_name": _partner_name(db, o.partner_id), "segment": o.segment,
        "segment_label": SEGMENTS.get(o.segment or ""), "trigger_event": o.trigger_event, "trigger_event_label": TRIGGER_EVENTS.get(o.trigger_event or ""),
        "products_of_interest": list(o.products_of_interest or []), "products_labels": [PRODUCTS.get(p, p) for p in o.products_of_interest or []],
        "est_value": o.value, "close_date": _iso(o.close_date), "next_step_due": _iso(o.next_step_due), "lost_reason": o.lost_reason,
        "lost_reason_label": LOST_REASONS.get(o.lost_reason or ""), "lost_note": o.lost_note, "bant": o.bant or {}, "competitors": list(o.competitors or []),
        "independence_flag": flag, "independence_reason": flag_reason, "last_activity_at": _iso(desk.last_touch(o, touches)),
        "stale": desk.is_stale(o, touches),
    }


def _get(db: Session, oid: str) -> Opportunity:
    o = db.get(Opportunity, oid)
    if o is None:
        raise NotFound()
    return o


OWNER_ROLES = ("sales_team", "sales_manager", "chief_auditor")  # who can own an opportunity


def _can(db: Session, actor: Actor, action: Action) -> bool:
    try:
        authorize(db, actor, action)
        return True
    except Exception:
        return False


def _check_reassign(db: Session, actor: Actor, o: Opportunity, owner_id: str | None) -> None:
    """Spec §4.1: the Sales Manager reassigns opportunities. A Sales Officer may take an unowned opportunity, or keep
    their own, but not move someone else's or hand one to another rep."""
    if owner_id == o.owner_id or _can(db, actor, Action.REASSIGN_OPPORTUNITIES):
        return
    if owner_id == actor.id and o.owner_id is None:
        return
    raise Forbidden("Only a Sales Manager or the Chief Auditor reassigns an opportunity to someone else.")


def _can_edit(db: Session, actor: Actor, o: Opportunity) -> bool:
    """Only the owner, or a Sales Manager or the Chief Auditor (reassign_opportunities), works an opportunity someone else
    owns; an unowned one can be worked and taken by anyone who works opportunities."""
    return o.owner_id in (None, actor.id) or _can(db, actor, Action.REASSIGN_OPPORTUNITIES)


def _check_edit(db: Session, actor: Actor, o: Opportunity) -> None:
    if not _can_edit(db, actor, o):
        raise Forbidden("This opportunity belongs to another rep. Only its owner or a Sales Manager can change it.")


def _owners(db: Session, futran_org_id: str) -> list[User]:
    users = db.scalars(select(User).where(User.organization_id == futran_org_id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name))
    return [u for u in users if {r.role for r in roles_of(db, u.id)} & set(OWNER_ROLES)]


def _check_owner(db: Session, actor: Actor, owner_id: str | None) -> None:
    if owner_id and owner_id not in {u.id for u in _owners(db, actor.organization.id)}:
        raise Invalid(errors=[{"field": "owner_id", "message": "Choose a Sales Officer, a Sales Manager or a Chief Auditor."}])


def _kpis(db: Session) -> dict:
    rows = _visible(db, db.scalars(select(Opportunity)))
    now = utcnow()
    q_start_month = 3 * ((now.month - 1) // 3) + 1
    open_ = [o for o in rows if o.stage in OPEN_STAGES]
    return {
        "open": len(open_),
        "created_by_triggers_this_month": sum(o.trigger != "manual" and o.created_at.year == now.year and o.created_at.month == now.month for o in rows),
        "waiting_approval": sum(o.needs_ca_approval and o.ca_decision is None for o in open_),
        "pipeline_value": sum(o.value or 0 for o in open_),
        "won_this_quarter": sum(o.stage == "won" and o.closed_at is not None and o.closed_at.year == now.year and o.closed_at.month >= q_start_month for o in rows),
    }


PRODUCT_FAMILIES = {"audit": ("audit",), "monitor": ("monitor",), "ll144": ("ll144",), "agent_assure": ("agent_assure",), "agentwarden": ("agentwarden",)}


def _visible(db: Session, rows) -> list[Opportunity]:
    """Opportunities whose company still exists (a lost prospect deleted after 24 months takes its opportunities)."""
    out = []
    for o in rows:
        org = db.get(Organization, o.organization_id)
        if org is not None and org.deleted_at is None:
            out.append(o)
    return out


@router.get("/opportunities")
def list_opps(trigger: str | None = None, stage: str | None = None, owner: str | None = None, q: str | None = None, source: str | None = None,
              product: str | None = None, flag: bool = False, stale: bool = False, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_OPPORTUNITIES)
    stmt = select(Opportunity)
    if trigger:
        stmt = stmt.where(Opportunity.trigger.in_(trigger.split(",")))
    if stage == "open":
        stmt = stmt.where(Opportunity.stage.in_(OPEN_STAGES))
    elif stage:
        stmt = stmt.where(Opportunity.stage.in_(stage.split(",")))
    if owner == "me":
        stmt = stmt.where(Opportunity.owner_id == actor.id)
    elif owner and owner not in ("team", "anyone"):
        stmt = stmt.where(Opportunity.owner_id == owner)
    if source == "manual":
        stmt = stmt.where(Opportunity.trigger == "manual")
    elif source == "auto":
        stmt = stmt.where(Opportunity.trigger != "manual")
    elif source == "partner":
        stmt = stmt.where((Opportunity.source == "referral_partner") | Opportunity.partner_id.is_not(None))
    elif source:
        stmt = stmt.where(Opportunity.source == source)
    rows = _visible(db, db.scalars(stmt.order_by(Opportunity.created_at.desc())))
    if product:
        rows = [o for o in rows if product in (o.products_of_interest or []) or (product == "other" and not set(o.products_of_interest or []) & set(PRODUCT_FAMILIES))]
    touches = desk.last_touches(db, [o.id for o in rows])
    items = [opp_out(db, o, touches) for o in rows]
    if stale:
        items = [i for i in items if i["stale"]]
    if flag:
        items = [i for i in items if i["independence_flag"]]
    by_id = {o.id: o for o in rows}
    for i in items:
        i["can_edit"] = _can_edit(db, actor, by_id[i["id"]])
    if q:
        needle = q.casefold()
        items = [i for i in items if needle in f"{i['client_name']} {i['service']} {i['name']} {i['why_now'] or ''}".casefold()]
    clients = [{"id": o.id, "name": o.name} for o in db.scalars(select(Organization).where(Organization.type == "client", Organization.deleted_at.is_(None)).order_by(Organization.name))]
    opts = lambda d: [{"value": k, "label": v} for k, v in d.items()]  # noqa: E731
    return {
        "items": items, "kpis": _kpis(db), "owners": [{"id": u.id, "name": u.name} for u in _owners(db, actor.organization.id)], "clients": clients,
        "triggers": opts(TRIGGER_LABELS), "stages": [{"value": k, "label": v} for k, v in STAGE_LABELS.items() if k != "contacted"],
        "sources": opts(SOURCES), "segments": opts(SEGMENTS), "trigger_events": opts(TRIGGER_EVENTS), "products": opts(PRODUCTS), "lost_reasons": opts(LOST_REASONS),
        "contact_roles": opts(CONTACT_ROLES), "industries": list(INDUSTRIES), "size_bands": list(SIZE_BANDS),
        "partners": [{"id": p.id, "name": p.name, "type": p.type} for p in _partners(db)],
        "can_approve": Action.APPROVE_OPPORTUNITY in _actions(db, actor), "can_work": _can(db, actor, Action.WORK_OPPORTUNITIES),
        "can_reassign": _can(db, actor, Action.REASSIGN_OPPORTUNITIES),
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
def export(ids: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.documents.csvsafe import safe_cell

    authorize(db, actor, Action.VIEW_OPPORTUNITIES)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Company", "Prospect or client", "Opportunity", "Source", "Trigger", "Products", "Value (USD)", "Close date", "Owner", "Stage", "Next step", "Next step due",
                "Independence flag", "Chief Auditor approval", "Why now"])
    stmt = select(Opportunity).order_by(Opportunity.created_at.desc())
    if ids:
        stmt = stmt.where(Opportunity.id.in_(ids.split(",")))
    rows = _visible(db, db.scalars(stmt))
    touches = desk.last_touches(db, [o.id for o in rows])
    for o in rows:
        x = opp_out(db, o, touches)
        w.writerow([safe_cell(v) for v in (x["client_name"], x["company"]["kind"].capitalize(), x["name"], x["source_label"] or "", x["trigger_label"], ", ".join(x["products_labels"]),
                                            x["value"] or "", x["close_date"] or "", x["owner_name"] or "", x["stage_label"], x["next_step"] or "", x["next_step_due"] or "",
                                            "Yes" if x["independence_flag"] else "No", x["approval"], x["why_now"] or "")])
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
def create_opp(body: OppIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    org = db.get(Organization, body.organization_id)
    if org is None or org.type != "client":
        raise Invalid(errors=[{"field": "organization_id", "message": "Choose a client."}])
    owner = body.owner_id or actor.id
    _check_owner(db, actor, owner)
    check_independence(db, org.id, body.service_kind)
    o = Opportunity(organization_id=org.id, trigger="manual", service=body.service, service_kind=body.service_kind, why_now=body.why_now, value=body.value,
                    owner_id=owner, next_step=body.next_step, needs_ca_approval=is_current_audit_client(db, org.id), created_by=actor.id, last_activity_at=utcnow())
    independence.refresh(db, o)
    o.needs_ca_approval = o.needs_ca_approval or bool(o.independence_flag)
    db.add(o)
    db.flush()
    audit.record(db, actor_id=actor.id, action="opportunity.create", obj=o, after=column_snapshot(o), request=request, organization_id=actor.organization.id, summary=f"Opportunity for {org.name}: {o.service}")
    return opp_out(db, o)


@router.get("/opportunities/{opp_id}")
def get_opp(opp_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_OPPORTUNITIES)
    o = _get(db, opp_id)
    acts = list(db.scalars(select(OpportunityActivity).where(OpportunityActivity.opportunity_id == o.id).order_by(OpportunityActivity.at.desc())))
    replies = desk.replies_for(db, [a.mail_thread_id for a in acts if a.mail_thread_id])
    contacts = db.scalars(select(OpportunityContact).where(OpportunityContact.opportunity_id == o.id, OpportunityContact.deleted_at.is_(None)).order_by(OpportunityContact.created_at))
    return opp_out(db, o) | {
        "activities": [{"id": a.id, "kind": a.kind, "summary": a.summary, "by": _name(db, a.by_id), "at": a.at.isoformat(), "outcome": a.outcome, "next_step": a.next_step,
                        "due_on": _iso(a.due_on), "done_at": _iso(a.done_at), "to": a.to_addresses or [], "replies": replies.get(a.mail_thread_id or "", [])} for a in acts],
        "contacts": [_contact_out(c) for c in contacts], "linked": desk.linked(db, o),
        "can_work": _can(db, actor, Action.WORK_OPPORTUNITIES) and _can_edit(db, actor, o), "can_reassign": _can(db, actor, Action.REASSIGN_OPPORTUNITIES),
        "can_approve": _can(db, actor, Action.APPROVE_OPPORTUNITY), "owners": [{"id": u.id, "name": u.name} for u in _owners(db, actor.organization.id)],
    }


def _partners(db: Session) -> list:
    """Active G-11 partners (R7), for the partner picker; empty in a build without partners."""
    try:
        from app.partners.models import Partner
    except ImportError:
        return []
    return list(db.scalars(select(Partner).where(Partner.status == "active", Partner.deleted_at.is_(None)).order_by(Partner.name)))


def _check_partner(db: Session, partner_id: str | None) -> None:
    if partner_id and partner_id not in {p.id for p in _partners(db)}:
        raise Invalid(errors=[{"field": "partner_id", "message": "Choose an active partner."}])


def _partner_name(db: Session, partner_id: str | None) -> str | None:
    if not partner_id:
        return None
    try:
        from app.partners.models import Partner
    except ImportError:
        return None
    p = db.get(Partner, partner_id)
    return p.name if p else None


def _contact_out(c: OpportunityContact) -> dict:
    return {"id": c.id, "name": c.name, "title": c.title, "email": c.email, "phone": c.phone, "contact_role": c.contact_role,
            "contact_role_label": CONTACT_ROLES.get(c.contact_role or "")}


def _one_of(choices: dict | tuple, message: str):
    def check(v):
        if v is not None and v != "" and v not in choices:
            raise ValueError(message)
        return v or None
    return check


class Bant(BaseModel):
    budget: str | None = Field(default=None, max_length=300)
    authority: str | None = Field(default=None, max_length=300)
    need: str | None = Field(default=None, max_length=600)
    timeline: str | None = Field(default=None, max_length=300)


class DealFields(BaseModel):
    """Spec §4.3 deal fields shared by Log opportunity (SM-03) and the record (SM-04)."""
    name: str | None = Field(default=None, max_length=200)
    source: str | None = None
    partner_id: str | None = Field(default=None, max_length=36)
    segment: str | None = None
    trigger_event: str | None = None
    products_of_interest: list[str] | None = Field(default=None, max_length=12)
    est_value: int | None = Field(default=None, ge=0, le=100_000_000)
    close_date: date | None = None
    next_step: str | None = Field(default=None, max_length=300)
    next_step_due: date | None = None
    bant: Bant | None = None
    competitors: list[str] | None = Field(default=None, max_length=12)

    _source = field_validator("source")(classmethod(lambda cls, v: _one_of(SOURCES, "Choose a source from the list.")(v)))
    _segment = field_validator("segment")(classmethod(lambda cls, v: _one_of(SEGMENTS, "Choose a segment from the list.")(v)))
    _trigger_event = field_validator("trigger_event")(classmethod(lambda cls, v: _one_of(TRIGGER_EVENTS, "Choose a trigger from the list.")(v)))

    @field_validator("products_of_interest")
    @classmethod
    def _products(cls, v):
        if v is not None and any(p not in PRODUCTS for p in v):
            raise ValueError("Choose products from the list.")
        return list(dict.fromkeys(v)) if v is not None else None

    @field_validator("competitors")
    @classmethod
    def _competitors(cls, v):
        return [c.strip()[:120] for c in v if c and c.strip()] if v is not None else None


class OppPatch(DealFields):
    stage: str | None = None
    owner_id: str | None = None
    value: int | None = Field(default=None, ge=0)
    service: str | None = Field(default=None, min_length=2, max_length=200)
    lost_reason: str | None = None
    lost_note: str | None = Field(default=None, max_length=500)

    @field_validator("stage")
    @classmethod
    def _stage(cls, v):
        if v is not None and v not in STAGES:
            raise ValueError("Unknown stage.")
        return v

    _lost = field_validator("lost_reason")(classmethod(lambda cls, v: _one_of(LOST_REASONS, "Choose a reason from the list.")(v)))


BANT_GATE = (("budget", "budget"), ("authority", "decision maker"), ("timeline", "timeline"))


def _stage_gate(o: Opportunity, new: str, data: dict) -> None:
    """Spec §4.2: qualified once the rep confirms budget, decision maker and timeline; lost with a reason."""
    if new == "qualified":
        bant = data.get("bant") or o.bant or {}
        missing = [label for k, label in BANT_GATE if not (bant.get(k) or "").strip()]
        if missing:
            raise Invalid(errors=[{"field": "bant", "message": f"Before Qualified, record the {', '.join(missing)} (BANT)."}])
    if new == "lost" and not (data.get("lost_reason") or o.lost_reason):
        raise Invalid(errors=[{"field": "lost_reason", "message": "Choose why it was lost."}])


OFFER_STAGES = ("proposal", "won")  # an offer has gone out: a current audit client needs the Chief Auditor's approval first


def _patch(db: Session, actor: Actor, o: Opportunity, body: OppPatch, settings=None) -> None:
    _check_edit(db, actor, o)
    data = body.model_dump(exclude_unset=True)
    independence.refresh(db, o)  # the flag first: it decides whether an offer needs the Chief Auditor (§4.7)
    if "est_value" in data:
        data["value"] = data.pop("est_value")
    if data.get("partner_id"):
        _check_partner(db, data["partner_id"])
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip() or None
    if data.get("stage") and data["stage"] != o.stage:
        _stage_gate(o, data["stage"], data)
    new_owner = data.get("owner_id") if "owner_id" in data and data.get("owner_id") != o.owner_id else None
    if "owner_id" in data:
        _check_owner(db, actor, data["owner_id"])
        _check_reassign(db, actor, o, data["owner_id"])
    if "service" in data and data["service"] is not None and data["service"].strip() != o.service:
        # The approval was for the service as it stood: a new service is a new offer. Re-check the independence rule and
        # whether the client is now a current audit client, and ask for approval again.
        check_independence(db, o.organization_id, o.service_kind)
        o.needs_ca_approval = needs_approval(db, o)
        if o.ca_decision is not None or o.approval_requested_at is not None:
            o.ca_decision, o.ca_approved_by, o.ca_approved_at, o.ca_note, o.approval_requested_at = None, None, None, None, None
            log(db, o, "approval_reset", f"Service changed from “{o.service}”; the Chief Auditor's approval no longer applies", actor.id)
        data["service"] = data["service"].strip()
    if "stage" in data and data["stage"] != o.stage:
        if data["stage"] in OFFER_STAGES:
            o.needs_ca_approval = o.needs_ca_approval or needs_approval(db, o)
            if not can_send_offer(o):
                raise Conflict("This client is a current audit client. The Chief Auditor approves the offer before a proposal goes out or the opportunity is won.")
        log(db, o, "stage", f"Stage changed from {STAGE_LABELS.get(o.stage, o.stage)} to {STAGE_LABELS[data['stage']]}", actor.id)
        o.closed_at = utcnow() if data["stage"] in ("won", "lost") else None
        if data["stage"] != "lost":
            o.lost_reason = o.lost_reason if "lost_reason" in data else None
    for k, v in data.items():
        setattr(o, k, v)
    independence.refresh(db, o)  # computed on every save (§4.3 rule 3)
    if o.trigger == "manual" and o.independence_flag:
        o.needs_ca_approval = True  # never cleared by a later save; an approval already given stands
    if new_owner and new_owner != actor.id:
        u = db.get(User, new_owner)
        org = db.get(Organization, o.organization_id)
        notify(db, [u], "opportunity_assigned", f"Opportunity assigned to you: {org.name if org else ''}", o.name or o.service, f"/sales/opportunities/{o.id}",
               settings=settings, email_template="notification" if settings is not None else None)


@router.patch("/opportunities/{opp_id}")
def patch_opp(opp_id: str, body: OppPatch, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"),
              settings=Depends(get_settings_dep)):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    before = column_snapshot(o)
    _patch(db, actor, o, body, settings)
    db.flush()
    audit.record(db, actor_id=actor.id, action="opportunity.update", obj=o, before=before, after=column_snapshot(o), request=request, organization_id=actor.organization.id, summary=f"Updated opportunity: {o.service}")
    return opp_out(db, o)


class BulkIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    owner_id: str | None = None
    stage: str | None = None


@router.post("/opportunities/bulk")
def bulk(body: BulkIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    patch = OppPatch(**{k: v for k, v in {"owner_id": body.owner_id, "stage": body.stage}.items() if v is not None})
    n = skipped = 0
    for oid in body.ids:
        o = db.get(Opportunity, oid)
        if o is None:
            continue
        try:
            with db.begin_nested():
                _patch(db, actor, o, patch, settings)
        except (Conflict, Forbidden, Invalid):  # waiting for the Chief Auditor's approval, or not this rep's to reassign: left as it is
            skipped += 1
            continue
        n += 1
    audit.record(db, actor_id=actor.id, action="opportunity.bulk_update", object_type="Opportunity", request=request, organization_id=actor.organization.id,
                 summary=f"Updated {n} opportunities" + (f"; {skipped} left as they were" if skipped else ""))
    return {"changed": n, "skipped": skipped}


class ActivityIn(BaseModel):
    kind: str
    summary: str = Field(min_length=2, max_length=4000)
    outcome: str | None = Field(default=None, max_length=500)
    next_step: str | None = Field(default=None, max_length=300)
    next_step_due: date | None = None
    due_on: date | None = None  # a task's due date
    on: date | None = None  # when it happened, if not now

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in ACTIVITY_KINDS:
            raise ValueError("Choose call, email, meeting, note, task, proposal or outcome.")
        return v


@router.post("/opportunities/{opp_id}/activities")
def add_activity(opp_id: str, body: ActivityIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    _check_edit(db, actor, o)
    if body.kind == "proposal" and not can_send_offer(o):
        raise Conflict("This client is a current audit client. The Chief Auditor approves the offer before a proposal goes out.")
    at = datetime.combine(body.on, utcnow().time()) if body.on and body.on < today() else None
    a = log(db, o, body.kind, body.summary, actor.id, at=at)
    a.outcome, a.next_step, a.due_on = body.outcome, body.next_step, body.due_on if body.kind == "task" else None
    if body.next_step:
        o.next_step, o.next_step_due = body.next_step, body.next_step_due
    desk.touch(o, a.at)
    db.flush()
    return {"id": a.id}


@router.post("/opportunities/{opp_id}/activities/{activity_id}/done")
def task_done(opp_id: str, activity_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    _check_edit(db, actor, o)
    a = db.get(OpportunityActivity, activity_id)
    if a is None or a.opportunity_id != o.id or a.kind != "task":
        raise NotFound()
    a.done_at = None if a.done_at else utcnow()
    desk.touch(o)
    return {"id": a.id, "done_at": _iso(a.done_at)}


class EmailIn(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=250)
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("to")
    @classmethod
    def _to(cls, v):
        out = [x.strip() for x in v if x and x.strip()]
        if not out or any("@" not in x or " " in x for x in out):
            raise ValueError("Enter email addresses.")
        return out


@router.post("/opportunities/{opp_id}/email")
def send_email(opp_id: str, body: EmailIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"),
               settings=Depends(get_settings_dep)):
    """Spec §4.3 rule 4: from the rep's own mailbox; replies thread back onto the opportunity."""
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    _check_edit(db, actor, o)
    a = desk.send_email(db, settings, actor.user, o, body.to, body.subject, body.body)
    audit.record(db, actor_id=actor.id, action="opportunity.email", obj=o, request=request, organization_id=actor.organization.id,
                 summary=f"Email sent from {actor.user.name}'s mailbox to {len(body.to)} {'recipient' if len(body.to) == 1 else 'recipients'}")  # append-only: no addresses
    return {"id": a.id}


# ---- contacts (spec §4.11 OpportunityContact)
class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    title: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    contact_role: str | None = None

    _role = field_validator("contact_role")(classmethod(lambda cls, v: _one_of(CONTACT_ROLES, "Choose economic buyer, champion, technical, legal or procurement.")(v)))

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        v = (v or "").strip().lower()
        if v and ("@" not in v or " " in v):
            raise ValueError("Enter an email address.")
        return v or None


class ContactPatch(ContactIn):
    name: str | None = Field(default=None, min_length=1, max_length=160)


def _contact(db: Session, o: Opportunity, cid: str) -> OpportunityContact:
    c = db.get(OpportunityContact, cid)
    if c is None or c.opportunity_id != o.id or c.deleted_at is not None:
        raise NotFound()
    return c


@router.post("/opportunities/{opp_id}/contacts")
def add_contact(opp_id: str, body: ContactIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    _check_edit(db, actor, o)
    c = OpportunityContact(opportunity_id=o.id, created_by=actor.id, **body.model_dump())
    db.add(c)
    db.flush()
    return _contact_out(c)


@router.patch("/opportunities/{opp_id}/contacts/{contact_id}")
def edit_contact(opp_id: str, contact_id: str, body: ContactPatch, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    _check_edit(db, actor, o)
    c = _contact(db, o, contact_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k != "name" or v:
            setattr(c, k, v)
    db.flush()
    return _contact_out(c)


@router.delete("/opportunities/{opp_id}/contacts/{contact_id}")
def remove_contact(opp_id: str, contact_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    _check_edit(db, actor, o)
    c = _contact(db, o, contact_id)
    c.deleted_at = utcnow()
    return {"id": c.id}


# ---- SM-03 log opportunity: an existing client or prospect, or a new prospect with the duplicate check
@router.get("/sales/duplicates")
def duplicates(name: str | None = None, website: str | None = None, email: str | None = None, actor: Actor = Depends(current_actor),
               db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    return {"matches": find_duplicates(db, name=name, website=website, emails=[e for e in (email or "").split(",") if e])}


@router.get("/sales/independence")
def independence_preview(organization_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """SM-03: the independence check shown before saving (the same check runs again on save)."""
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    org = db.get(Organization, organization_id)
    if org is None or org.type not in ("client", "prospect"):
        raise NotFound()
    flag, reason = independence.flag_for(db, org.id)
    return {"flag": flag, "reason": reason}


@router.get("/sales/companies")
def companies(q: str = "", actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """SM-03 company search: existing clients and prospects."""
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    needle = q.strip().casefold()
    rows = db.scalars(select(Organization).where(Organization.type.in_(("client", "prospect")), Organization.deleted_at.is_(None), Organization.is_internal.is_(False))
                      .order_by(Organization.name))
    out = [{"id": o.id, "name": o.name, "kind": kind_of(o), "website": o.website, "domain": domain_of(o.website)} for o in rows
           if not needle or needle in f"{o.name} {o.website or ''}".casefold()]
    return {"items": out[:25]}


class ProspectIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=80)
    size_band: str | None = Field(default=None, max_length=40)
    hq_state: str | None = Field(default=None, max_length=120)
    hq_country: str | None = Field(default=None, max_length=2)


class LogIn(DealFields):
    organization_id: str | None = None
    prospect: ProspectIn | None = None
    confirm_different: bool = False
    owner_id: str | None = None
    contacts: list[ContactIn] = Field(default_factory=list, max_length=20)


@router.post("/sales/opportunities")
def log_opportunity(body: LogIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"),
                    settings=Depends(get_settings_dep)):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    if (body.organization_id is None) == (body.prospect is None):
        raise Invalid(errors=[{"field": "organization_id", "message": "Choose an existing company or enter a new prospect."}])
    if body.organization_id:
        org = db.get(Organization, body.organization_id)
        if org is None or org.deleted_at is not None or org.type not in ("client", "prospect") or org.is_internal:
            raise Invalid(errors=[{"field": "organization_id", "message": "Choose a client or a prospect."}])
    else:
        p = body.prospect
        if not body.confirm_different:
            dups = find_duplicates(db, name=p.name, website=p.website, emails=[c.email for c in body.contacts if c.email])
            if dups:
                raise Conflict("This may be a company already on file. Open it, or confirm this is a different company.", errors=dups)
        org = create_prospect(db, name=p.name, actor_id=actor.id, website=p.website, industry=p.industry, employee_band=p.size_band, hq_state=p.hq_state,
                              hq_country=(p.hq_country or "").upper() or None)
        audit.record(db, actor_id=actor.id, action="prospect.create", obj=org, after=column_snapshot(org), request=request, organization_id=actor.organization.id,
                     summary=f"New prospect {org.name}")
    _check_partner(db, body.partner_id)
    owner = body.owner_id or actor.id
    _check_owner(db, actor, owner)
    if owner != actor.id and not _can(db, actor, Action.REASSIGN_OPPORTUNITIES):
        raise Forbidden("Only a Sales Manager or the Chief Auditor logs an opportunity for someone else.")
    products = body.products_of_interest or []
    name = (body.name or "").strip() or f"{org.name} · {', '.join(PRODUCTS[p] for p in products) or 'New opportunity'}"
    now = utcnow()
    o = Opportunity(organization_id=org.id, trigger="manual", service=name[:200], service_kind="other", why_now=TRIGGER_EVENTS.get(body.trigger_event or "", "")[:300],
                    value=body.est_value, owner_id=owner, next_step=body.next_step, next_step_due=body.next_step_due, name=name[:200], source=body.source,
                    partner_id=body.partner_id, segment=body.segment, trigger_event=body.trigger_event, products_of_interest=products, close_date=body.close_date,
                    bant=body.bant.model_dump() if body.bant else None, competitors=body.competitors, created_by=actor.id, last_activity_at=now, stage="new")
    independence.refresh(db, o)
    o.needs_ca_approval = bool(o.independence_flag) or is_current_audit_client(db, org.id)
    db.add(o)
    db.flush()
    for c in body.contacts:
        db.add(OpportunityContact(opportunity_id=o.id, created_by=actor.id, **c.model_dump()))
    log(db, o, "created", f"Logged by {actor.user.name}" + (f" from {SOURCES[body.source].lower()}" if body.source else ""), actor.id, at=now)
    db.flush()
    audit.record(db, actor_id=actor.id, action="opportunity.create", obj=o, after=column_snapshot(o), request=request, organization_id=actor.organization.id,
                 summary=f"Opportunity for {org.name}: {name}")
    if owner != actor.id:
        notify(db, [db.get(User, owner)], "opportunity_assigned", f"Opportunity assigned to you: {org.name}", name, f"/sales/opportunities/{o.id}",
               settings=settings, email_template="notification")
    return get_opp(o.id, actor, db)


# ---- SM-01 Sales home
@router.get("/sales/home")
def sales_home(scope: str = "mine", actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_OPPORTUNITIES)
    if not (_can(db, actor, Action.VIEW_SALES_HOME) or _can(db, actor, Action.VIEW_TEAM_PIPELINE)):
        raise Forbidden()
    return desk.home(db, actor, scope, _can(db, actor, Action.VIEW_TEAM_PIPELINE))


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/opportunities/{opp_id}/request-approval")
def request_approval(opp_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    _check_edit(db, actor, o)
    if not o.needs_ca_approval:
        raise Conflict("This client is not a current audit client; no approval is needed.")
    o.approval_requested_at = utcnow()
    org = db.get(Organization, o.organization_id)
    log(db, o, "approval_requested", body.note or "Approval requested", actor.id)
    chiefs = [u for u in db.scalars(select(User).where(User.organization_id == actor.organization.id, User.deleted_at.is_(None))) if "chief_auditor" in {r.role for r in roles_of(db, u.id)}]
    notify(db, chiefs, "opportunity_approval", f"Approve an offer to {org.name}", f"{actor.user.name} asks to offer “{o.service}”. {body.note}".strip(), link=f"/sales/opportunities/{o.id}")
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
def decide(opp_id: str, body: DecisionIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.APPROVE_OPPORTUNITY)
    o = _get(db, opp_id)
    check_independence(db, o.organization_id, o.service_kind)  # approval never overrides the independence rule
    o.ca_decision = "approved" if body.decision == "approve" else "declined"
    o.ca_approved_by, o.ca_approved_at, o.ca_note = actor.id, utcnow(), body.note or None
    log(db, o, "approved" if body.decision == "approve" else "declined", body.note or ("Offer approved" if body.decision == "approve" else "Offer declined"), actor.id)
    audit.record(db, actor_id=actor.id, action=f"opportunity.{o.ca_decision}", obj=o, request=request, organization_id=actor.organization.id, summary=f"Offer {o.ca_decision}: {o.service}")
    if o.owner_id and o.owner_id != actor.id:
        notify(db, [db.get(User, o.owner_id)], "opportunity_decided", f"Offer {o.ca_decision}: {o.service}", body.note or None, link=f"/sales/opportunities/{o.id}")
    return opp_out(db, o)


class ProposalIn(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)


@router.post("/opportunities/{opp_id}/send-proposal")
def send_proposal(opp_id: str, body: ProposalIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.WORK_OPPORTUNITIES)
    o = _get(db, opp_id)
    _check_edit(db, actor, o)
    if not can_send_offer(o):
        raise Conflict("This client is a current audit client. The Chief Auditor approves the offer before it is sent.")
    check_independence(db, o.organization_id, o.service_kind)
    log(db, o, "proposal", body.summary, actor.id)
    if o.stage in ("new", "contacted"):
        o.stage = "proposal"
    audit.record(db, actor_id=actor.id, action="opportunity.proposal", obj=o, request=request, organization_id=actor.organization.id, summary=f"Proposal logged: {o.service}")
    return opp_out(db, o)


# ---- 11-03 F8: the periodic opportunity scan (Futran Admin settings)
class ScanSettingIn(BaseModel):
    every_days: int | None = Field(default=None, ge=1, le=365)


def _run_out(db: Session, run) -> dict | None:
    if run is None:
        return None
    found = []
    for oid in run.found or []:
        o = db.get(Opportunity, oid)
        if o is not None:
            org = db.get(Organization, o.organization_id)
            found.append({"id": o.id, "client_name": org.name if org else "", "trigger_label": TRIGGER_LABELS.get(o.trigger, o.trigger), "service": o.service,
                          "why_now": o.why_now})
    return {"id": run.id, "trigger": run.trigger, "status": run.status, "started_at": run.started_at.isoformat(), "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "since": run.since.isoformat(), "by": _name(db, run.started_by) or "Scheduled", "counts": run.counts or {}, "errors": run.errors or [], "found": found}


def _scan_out(db: Session, actor: Actor) -> dict:
    from app.sales import scan

    try:
        authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
        can_edit = True
    except Exception:
        can_edit = False
    nxt = scan.next_run_on(db)
    return {"every_days": scan.interval(db), "choices": list(scan.CHOICES), "min_days": scan.MIN_DAYS, "max_days": scan.MAX_DAYS,
            "last_run": _run_out(db, scan.last_run(db)), "next_run_on": nxt.isoformat() if nxt else None, "can_edit": can_edit}


@router.get("/admin/opportunity-scan")
def get_scan(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_PLATFORM_SETTINGS)
    return _scan_out(db, actor)


@router.put("/admin/opportunity-scan")
def put_scan(body: ScanSettingIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.sales import scan

    authorize(db, actor, Action.MANAGE_FUTRAN_USERS)  # the Futran Admin: "Manage Futran users and platform settings" (§5)
    scan.set_interval(db, actor.user, body.every_days, request=request)
    return _scan_out(db, actor)


@router.post("/admin/opportunity-scan/run")
def run_scan_now(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.sales import scan

    authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
    scan.run_now(db, actor.user, request=request)
    return _scan_out(db, actor)
