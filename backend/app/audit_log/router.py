import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log.models import AuditLog
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden
from app.policy.actions import Action
from app.policy.authorize import assigned_engagement_ids
from app.policy.matrix import Scope, scopes_for

router = APIRouter(prefix="/audit-log", tags=["audit-log"])

CSV_COLUMNS = ["at", "actor", "action", "object_type", "object_id", "summary", "ip"]


@router.get("")
def list_audit_log(
    object_type: str | None = None,
    object_id: str | None = None,
    actor_id: str | None = None,
    engagement_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
    format: str = "json",
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    scopes = scopes_for(actor.role_names, Action.VIEW_AUDIT_LOG)
    if not scopes:
        raise Forbidden()
    stmt = select(AuditLog)
    if actor.is_futran:
        if Scope.ALL not in scopes:
            stmt = stmt.where(AuditLog.engagement_id.in_(assigned_engagement_ids(db, actor.id)))
    else:
        stmt = stmt.where(AuditLog.organization_id == actor.organization.id)
    for col, val in ((AuditLog.object_type, object_type), (AuditLog.object_id, object_id), (AuditLog.actor_id, actor_id), (AuditLog.engagement_id, engagement_id)):
        if val:
            stmt = stmt.where(col == val)
    if since:
        stmt = stmt.where(AuditLog.at >= since)
    if until:
        stmt = stmt.where(AuditLog.at <= until)
    cap = 50_000 if format == "csv" else min(limit, 2000)
    rows = list(db.scalars(stmt.order_by(AuditLog.at.desc()).limit(cap)))
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(CSV_COLUMNS)
        for e in rows:
            w.writerow([e.at.isoformat(), e.actor_name or e.actor_id or "", e.action, e.object_type, e.object_id or "", e.summary or "", e.ip or ""])
        return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'})
    return [
        {
            "id": e.id,
            "at": e.at.isoformat(),
            "actor_id": e.actor_id,
            "actor_name": e.actor_name,
            "action": e.action,
            "object_type": e.object_type,
            "object_id": e.object_id,
            "engagement_id": e.engagement_id,
            "summary": e.summary,
            "ip": e.ip,
        }
        for e in rows
    ]
