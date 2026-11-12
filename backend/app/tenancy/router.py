from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Conflict, Invalid, NotFound
from app.core.models import column_snapshot
from app.invitations.service import invite_user
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.policy.roles import FUTRAN_ROLES, role_label
from app.tenancy.models import Department, Organization, RoleAssignment, User
from app.tenancy.service import assign_role, create_department, create_user, roles_of

router = APIRouter(tags=["admin"])


class UserIn(BaseModel):
    name: str
    email: str
    job_title: str | None = None
    roles: list[str]
    department_id: str | None = None


class UserPatch(BaseModel):
    name: str | None = None
    job_title: str | None = None
    roles: list[str] | None = None
    status: str | None = None
    department_id: str | None = None  # sent as null to clear it


class FutranDepartmentIn(BaseModel):
    name: str


def _futran_department(db: Session, actor: Actor, dept_id: str | None) -> Department | None:
    """A department of the caller's own (Futran) organisation; a client's department is refused as invalid."""
    if not dept_id:
        return None
    d = db.get(Department, dept_id)
    if d is None or d.organization_id != actor.organization.id or d.deleted_at:
        raise Invalid("Choose one of Futran's departments.", [{"field": "department_id", "message": "Not one of Futran's departments."}])
    return d


def user_out(db: Session, u: User) -> dict:
    roles = sorted({r.role for r in roles_of(db, u.id)})
    dept = db.get(Department, u.department_id) if u.department_id else None
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "job_title": u.job_title,
        "department_id": dept.id if dept and not dept.deleted_at else None,
        "department": dept.name if dept and not dept.deleted_at else None,
        "status": u.status,
        "mfa_enabled": u.mfa_enabled,
        "roles": roles,
        "role_labels": [role_label(r) for r in roles],
    }


def _check_futran_roles(roles: list[str]) -> None:
    bad = [r for r in roles if r not in {x.value for x in FUTRAN_ROLES}]
    if bad or not roles:
        raise Invalid("Choose at least one Futran role.", [{"field": "roles", "message": f"Not a Futran role: {', '.join(bad)}" if bad else "Choose at least one role."}])


def _futran_only(actor: Actor) -> None:
    if not actor.is_futran:
        raise NotFound()


@router.get("/admin/users")
def list_futran_users(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.VIEW_FUTRAN_USERS)
    users = db.scalars(select(User).where(User.organization_id == actor.organization.id, User.deleted_at.is_(None)).order_by(User.name))
    return [user_out(db, u) for u in users]


@router.post("/admin/users")
def create_futran_user(body: UserIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
    _check_futran_roles(body.roles)
    dept = _futran_department(db, actor, body.department_id)
    u = create_user(db, actor.organization, name=body.name, email=body.email, job_title=body.job_title, department_id=dept.id if dept else None, actor_id=actor.id)
    for r in body.roles:
        assign_role(db, u, r, actor_id=actor.id)
    audit.record(db, actor_id=actor.id, action="user.create", obj=u, after=column_snapshot(u) | {"roles": body.roles}, request=request, summary=f"Added {u.email}")
    invite_user(db, request.app.state.settings, actor.user, u)
    return user_out(db, u)


@router.patch("/admin/users/{user_id}")
def update_futran_user(user_id: str, body: UserPatch, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
    u = db.get(User, user_id)
    if u is None or u.organization_id != actor.organization.id or u.deleted_at:
        raise NotFound()
    before = column_snapshot(u) | {"roles": sorted(r.role for r in roles_of(db, u.id))}
    if body.status is not None:
        if body.status not in ("active", "disabled", "invited"):
            raise Invalid("Status must be active or disabled.")
        if u.id == actor.id and body.status == "disabled":
            raise Conflict("You cannot disable your own account.")
        if body.status == "active" and u.status == "disabled" and not u.password_hash:
            u.status = "invited"
            body.status = "invited"
        elif body.status == "active" and not u.password_hash:
            raise Conflict("This person has not accepted their invitation yet. Resend it instead.")
        if body.status == "disabled":
            from app.invitations.service import revoke_pending_invitations

            revoke_pending_invitations(db, u.id)
        u.status = body.status
    if body.name is not None:
        u.name = body.name.strip()
    if body.job_title is not None:
        u.job_title = body.job_title
    if "department_id" in body.model_fields_set:
        dept = _futran_department(db, actor, body.department_id)
        u.department_id = dept.id if dept else None
    if body.roles is not None:
        _check_futran_roles(body.roles)
        if u.id == actor.id and "admin" not in body.roles:
            raise Conflict("You cannot remove your own Admin role.")
        for ra in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == u.id, RoleAssignment.deleted_at.is_(None))):
            if ra.role not in body.roles:
                from app.core.clock import utcnow

                ra.deleted_at = utcnow()
        for r in body.roles:
            assign_role(db, u, r, actor_id=actor.id)
    db.flush()
    after = column_snapshot(u) | {"roles": sorted(r.role for r in roles_of(db, u.id))}
    audit.record(db, actor_id=actor.id, action="user.update", obj=u, before=before, after=after, request=request)
    return user_out(db, u)


# ---- Futran's own departments (feedback 10 Nov F1). Futran staff use the same departments table as clients, scoped to Futran's
# organisation; only Futran staff reach these routes, and only the Futran Admin changes the list.

def _dept_out(db: Session, d: Department) -> dict:
    people = db.scalar(select(func.count()).select_from(User).where(User.department_id == d.id, User.deleted_at.is_(None))) or 0
    return {"id": d.id, "name": d.name, "people": people}


def _own_dept(db: Session, actor: Actor, dept_id: str) -> Department:
    d = db.get(Department, dept_id)
    if d is None or d.organization_id != actor.organization.id or d.deleted_at:
        raise NotFound()
    return d


def _dept_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise Invalid("Give the department a name.", [{"field": "name", "message": "Enter a name."}])
    if len(name) > 120:
        raise Invalid("Department names are at most 120 characters.", [{"field": "name", "message": "At most 120 characters."}])
    return name


def _dup(db: Session, actor: Actor, name: str, not_id: str | None = None) -> None:
    q = select(Department.id).where(Department.organization_id == actor.organization.id, func.lower(Department.name) == name.lower(), Department.deleted_at.is_(None))
    if not_id:
        q = q.where(Department.id != not_id)
    if db.scalar(q):
        raise Conflict(f"The department {name} already exists.")


@router.get("/admin/departments")
def list_futran_departments(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.VIEW_FUTRAN_USERS)
    rows = db.scalars(select(Department).where(Department.organization_id == actor.organization.id, Department.deleted_at.is_(None)).order_by(Department.name))
    return [_dept_out(db, d) for d in rows]


@router.post("/admin/departments")
def add_futran_department(body: FutranDepartmentIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
    d = create_department(db, actor.organization, name=_dept_name(body.name), actor_id=actor.id)
    audit.record(db, actor_id=actor.id, action="department.create", obj=d, after={"name": d.name}, request=request, summary=f"Added the Futran department {d.name}")
    return _dept_out(db, d)


@router.patch("/admin/departments/{dept_id}")
def rename_futran_department(dept_id: str, body: FutranDepartmentIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
    d = _own_dept(db, actor, dept_id)
    name = _dept_name(body.name)
    _dup(db, actor, name, not_id=d.id)
    before = {"name": d.name}
    d.name, d.updated_by = name, actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="department.update", obj=d, before=before, after={"name": d.name}, request=request, summary=f"Renamed the Futran department {before['name']} to {d.name}")
    return _dept_out(db, d)


@router.delete("/admin/departments/{dept_id}")
def remove_futran_department(dept_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
    d = _own_dept(db, actor, dept_id)
    if _dept_out(db, d)["people"]:
        raise Conflict(f"People are still in {d.name}. Move them to another department first.")
    from app.core.clock import utcnow

    d.deleted_at = utcnow()
    audit.record(db, actor_id=actor.id, action="department.delete", obj=d, before={"name": d.name}, request=request, summary=f"Removed the Futran department {d.name}")
    return {"deleted": True}


# ---- Administration > Client users (feedback 10 Nov F1): every client organisation's people, read-only, Futran Admin and Chief Auditor.

@router.get("/admin/client-users")
def all_client_users(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _futran_only(actor)
    authorize(db, actor, Action.VIEW_ALL_CLIENT_USERS)
    from app.policy.authorize import visible_org_ids
    from app.policy.roles import CLIENT_ROLES
    from app.tenancy.people import user_department

    allowed = visible_org_ids(db, actor)
    client_roles = {str(r) for r in CLIENT_ROLES}
    orgs = [o for o in db.scalars(select(Organization).where(Organization.type == "client", Organization.deleted_at.is_(None)).order_by(Organization.name))
            if allowed is None or o.id in allowed]
    users, depts = [], set()
    for org in orgs:
        names = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None)))}
        for u in db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None)).order_by(User.name)):
            keys = sorted({r.role for r in roles_of(db, u.id) if r.role in client_roles})
            dept = user_department(db, u, names)
            if dept:
                depts.add(dept)
            users.append({"id": u.id, "name": u.name, "email": u.email, "client_id": org.id, "client": org.name, "department": dept, "job_title": u.job_title,
                          "role_keys": keys, "roles": [role_label(k) for k in keys], "status": u.status})
    audit.record(db, actor_id=actor.id, action="client_users.view", organization_id=actor.organization.id, object_type="ClientUsers", request=request,
                 summary=f"Viewed the client users list ({len(users)} people across {len(orgs)} clients)")
    return {"users": users, "clients": [{"id": o.id, "name": o.name} for o in orgs], "departments": sorted(depts, key=str.lower),
            "roles": [{"value": str(r), "label": role_label(str(r))} for r in sorted(CLIENT_ROLES, key=lambda r: role_label(str(r)))]}


@router.post("/invitations/{user_id}/resend")
def resend_invitation(user_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    u = db.get(User, user_id)
    if u is None or u.deleted_at:
        raise NotFound()
    org = db.get(Organization, u.organization_id)
    if org.type == "futran":
        if not actor.is_futran:
            raise NotFound()
        authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
    else:
        authorize(db, actor, Action.MANAGE_CLIENT_USERS, org_id=org.id) if not actor.is_futran else _futran_resend_ok(db, actor, org)
    inv = invite_user(db, request.app.state.settings, actor.user, u)
    return {"ok": True, "expires_at": inv.expires_at.isoformat()}


def _futran_resend_ok(db: Session, actor: Actor, org: Organization) -> None:
    """Futran users may resend client invitations for clients they can see (client page, spec §13 screen 8)."""
    from app.policy.authorize import visible_org_ids

    allowed = visible_org_ids(db, actor)
    if allowed is not None and org.id not in allowed:
        raise NotFound()
    if not (actor.role_names & {"admin", "chief_auditor", "auditor", "engagement_manager"}):
        from app.core.errors import Forbidden

        raise Forbidden()


def _ai_settings(request: Request, s, db: Session) -> dict:
    """What law refresh and Draft with AI use: the connected AI provider, else ANTHROPIC_API_KEY (11-03 F1)."""
    from app.ai.client import ai_status, research_client_for

    st = ai_status(request.app.state, s, db)
    on = research_client_for(request.app.state, s, db) is not None
    return {"law_refresh_enabled": on, "claude_model": st["model"] if on else s.claude_model,
            "ai_label": f"{st['provider_label']} · {st['model']}" if on and st["source"] in ("connection", "environment") else ("Demonstration model" if on else None)}


@router.get("/admin/settings")
def platform_settings(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_FUTRAN_USERS)
    s = request.app.state.settings
    return {
        "test_mode": s.test_mode,
        "mfa_required": s.mfa_required,
        "email_mode": s.email_mode,
        "smtp_host": s.smtp_host,
        "data_region": s.data_region_label,
        **_ai_settings(request, s, db),
        "session_idle_min": s.session_idle_min,
        "session_max_hours": s.session_max_hours,
        "retention_years_default": s.retention_years_default,
        "virus_scan": s.virus_scan,
        "max_upload_mb": s.max_upload_mb,
        "base_url": s.base_url,
    }
