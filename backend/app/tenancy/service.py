from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.core.ids import new_id
from app.tenancy.models import Department, Organization, RoleAssignment, User


def next_client_ref(db: Session) -> str:
    refs = db.scalars(select(Organization.client_ref).where(Organization.client_ref.is_not(None))).all()
    highest = max((int(r.split("-")[1]) for r in refs), default=0)
    return f"FUT-{highest + 1:04d}"


def create_organization(db: Session, *, name: str, type: str, actor_id: str | None = None, **fields) -> Organization:
    if type not in ("futran", "client"):
        raise ValueError(f"unknown organization type {type!r}")
    oid = new_id()
    org = Organization(id=oid, organization_id=oid, name=name, type=type, created_by=actor_id, updated_by=actor_id, **fields)
    if type == "client":
        org.client_ref = next_client_ref(db)
    db.add(org)
    db.flush()
    return org


def normalise_email(email: str) -> str:
    return email.strip().lower()


def find_user_by_email(db: Session, org_id: str, email: str) -> User | None:
    return db.scalar(
        select(User).where(
            User.organization_id == org_id,
            func.lower(User.email) == normalise_email(email),
            User.deleted_at.is_(None),
        )
    )


def create_user(db: Session, org: Organization, *, name: str, email: str, actor_id: str | None = None, **fields) -> User:
    email = normalise_email(email)
    if find_user_by_email(db, org.id, email):
        raise Conflict(f"A user with the email {email} already exists in {org.name}.")
    user = User(organization_id=org.id, name=name.strip(), email=email, created_by=actor_id, updated_by=actor_id, **fields)
    db.add(user)
    db.flush()
    return user


def assign_role(
    db: Session,
    user: User,
    role: str,
    scope_type: str = "org",
    scope_id: str | None = None,
    actor_id: str | None = None,
) -> RoleAssignment:
    existing = db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.user_id == user.id,
            RoleAssignment.role == role,
            RoleAssignment.scope_type == scope_type,
            RoleAssignment.scope_id.is_(scope_id) if scope_id is None else RoleAssignment.scope_id == scope_id,
            RoleAssignment.deleted_at.is_(None),
        )
    )
    if existing:
        return existing
    ra = RoleAssignment(
        organization_id=user.organization_id,
        user_id=user.id,
        role=role,
        scope_type=scope_type,
        scope_id=scope_id,
        created_by=actor_id,
    )
    db.add(ra)
    db.flush()
    return ra


def roles_of(db: Session, user_id: str) -> list[RoleAssignment]:
    return list(
        db.scalars(
            select(RoleAssignment).where(RoleAssignment.user_id == user_id, RoleAssignment.deleted_at.is_(None))
        )
    )


def get_org(db: Session, org_id: str) -> Organization:
    org = db.get(Organization, org_id)
    if not org or org.deleted_at:
        raise NotFound()
    return org


def create_department(db: Session, org: Organization, *, name: str, actor_id: str | None = None, **fields) -> Department:
    dup = db.scalar(
        select(Department).where(
            Department.organization_id == org.id,
            func.lower(Department.name) == name.strip().lower(),
            Department.deleted_at.is_(None),
        )
    )
    if dup:
        raise Conflict(f"The department {name} already exists.")
    d = Department(organization_id=org.id, name=name.strip(), created_by=actor_id, **fields)
    db.add(d)
    db.flush()
    return d
