"""M6 refresh alerts and settings (spec §27.9). Each person sees only their own alerts."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.core.models import column_snapshot
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.refresh.service import open_items
from app.staffalerts.models import SCOPES, AlertSetting, StaffAlert
from app.staffalerts.service import futran_users_with, get_setting, send_test_alert

router = APIRouter(tags=["staff alerts"])


def alert_out(db: Session, a: StaffAlert) -> dict:
    waiting = open_items(db, a.refresh_run_id) if a.refresh_run_id and a.resolved_at is None else 0
    return {
        "id": a.id, "kind": a.kind, "scope": a.scope, "title": a.title, "summary": a.summary, "run_id": a.refresh_run_id,
        "at": a.created_at.isoformat(), "read": a.read_at is not None, "resolved": a.resolved_at is not None, "needs_action": waiting > 0,
        "waiting": waiting, "is_copy": a.is_copy, "is_test": a.is_test, "emailed": a.email_send_id is not None,
        "link": "/litigation" if a.scope == "litigation_refresh" else ("/reg/refresh" + (f"?run={a.refresh_run_id}" if a.refresh_run_id else "")),
    }


@router.get("/staff/alerts")
def my_alerts(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Your own alerts. Unresolved alerts stay at the top until the changes are reviewed."""
    if not actor.is_futran:
        raise Forbidden()
    rows = list(db.scalars(select(StaffAlert).where(StaffAlert.user_id == actor.id).order_by(StaffAlert.created_at.desc()).limit(60)))
    items = [alert_out(db, a) for a in rows]
    items.sort(key=lambda i: (not i["needs_action"], i["read"]))  # stable: newest first inside each group
    return {"unread": sum(not i["read"] for i in items), "needs_action": sum(i["needs_action"] for i in items), "items": items}


def _mine(db: Session, actor: Actor, alert_id: str) -> StaffAlert:
    a = db.get(StaffAlert, alert_id)
    if a is None or a.user_id != actor.id:
        raise NotFound()
    return a


@router.post("/staff/alerts/{alert_id}/read")
def read(alert_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    a = _mine(db, actor, alert_id)
    a.read_at = a.read_at or utcnow()
    return {"ok": True}


@router.post("/staff/alerts/read-all")
def read_all(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    for a in db.scalars(select(StaffAlert).where(StaffAlert.user_id == actor.id, StaffAlert.read_at.is_(None))):
        a.read_at = utcnow()
    return {"ok": True}


def setting_out(s: AlertSetting) -> dict:
    return {"scope": s.scope, "recipients_rule": s.recipients_rule, "cc_roles": s.cc_roles or [], "when_rule": s.when_rule, "channels": s.channels or [],
            "remind_after_days": s.remind_after_days, "escalate_after_days": s.escalate_after_days, "escalate_to_roles": s.escalate_to_roles or []}


@router.get("/staff/alerts/settings")
def get_settings(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_ALERT_SETTINGS)
    return {"settings": [setting_out(get_setting(db, sc)) for sc in SCOPES], "chief_auditors": [{"id": u.id, "name": u.name} for u in futran_users_with(db, {"chief_auditor"})]}


class SettingIn(BaseModel):
    recipients_rule: str | None = None
    cc_roles: list[str] | None = None
    when_rule: str | None = None
    channels: list[str] | None = None
    remind_after_days: int | None = Field(default=None, ge=1, le=60)
    escalate_after_days: int | None = Field(default=None, ge=1, le=90)

    @field_validator("recipients_rule")
    @classmethod
    def _r(cls, v):
        if v is not None and v not in ("all_chief_auditors", "runner"):
            raise ValueError("Choose all Chief Auditors or the one who ran the refresh.")
        return v

    @field_validator("cc_roles")
    @classmethod
    def _cc(cls, v):
        if v is not None and set(v) - {"qa_reviewer", "admin"}:
            raise ValueError("Copies can go to the QA Reviewer and the Futran Admin.")
        return v

    @field_validator("when_rule")
    @classmethod
    def _w(cls, v):
        if v is not None and v not in ("every", "changes", "high_impact"):
            raise ValueError("Choose every refresh, only with changes, or only high-impact or low-confidence changes.")
        return v

    @field_validator("channels")
    @classmethod
    def _c(cls, v):
        if v is not None and (not v or set(v) - {"in_app", "email"}):
            raise ValueError("Choose in the app, by email, or both.")
        return v


@router.put("/staff/alerts/settings/{scope}")
def put_settings(scope: str, body: SettingIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_ALERT_SETTINGS)
    if scope not in SCOPES:
        raise NotFound()
    s = get_setting(db, scope)
    before = column_snapshot(s)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    s.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="staff_alert.settings", obj=s, before=before, after=column_snapshot(s), request=request, organization_id=actor.organization.id, summary=f"Changed {scope.replace('_', ' ')} alert settings")
    return setting_out(s)


class TestIn(BaseModel):
    scope: str = "law_refresh"


@router.post("/staff/alerts/test")
def test_alert(body: TestIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_ALERT_SETTINGS)
    if body.scope not in SCOPES:
        raise NotFound()
    out = send_test_alert(db, request.app.state.settings, actor.user, body.scope)
    return {"sent": len(out)}
