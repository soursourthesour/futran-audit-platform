"""Futran Admin > Platform trust (`/staff/admin/trust`, spec §21 F19): the SOC 2 readiness register and the platform's own
AI systems. The Futran Admin edits; the Chief Auditor and QA Reviewer read. Every endpoint calls `authorize`."""
import importlib
import re
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.platformtrust.models import CRITERIA, STATUSES, SocControl
from app.platformtrust.seed import counts
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.register.models import RegisterSystem
from app.tenancy.models import User

router = APIRouter(tags=["platform trust"])


class ControlPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    owner_id: str | None = None
    status: str | None = None
    evidence_link: str | None = Field(default=None, max_length=500)
    last_reviewed_on: str | None = None
    review_months: int | None = Field(default=None, ge=1, le=36)
    notes: str | None = None


class ControlIn(ControlPatch):
    code: str = Field(min_length=1, max_length=12)
    criterion: str
    title: str = Field(min_length=1, max_length=200)


def _org(db: Session, actor: Actor, action: Action):
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, action, org_id=actor.organization.id)
    return actor.organization


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return date(year, month, 28)


def control_out(db: Session, c: SocControl) -> dict:
    owner = db.get(User, c.owner_id) if c.owner_id else None
    nxt = _add_months(c.last_reviewed_on, c.review_months) if c.last_reviewed_on else None
    return {"id": c.id, "code": c.code, "criterion": c.criterion, "criterion_label": CRITERIA.get(c.criterion), "title": c.title, "description": c.description,
            "owner_id": c.owner_id, "owner": owner.name if owner else None, "status": c.status, "status_label": STATUSES.get(c.status), "evidence_link": c.evidence_link,
            "last_reviewed_on": c.last_reviewed_on.isoformat() if c.last_reviewed_on else None, "review_months": c.review_months,
            "next_review_on": nxt.isoformat() if nxt else None, "review_overdue": bool(nxt and nxt < date.today()), "notes": c.notes}


def _system_out(s: RegisterSystem) -> dict:
    return {"id": s.id, "reference": s.reference, "name": s.name, "stage": s.stage, "purpose": s.purpose, "risk_tier": s.risk_tier, "ai_provider": s.ai_provider, "model_name": s.model_name}


def _trust_center(db: Session, org_id: str) -> dict | None:
    """Futran's own Trust Center page, when WS-I's Trust Center (app.trust) is installed and offers a public link."""
    try:
        mod = importlib.import_module("app.trust.service")
    except ModuleNotFoundError:
        return None
    fn = getattr(mod, "public_link_for", None)
    link = fn(db, org_id) if fn else None
    return {"link": link} if link else None


@router.get("/staff/admin/trust")
def page(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _org(db, actor, Action.VIEW_PLATFORM_TRUST)
    rows = list(db.scalars(select(SocControl).where(SocControl.organization_id == org.id, SocControl.deleted_at.is_(None)).order_by(SocControl.order, SocControl.code)))
    systems = db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org.id, RegisterSystem.deleted_at.is_(None)).order_by(RegisterSystem.reference))
    try:
        authorize(db, actor, Action.MANAGE_PLATFORM_TRUST, org_id=org.id)
        can_edit = True
    except (Forbidden, NotFound):
        can_edit = False
    by = counts(db, org.id)
    outs = [control_out(db, c) for c in rows]
    people = db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None), User.status == "active").order_by(User.name)) if can_edit else []
    return {"controls": outs, "criteria": [{"value": k, "label": v} for k, v in CRITERIA.items()], "statuses": [{"value": k, "label": v} for k, v in STATUSES.items()],
            "summary": {"total": len(rows), **{k: by.get(k, 0) for k in STATUSES}, "review_overdue": sum(o["review_overdue"] for o in outs)},
            "ai_systems": [_system_out(s) for s in systems], "trust_center": _trust_center(db, org.id), "can_edit": can_edit,
            "people": [{"id": u.id, "name": u.name} for u in people]}


def _apply(db: Session, org_id: str, c: SocControl, body: ControlPatch) -> None:
    errs = []
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        if data["status"] not in STATUSES:
            errs.append({"field": "status", "message": "Choose a status from the list."})
        else:
            c.status = data["status"]
    if "owner_id" in data:
        u = db.get(User, data["owner_id"]) if data["owner_id"] else None
        if data["owner_id"] and (u is None or u.organization_id != org_id or u.deleted_at is not None):
            errs.append({"field": "owner_id", "message": "Choose a person at Futran."})
        else:
            c.owner_id = u.id if u else None
    if "evidence_link" in data:
        link = (data["evidence_link"] or "").strip()
        if link and not link.lower().startswith(("https://", "http://")) and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", link):  # another scheme (javascript:, data:)
            errs.append({"field": "evidence_link", "message": "Enter a web address starting https:// or a short description of where the evidence is."})
        else:
            c.evidence_link = link or None
    if "last_reviewed_on" in data:
        try:
            d = date.fromisoformat(data["last_reviewed_on"]) if data["last_reviewed_on"] else None
        except ValueError:
            d = None
            errs.append({"field": "last_reviewed_on", "message": "Enter a date."})
        if d and d > date.today():
            errs.append({"field": "last_reviewed_on", "message": "This is in the future."})
        elif not errs or errs[-1]["field"] != "last_reviewed_on":
            c.last_reviewed_on = d
    for k in ("title", "description", "notes"):
        if k in data:
            v = (data[k] or "").strip()
            if k == "title" and not v:
                errs.append({"field": "title", "message": "Give the control a title."})
            else:
                setattr(c, k, v or None)
    if "review_months" in data and data["review_months"]:
        c.review_months = data["review_months"]
    if errs:
        raise Invalid(errors=errs)


@router.patch("/staff/admin/trust/controls/{control_id}")
def patch_control(control_id: str, body: ControlPatch, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _org(db, actor, Action.MANAGE_PLATFORM_TRUST)
    c = db.get(SocControl, control_id)
    if c is None or c.deleted_at is not None or c.organization_id != org.id:
        raise NotFound()
    before = control_out(db, c)
    _apply(db, org.id, c, body)
    c.updated_by = actor.id
    db.flush()
    after = control_out(db, c)
    audit.record(db, actor_id=actor.id, action="platform_trust.control_edited", obj=c, request=actor.request,
                 before={k: before[k] for k in before if before[k] != after[k]}, after={k: after[k] for k in after if before[k] != after[k]}, summary=f"Updated SOC 2 control {c.code} {c.title}")
    return after


@router.post("/staff/admin/trust/controls")
def add_control(body: ControlIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _org(db, actor, Action.MANAGE_PLATFORM_TRUST)
    code = body.code.strip().upper()
    if body.criterion not in CRITERIA:
        raise Invalid(errors=[{"field": "criterion", "message": "Choose a trust services criterion."}])
    if db.scalar(select(SocControl.id).where(SocControl.organization_id == org.id, SocControl.code == code)):
        raise Conflict(f"There is already a control {code}.")
    top = max((c.order for c in db.scalars(select(SocControl).where(SocControl.organization_id == org.id))), default=0)
    c = SocControl(organization_id=org.id, code=code, criterion=body.criterion, title=body.title.strip(), status="not_started", review_months=12, order=top + 1, created_by=actor.id)
    db.add(c)
    _apply(db, org.id, c, ControlPatch(**body.model_dump(exclude_unset=True, exclude={"code", "criterion", "title"})))
    db.flush()
    audit.record(db, actor_id=actor.id, action="platform_trust.control_added", obj=c, request=actor.request, summary=f"Added SOC 2 control {c.code} {c.title}")
    return control_out(db, c)
