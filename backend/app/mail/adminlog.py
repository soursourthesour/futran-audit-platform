"""The email admin log (spec §26.7): connection changes, admin consent, sender changes, group edits, directory sync
results and every send. Append-only and kept 7 years (§15)."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.mail.models import AdminLogEntry
from app.tenancy.models import Organization, User

RETENTION_YEARS = 7
CATEGORIES = ("connection", "consent", "sender", "group", "directory", "send", "template", "settings")


def _plus_years(d: datetime, years: int) -> datetime:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def retain_until(at: datetime) -> datetime:
    return _plus_years(at, RETENTION_YEARS)


def write(db: Session, *, organization_id: str, category: str, action: str, summary: str, actor: User | None = None, actor_name: str | None = None,
          details: dict | None = None, engagement_id: str | None = None, send_id: str | None = None, department_id: str | None = None) -> AdminLogEntry:
    org = db.get(Organization, organization_id)
    now = utcnow()
    if actor is not None and actor_name is None:
        from app.policy.roles import role_label
        from app.tenancy.service import roles_of

        roles = [r.role for r in roles_of(db, actor.id)]
        actor_name = f"{actor.name} · {role_label(roles[0])}" if roles else actor.name
    e = AdminLogEntry(owner="futran" if org is not None and org.type == "futran" else "client", organization_id=organization_id, engagement_id=engagement_id, at=now,
                      actor_id=actor.id if actor else None, actor_name=actor_name or "System", category=category, action=action, summary=summary[:500],
                      details=details, send_id=send_id, department_id=department_id, retain_until=retain_until(now))
    db.add(e)
    return e


def query(db: Session, *, organization_ids: set[str] | None, engagement_ids: set[str] | None = None, category: str | None = None,
          department_ids: set[str] | None = None, limit: int = 500) -> list[AdminLogEntry]:
    stmt = select(AdminLogEntry)
    if organization_ids is not None:
        stmt = stmt.where(AdminLogEntry.organization_id.in_(organization_ids))
    if engagement_ids is not None:
        stmt = stmt.where(AdminLogEntry.engagement_id.in_(engagement_ids))
    if department_ids is not None:
        stmt = stmt.where(AdminLogEntry.department_id.in_(department_ids))
    if category:
        stmt = stmt.where(AdminLogEntry.category == category)
    return list(db.scalars(stmt.order_by(AdminLogEntry.at.desc(), AdminLogEntry.id).limit(min(limit, 2000))))


def entry_out(e: AdminLogEntry) -> dict:
    return {"id": e.id, "at": e.at.isoformat(), "who": e.actor_name, "category": e.category, "action": e.action, "summary": e.summary, "details": e.details,
            "send_id": e.send_id, "retain_until": e.retain_until.date().isoformat()}
