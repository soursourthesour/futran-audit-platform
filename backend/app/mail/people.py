"""People who can receive email (DirectoryPerson): synced from the directory, users with a login, or added by hand."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.mail.models import DirectoryPerson
from app.tenancy.models import User

PERSON_FIELDS = ("name", "department", "department_id", "job_title", "manager_id", "office", "status", "is_guest", "user_id", "directory_id", "directory_group_ids")


def find_person(db: Session, org_id: str, email: str) -> DirectoryPerson | None:
    return db.scalar(select(DirectoryPerson).where(DirectoryPerson.organization_id == org_id, func.lower(DirectoryPerson.email) == email.strip().lower(),
                                                   DirectoryPerson.deleted_at.is_(None)).limit(1))


def upsert_person(db: Session, org_id: str, *, email: str, name: str, source: str = "manual", **fields) -> DirectoryPerson:
    """Add a person, or update the one with the same email in the organisation."""
    email = email.strip().lower()
    p = find_person(db, org_id, email)
    if p is None:
        p = DirectoryPerson(organization_id=org_id, email=email, name=name.strip() or email, source=source, status="active", directory_group_ids=[])
        db.add(p)
    else:
        p.name = name.strip() or p.name
        if source == "directory" and p.source != "directory":
            p.source = "directory"
    for k, v in fields.items():
        if k in PERSON_FIELDS:
            setattr(p, k, v)
    if p.status == "left" and p.left_at is None:
        p.left_at = utcnow()
    db.flush()
    return p


def _user_department(db: Session, u: User) -> str | None:
    """The user's department, or the department their department-scoped role is for."""
    if u.department_id:
        return u.department_id
    from app.tenancy.models import RoleAssignment

    return db.scalar(select(RoleAssignment.scope_id).where(RoleAssignment.user_id == u.id, RoleAssignment.scope_type == "department", RoleAssignment.deleted_at.is_(None)).limit(1))


def ensure_platform_people(db: Session, org_id: str) -> None:
    """Every active user with a login is also a person who can be emailed (their department comes with them)."""
    users = db.scalars(select(User).where(User.organization_id == org_id, User.deleted_at.is_(None), User.status != "disabled"))
    for u in users:
        p = find_person(db, org_id, u.email)
        if p is None:
            p = DirectoryPerson(organization_id=org_id, email=u.email.lower(), name=u.name, source="platform", status="active", user_id=u.id,
                                department_id=_user_department(db, u), job_title=u.job_title, office=u.location, directory_group_ids=[])
            db.add(p)
        else:
            if p.user_id is None:
                p.user_id = u.id
            if p.department_id is None:
                p.department_id = _user_department(db, u)
    db.flush()


def person_out(p: DirectoryPerson, depts: dict | None = None) -> dict:
    return {"id": p.id, "name": p.name, "email": p.email, "department": (depts or {}).get(p.department_id) or p.department, "department_id": p.department_id,
            "job_title": p.job_title, "office": p.office, "status": p.status, "source": p.source, "has_login": p.user_id is not None}
