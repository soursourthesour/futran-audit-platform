from dataclasses import dataclass, field

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth.models import AuthSession
from app.auth.sessions import COOKIE_NAME, load_session
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.tenancy.models import Organization, RoleAssignment, User
from app.tenancy.service import roles_of

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Actor:
    user: User
    organization: Organization
    roles: list[RoleAssignment] = field(default_factory=list)
    session: AuthSession | None = None
    request: Request | None = None

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def is_futran(self) -> bool:
        return self.organization.type == "futran"

    @property
    def role_names(self) -> set[str]:
        return {r.role for r in self.roles}

    def has_role(self, role: str, scope_type: str | None = None, scope_id: str | None = None) -> bool:
        for r in self.roles:
            if r.role != role:
                continue
            if scope_type is None:
                return True
            if r.scope_type == scope_type and (scope_id is None or r.scope_id == scope_id):
                return True
        return False


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def _check_csrf(request: Request, s: AuthSession) -> None:
    if request.method in UNSAFE and request.headers.get("x-csrf-token") != s.csrf_token:
        raise Forbidden("Your session security token is missing or out of date. Reload the page and try again.")


def current_session(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    """A valid session, MFA not necessarily completed. Used by the MFA endpoints."""
    settings: Settings = request.app.state.settings
    s = load_session(db, request.cookies.get(COOKIE_NAME), settings)
    if s is None:
        raise Unauthorized()
    _check_csrf(request, s)
    return s


def build_actor(db: Session, s: AuthSession, request: Request | None = None) -> Actor:
    user = db.get(User, s.user_id)
    if user is None or user.status != "active" or user.deleted_at is not None:
        raise Unauthorized()
    org = db.get(Organization, user.organization_id)
    return Actor(user=user, organization=org, roles=roles_of(db, user.id), session=s, request=request)


def current_actor(request: Request, db: Session = Depends(get_db)) -> Actor:
    s = current_session(request, db)
    settings: Settings = request.app.state.settings
    if settings.mfa_required and not s.mfa_passed:
        raise Forbidden("mfa_required")
    return build_actor(db, s, request)
