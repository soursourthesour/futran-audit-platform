"""Directory sync (spec §26.2): people and groups from Microsoft Entra ID or Google Workspace. Daily by default.

Imports name, email, department, job title, manager and office for the people in the chosen directory group (or
everyone), guests only when asked. Leavers (gone from the directory, or account disabled) are marked as left and
removed from groups; their past answers are kept. Departments are matched by name to the client's departments;
names that match none are listed in the report rather than created, so the audit scope never changes by itself.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Invalid
from app.mail import adminlog, tokens
from app.mail.models import DirectoryGroup, DirectoryPerson, DirectorySync, MailConnection, MailGroupMember, UserMailConnection
from app.mail.providers import ProviderError, get_adapter
from app.tenancy.models import Department, User

SCHEDULES = {"daily": timedelta(days=1), "6h": timedelta(hours=6), "weekly": timedelta(days=7)}


def for_connection(db: Session, conn: MailConnection) -> DirectorySync | None:
    return db.scalar(select(DirectorySync).where(DirectorySync.connection_id == conn.id, DirectorySync.deleted_at.is_(None)).limit(1))


def configure(db: Session, actor: User | None, conn: MailConnection, data: dict) -> DirectorySync:
    ds = for_connection(db, conn)
    if ds is None:
        ds = DirectorySync(organization_id=conn.organization_id, connection_id=conn.id, schedule="daily", department_field="department", include_guests=False,
                           use_directory_groups=True, enabled=True, created_by=actor.id if actor else None)
        db.add(ds)
    if "schedule" in data:
        if data["schedule"] not in (*SCHEDULES, "off"):
            raise Invalid(errors=[{"field": "schedule", "message": "Choose how often to sync."}])
        ds.schedule = data["schedule"]
    if "department_field" in data:
        if data["department_field"] not in ("department", "office"):
            raise Invalid(errors=[{"field": "department_field", "message": "Choose where the department comes from."}])
        ds.department_field = data["department_field"]
    for k in ("include_guests", "use_directory_groups", "enabled"):
        if k in data:
            setattr(ds, k, bool(data[k]))
    if "scope_group" in data:
        ds.scope_group = data["scope_group"] or None
        g = db.scalar(select(DirectoryGroup).where(DirectoryGroup.organization_id == conn.organization_id, DirectoryGroup.directory_id == ds.scope_group)) if ds.scope_group else None
        ds.scope_group_name = data.get("scope_group_name") or (g.name if g else None)
    db.flush()
    return ds


def sync_due(ds: DirectorySync, now: datetime) -> bool:
    if not ds.enabled or ds.schedule == "off":
        return False
    return ds.last_run_at is None or ds.last_run_at + SCHEDULES.get(ds.schedule, SCHEDULES["daily"]) <= now


def _dept_index(db: Session, org_id: str) -> dict[str, str]:
    return {d.name.strip().lower(): d.id for d in db.scalars(select(Department).where(Department.organization_id == org_id, Department.deleted_at.is_(None)))}


def _mark_left(db: Session, p: DirectoryPerson, now: datetime) -> None:
    p.status, p.left_at = "left", p.left_at or now
    for m in db.scalars(select(MailGroupMember).where(MailGroupMember.person_id == p.id, MailGroupMember.deleted_at.is_(None))):
        m.deleted_at = now
    user_id = p.user_id or db.scalar(select(User.id).where(func.lower(User.email) == p.email.lower()))
    if user_id:
        for uc in db.scalars(select(UserMailConnection).where(UserMailConnection.user_id == user_id, UserMailConnection.status == "connected")):
            uc.status = "disconnected"
            tokens.clear(uc)


def run_directory_sync(db: Session, settings: Settings, ds: DirectorySync, actor: User | None = None, now: datetime | None = None) -> DirectorySync:
    now = now or utcnow()
    conn = db.get(MailConnection, ds.connection_id)
    adapter = get_adapter(settings, conn.provider if conn else None)
    if conn is None or conn.status != "connected" or adapter is None:
        raise Conflict("Connect the mailbox before syncing the directory.")
    org_id = conn.organization_id
    try:
        grant = tokens.load(settings, conn)
        groups = adapter.list_groups(grant) if ds.use_directory_groups else []
        entries = adapter.list_people(grant, scope_group=ds.scope_group, include_guests=ds.include_guests)
        if ds.use_directory_groups:
            members: dict[str, list[str]] = {}
            for g in groups:
                for uid in adapter.group_member_ids(grant, g.directory_id):
                    members.setdefault(uid, []).append(g.directory_id)
            for e in entries:
                e.group_ids = sorted(set(e.group_ids) | set(members.get(e.directory_id, [])))
        tokens.save_if_refreshed(settings, conn, grant)
    except (ProviderError, tokens.TokenError) as exc:
        ds.status, ds.last_run_at, ds.report = "failed", now, {"error": str(exc)[:500]}
        adminlog.write(db, organization_id=org_id, category="directory", action="sync_failed", actor=actor, summary=f"Directory sync failed: {str(exc)[:200]}")
        db.flush()
        return ds

    by_id = {g.directory_id: g for g in db.scalars(select(DirectoryGroup).where(DirectoryGroup.organization_id == org_id, DirectoryGroup.deleted_at.is_(None)))}
    for g in groups:
        row = by_id.get(g.directory_id)
        if row is None:
            row = DirectoryGroup(organization_id=org_id, connection_id=conn.id, directory_id=g.directory_id, name=g.name)
            db.add(row)
        row.name, row.synced_at = g.name, now
        row.member_count = sum(1 for e in entries if g.directory_id in e.group_ids) or g.member_count

    depts = _dept_index(db, org_id)
    users = {u.email.lower(): u.id for u in db.scalars(select(User).where(User.organization_id == org_id, User.deleted_at.is_(None)))}
    existing = {p.email.lower(): p for p in db.scalars(select(DirectoryPerson).where(DirectoryPerson.organization_id == org_id, DirectoryPerson.deleted_at.is_(None)))}
    by_dir = {p.directory_id: p for p in existing.values() if p.directory_id}
    seen: set[str] = set()
    joined = left = changed = 0
    unmatched: set[str] = set()
    for e in entries:
        if not e.email:
            continue
        p = by_dir.get(e.directory_id) or existing.get(e.email.lower())
        dept_name = (e.office if ds.department_field == "office" else e.department) or None
        dept_id = depts.get(dept_name.strip().lower()) if dept_name else None
        if dept_name and dept_id is None:
            unmatched.add(dept_name)
        if not e.enabled:
            if p is not None and p.status != "left":
                _mark_left(db, p, now)
                left += 1
            if p is not None:
                seen.add(p.id)
            continue
        if p is None:
            p = DirectoryPerson(organization_id=org_id, email=e.email.lower(), name=e.name, source="directory", status="active", directory_group_ids=[])
            db.add(p)
            db.flush()
            joined += 1
        else:
            if p.status == "left":
                joined += 1
            elif p.source == "directory" and (p.name, p.department, p.job_title, p.office) != (e.name, dept_name, e.job_title, e.office):
                changed += 1
            p.status, p.left_at = ("active", None) if p.status == "left" else (p.status, p.left_at)
        p.source, p.directory_id, p.email, p.name = "directory", e.directory_id, e.email.lower(), e.name
        p.department, p.job_title, p.manager_id, p.office, p.is_guest = dept_name, e.job_title, e.manager_id, e.office, e.is_guest
        if dept_id:
            p.department_id = dept_id
        p.directory_group_ids = list(e.group_ids)
        p.user_id = p.user_id or users.get(p.email)
        seen.add(p.id)
    for p in existing.values():
        if p.source == "directory" and p.id not in seen and p.status != "left":
            _mark_left(db, p, now)
            left += 1
    active = sum(1 for e in entries if e.enabled)
    ds.people, ds.joined, ds.left, ds.changed, ds.last_run_at, ds.status = active, joined, left, changed, now, "ok"
    ds.report = {"groups": len(groups), "unmatched_departments": sorted(unmatched), "departments": len({(e.department or "").lower() for e in entries if e.department})}
    conn.last_sync_at = now
    from app.mail.groups import ensure_default_groups

    ensure_default_groups(db, org_id)
    adminlog.write(db, organization_id=org_id, category="directory", action="sync", actor=actor,
                   summary=f"{active:,} people, {joined} joined, {left} left, {changed} changed", details={"groups": len(groups), "unmatched_departments": sorted(unmatched)})
    db.flush()
    return ds


def run_due(db: Session, settings: Settings, now: datetime | None = None) -> int:
    now = now or utcnow()
    n = 0
    for ds in list(db.scalars(select(DirectorySync).where(DirectorySync.deleted_at.is_(None)))):
        if sync_due(ds, now):
            conn = db.get(MailConnection, ds.connection_id)
            if conn is not None and conn.status == "connected" and get_adapter(settings, conn.provider) is not None:
                run_directory_sync(db, settings, ds, now=now)
                n += 1
    return n
