from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log.models import AuditLog


def record(
    db: Session,
    *,
    actor_id: str | None,
    action: str,
    obj=None,
    before: dict | None = None,
    after: dict | None = None,
    request=None,
    organization_id: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    engagement_id: str | None = None,
    summary: str | None = None,
    actor_name: str | None = None,
) -> AuditLog:
    """Write one append-only audit entry. The tenant is the object's tenant unless given."""
    if obj is not None:
        object_type = object_type or type(obj).__name__
        object_id = object_id or getattr(obj, "id", None)
        organization_id = organization_id or getattr(obj, "organization_id", None)
        engagement_id = engagement_id or getattr(obj, "engagement_id", None)
    if organization_id is None:
        raise ValueError("audit.record needs an organization_id or an object with one")
    ip = ua = None
    if request is not None:
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "")[:300]
    if actor_id and actor_name is None:
        from app.tenancy.models import User

        u = db.get(User, actor_id)
        actor_name = u.name if u else None
    entry = AuditLog(
        organization_id=organization_id,
        actor_id=actor_id,
        actor_name=actor_name,
        action=action,
        object_type=object_type or "Unknown",
        object_id=object_id,
        engagement_id=engagement_id,
        summary=summary,
        before=before,
        after=after,
        ip=ip,
        user_agent=ua,
    )
    db.add(entry)
    return entry


def query(
    db: Session,
    *,
    organization_id: str | None = None,
    organization_ids: list[str] | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    actor_id: str | None = None,
    engagement_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
) -> list[AuditLog]:
    stmt = select(AuditLog)
    if organization_id:
        stmt = stmt.where(AuditLog.organization_id == organization_id)
    if organization_ids is not None:
        stmt = stmt.where(AuditLog.organization_id.in_(organization_ids))
    if object_type:
        stmt = stmt.where(AuditLog.object_type == object_type)
    if object_id:
        stmt = stmt.where(AuditLog.object_id == object_id)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if engagement_id:
        stmt = stmt.where(AuditLog.engagement_id == engagement_id)
    if since:
        stmt = stmt.where(AuditLog.at >= since)
    if until:
        stmt = stmt.where(AuditLog.at <= until)
    return list(db.scalars(stmt.order_by(AuditLog.at.desc(), AuditLog.id).limit(limit)))
