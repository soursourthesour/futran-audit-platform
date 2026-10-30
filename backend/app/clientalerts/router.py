"""A1 automatic client alerts (spec §27.6): rules grid and approval queue. Chief Auditor and Futran Admin."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.core.models import column_snapshot
from app.clientalerts.models import APPROVALS, AlertRule, AlertSend
from app.clientalerts.service import (APPROVAL_LABELS, AUDIENCE_LABELS, GROUP_ROLES, WHEN_LABELS, deliver, ensure_rules, preview, sender_label,
                                      subject_of, system_names)
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization, User

router = APIRouter(tags=["client alerts"])


def rule_out(r: AlertRule) -> dict:
    return {
        "id": r.id, "trigger": r.trigger, "when_label": WHEN_LABELS.get(r.trigger, r.trigger), "audience_rule": r.audience_rule,
        "audience_label": AUDIENCE_LABELS.get(r.audience_rule, r.audience_rule), "client_groups": r.client_groups or [], "email_label": r.email_label,
        "approval": r.approval, "approval_label": APPROVAL_LABELS.get(r.approval, r.approval), "active": r.active, "days_before": r.days_before or [],
        "last_sent_at": r.last_sent_at.isoformat() if r.last_sent_at else None, "last_sent_count": r.last_sent_count,
    }


def send_out(db: Session, s: AlertSend) -> dict:
    org = db.get(Organization, s.organization_id)
    u = db.get(User, s.approved_by) if s.approved_by else None
    return {
        "id": s.id, "rule_id": s.alert_rule_id, "organization_id": s.organization_id, "client_name": org.name if org else "", "change_ref": s.change_ref,
        "headline": s.headline, "subject": subject_of(db, s), "systems": system_names(db, s.affected_system_ids), "todo_count": len(s.todo_items or []),
        "status": s.status, "sent_from": s.sent_from or sender_label(db, s.organization_id), "deadline": s.deadline.isoformat() if s.deadline else None,
        "created_at": s.created_at.isoformat(), "sent_at": s.sent_at.isoformat() if s.sent_at else None, "approved_by_name": u.name if u else None,
    }


@router.get("/alerts/rules")
def list_rules(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_CLIENT_ALERTS)
    return {"rules": [rule_out(r) for r in ensure_rules(db)], "groups": sorted(GROUP_ROLES), "approvals": [{"value": a, "label": APPROVAL_LABELS[a]} for a in APPROVALS]}


class RulePatch(BaseModel):
    active: bool | None = None
    client_groups: list[str] | None = None
    approval: str | None = None
    email_label: str | None = Field(default=None, min_length=2, max_length=160)

    @field_validator("approval")
    @classmethod
    def _a(cls, v):
        if v is not None and v not in APPROVALS:
            raise ValueError("Unknown approval.")
        return v

    @field_validator("client_groups")
    @classmethod
    def _g(cls, v):
        if v is not None and (not v or set(v) - set(GROUP_ROLES)):
            raise ValueError(f"Choose from {', '.join(sorted(GROUP_ROLES))}.")
        return v


@router.patch("/alerts/rules/{rule_id}")
def patch_rule(rule_id: str, body: RulePatch, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_CLIENT_ALERTS)
    r = db.get(AlertRule, rule_id)
    if r is None:
        raise NotFound()
    before = column_snapshot(r)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    r.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="alert_rule.update", obj=r, before=before, after=column_snapshot(r), request=request, organization_id=actor.organization.id, summary=f"Changed alert rule: {WHEN_LABELS.get(r.trigger)}")
    return rule_out(r)


class RuleBulk(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    active: bool


@router.post("/alerts/rules/bulk")
def bulk_rules(body: RuleBulk, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_CLIENT_ALERTS)
    n = 0
    for rid in body.ids:
        r = db.get(AlertRule, rid)
        if r is not None and r.active != body.active:
            r.active, r.updated_by = body.active, actor.id
            n += 1
    audit.record(db, actor_id=actor.id, action="alert_rule.bulk", object_type="AlertRule", request=request, organization_id=actor.organization.id, summary=f"{'Turned on' if body.active else 'Paused'} {n} alert rules")
    return {"changed": n}


@router.get("/alerts/rules/{rule_id}/history")
def rule_history(rule_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_CLIENT_ALERTS)
    return [send_out(db, s) for s in db.scalars(select(AlertSend).where(AlertSend.alert_rule_id == rule_id).order_by(AlertSend.created_at.desc()).limit(200))]


def _can_queue(db: Session, actor: Actor) -> bool:
    for a in (Action.MANAGE_CLIENT_ALERTS, Action.APPROVE_CLIENT_ALERTS, Action.APPROVE_ADDON_ALERTS):
        try:
            authorize(db, actor, a)
            return True
        except Exception:
            continue
    return False


@router.get("/alerts/queue")
def queue(status: str = "waiting_approval", actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Sends waiting for approval, grouped by the change that created them."""
    if not _can_queue(db, actor):
        raise Forbidden()
    rows = list(db.scalars(select(AlertSend).where(AlertSend.status.in_(status.split(","))).order_by(AlertSend.created_at.desc()).limit(500)))
    groups: dict[str, dict] = {}
    for s in rows:
        g = groups.setdefault(s.change_ref, {"change_ref": s.change_ref, "headline": s.headline, "rule_id": s.alert_rule_id, "items": []})
        g["items"].append(send_out(db, s))
    for g in groups.values():
        r = db.get(AlertRule, g["rule_id"])
        g["approval"] = r.approval if r else None
        g["when_label"] = WHEN_LABELS.get(r.trigger) if r else ""
    return {"groups": list(groups.values())}


def _send_or_404(db: Session, sid: str) -> AlertSend:
    s = db.get(AlertSend, sid)
    if s is None:
        raise NotFound()
    return s


def _authorize_send(db: Session, actor: Actor, s: AlertSend) -> None:
    rule = db.get(AlertRule, s.alert_rule_id)
    if rule is not None and rule.approval == "sales_owner":
        authorize(db, actor, Action.APPROVE_ADDON_ALERTS)
        if s.owner_id and s.owner_id != actor.id and "chief_auditor" not in actor.role_names:
            raise Forbidden("Only the Sales owner or a Chief Auditor approves this alert.")
    else:
        authorize(db, actor, Action.APPROVE_CLIENT_ALERTS)


@router.get("/alerts/sends/{send_id}/preview")
def send_preview(send_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if not _can_queue(db, actor):
        raise Forbidden()
    s = _send_or_404(db, send_id)
    return preview(db, request.app.state.settings, s) | send_out(db, s)


class SendPatch(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    intro: str | None = Field(default=None, max_length=4000)


@router.patch("/alerts/sends/{send_id}")
def edit_send(send_id: str, body: SendPatch, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    s = _send_or_404(db, send_id)
    _authorize_send(db, actor, s)
    if s.status == "sent":
        from app.core.errors import Conflict

        raise Conflict("This alert has already been sent.")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, (v or None))
    audit.record(db, actor_id=actor.id, action="client_alert.edit", obj=s, request=request, organization_id=s.organization_id, summary=f"Edited client alert: {subject_of(db, s)}")
    return send_out(db, s)


class IdsIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


@router.post("/alerts/sends/approve")
def approve_sends(body: IdsIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    settings = request.app.state.settings
    sends = [_send_or_404(db, i) for i in body.ids]
    for s in sends:
        _authorize_send(db, actor, s)
    n = 0
    for s in sends:
        if s.status in ("waiting_approval", "held"):
            deliver(db, settings, s, approver_id=actor.id)
            n += s.status == "sent"
    return {"sent": n}


@router.post("/alerts/sends/hold")
def hold_sends(body: IdsIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    n = 0
    for i in body.ids:
        s = _send_or_404(db, i)
        _authorize_send(db, actor, s)
        if s.status == "waiting_approval":
            s.status = "held"
            n += 1
            audit.record(db, actor_id=actor.id, action="client_alert.hold", obj=s, request=request, organization_id=s.organization_id, summary=f"Held client alert: {subject_of(db, s)}")
    return {"held": n}
