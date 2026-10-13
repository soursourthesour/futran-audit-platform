from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
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
from app.tenancy.models import Organization, RoleAssignment, User
from app.tenancy.service import assign_role, create_user, roles_of

router = APIRouter(tags=["admin"])


class UserIn(BaseModel):
    name: str
    email: str
    job_title: str | None = None
    roles: list[str]


class UserPatch(BaseModel):
    name: str | None = None
    job_title: str | None = None
    roles: list[str] | None = None
    status: str | None = None


def user_out(db: Session, u: User) -> dict:
    roles = sorted({r.role for r in roles_of(db, u.id)})
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "job_title": u.job_title,
        "status": u.status,
        "mfa_enabled": u.mfa_enabled,
        "roles": roles,
        "role_labels": [role_label(r) for r in roles],
    }


def _check_futran_roles(roles: list[str]) -> None:
    bad = [r for r in roles if r not in {x.value for x in FUTRAN_ROLES}]
    if bad or not roles:
        raise Invalid("Choose at least one Futran role.", [{"field": "roles", "message": f"Not a Futran role: {', '.join(bad)}" if bad else "Choose at least one role."}])


@router.get("/admin/users")
def list_futran_users(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_FUTRAN_USERS)
    users = db.scalars(select(User).where(User.organization_id == actor.organization.id, User.deleted_at.is_(None)).order_by(User.name))
    return [user_out(db, u) for u in users]


@router.post("/admin/users")
def create_futran_user(body: UserIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
    _check_futran_roles(body.roles)
    u = create_user(db, actor.organization, name=body.name, email=body.email, job_title=body.job_title, actor_id=actor.id)
    for r in body.roles:
        assign_role(db, u, r, actor_id=actor.id)
    audit.record(db, actor_id=actor.id, action="user.create", obj=u, after=column_snapshot(u) | {"roles": body.roles}, request=request, summary=f"Added {u.email}")
    invite_user(db, request.app.state.settings, actor.user, u)
    return user_out(db, u)


@router.patch("/admin/users/{user_id}")
def update_futran_user(user_id: str, body: UserPatch, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_FUTRAN_USERS)
    u = db.get(User, user_id)
    if u is None or u.organization_id != actor.organization.id or u.deleted_at:
        raise NotFound()
    before = column_snapshot(u) | {"roles": sorted(r.role for r in roles_of(db, u.id))}
    if body.status is not None:
        if body.status not in ("active", "disabled"):
            raise Invalid("Status must be active or disabled.")
        if u.id == actor.id and body.status == "disabled":
            raise Conflict("You cannot disable your own account.")
        if body.status == "active" and not u.password_hash:
            raise Conflict("This person has not accepted their invitation yet. Resend it instead.")
        u.status = body.status
    if body.name is not None:
        u.name = body.name.strip()
    if body.job_title is not None:
        u.job_title = body.job_title
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


@router.post("/invitations/{user_id}/resend")
def resend_invitation(user_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
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


@router.get("/admin/settings")
def platform_settings(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_FUTRAN_USERS)
    s = request.app.state.settings
    return {
        "test_mode": s.test_mode,
        "mfa_required": s.mfa_required,
        "email_mode": s.email_mode,
        "smtp_host": s.smtp_host,
        "data_region": s.data_region_label,
        "law_refresh_enabled": bool(s.anthropic_api_key),
        "claude_model": s.claude_model,
        "session_idle_min": s.session_idle_min,
        "session_max_hours": s.session_max_hours,
        "retention_years_default": s.retention_years_default,
        "virus_scan": s.virus_scan,
        "max_upload_mb": s.max_upload_mb,
        "base_url": s.base_url,
    }
