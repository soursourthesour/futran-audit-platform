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


def add_person_if_new(db: Session, org_id: str, *, email: str, name: str, **fields) -> DirectoryPerson:
    """The person with this email, unchanged; or a new manual person. Adding someone to a group by email or CSV never
    renames or moves a person who is already on record (the directory sync and the Client Admin own those details)."""
    p = find_person(db, org_id, email)
    if p is not None:
        return p
    u = db.scalar(select(User).where(User.organization_id == org_id, func.lower(User.email) == email.strip().lower(), User.deleted_at.is_(None)).limit(1))
    if u is not None:  # BUG-C04: someone with an account keeps the name on their account, not their email prefix
        name = u.name or name
        fields = {**fields, "user_id": u.id, **({"department_id": d} if (d := _user_department(db, u)) else {})}
    return upsert_person(db, org_id, email=email, name=name, **fields)


def _user_department(db: Session, u: User) -> str | None:
    """The user's department, or the department their department-scoped role is for (one user; the bulk path in
    ensure_platform_people reads these in one query)."""
    if u.department_id:
        return u.department_id
    from app.tenancy.models import RoleAssignment

    return db.scalar(select(RoleAssignment.scope_id).where(RoleAssignment.user_id == u.id, RoleAssignment.scope_type == "department",
                                                           RoleAssignment.deleted_at.is_(None)).order_by(RoleAssignment.created_at).limit(1))


# org_id -> fingerprint of the users, role assignments and people the last ensure_platform_people() left behind
_ENSURED: dict[str, tuple] = {}


def _fingerprint(db: Session, org_id: str) -> tuple:
    """Changes whenever a user, a role assignment or a person of the organisation is added, changed or removed (row
    counts and the latest updated_at of each, deleted rows included). One indexed aggregate statement."""
    from app.tenancy.models import RoleAssignment

    parts = []
    for model, join, where in ((User, None, User.organization_id == org_id), (DirectoryPerson, None, DirectoryPerson.organization_id == org_id),
                               (RoleAssignment, User, User.organization_id == org_id)):
        for fn in (func.count(model.id), func.max(model.updated_at)):
            stmt = select(fn).select_from(model)
            if join is not None:
                stmt = stmt.join(join, join.id == model.user_id)
            parts.append(stmt.where(where).scalar_subquery())
    return tuple(db.execute(select(*parts)).one())


def ensure_platform_people(db: Session, org_id: str) -> None:
    """Every active user with a login is also a person who can be emailed (their department comes with them).

    Set-based (load test BUG-V02): the organisation's people are read once, keyed by lower-case email, and only the
    missing ones are added. It does nothing when no user, role assignment or person has changed since the last run."""
    db.flush()
    if _ENSURED.get(org_id) == _fingerprint(db, org_id):
        return
    users = list(db.scalars(select(User).where(User.organization_id == org_id, User.deleted_at.is_(None), User.status != "disabled")))
    people: dict[str, DirectoryPerson] = {}
    for p in db.scalars(select(DirectoryPerson).where(DirectoryPerson.organization_id == org_id, DirectoryPerson.deleted_at.is_(None))
                        .order_by(DirectoryPerson.created_at, DirectoryPerson.id)):
        people.setdefault(p.email.strip().lower(), p)
    need_dept = [u.id for u in users if not u.department_id and (people.get(u.email.lower()) is None or people[u.email.lower()].department_id is None)]
    role_dept: dict[str, str] = {}
    if need_dept:
        from app.tenancy.models import RoleAssignment

        rows = db.execute(select(RoleAssignment.user_id, RoleAssignment.scope_id).join(User, User.id == RoleAssignment.user_id)
                          .where(User.organization_id == org_id, RoleAssignment.scope_type == "department", RoleAssignment.deleted_at.is_(None))
                          .order_by(RoleAssignment.created_at, RoleAssignment.id))
        wanted = set(need_dept)
        for uid, scope_id in rows:
            if uid in wanted and scope_id:
                role_dept.setdefault(uid, scope_id)
    for u in users:
        dept = u.department_id or role_dept.get(u.id)
        p = people.get(u.email.lower())
        if p is None:
            p = DirectoryPerson(organization_id=org_id, email=u.email.lower(), name=u.name, source="platform", status="active", user_id=u.id,
                                department_id=dept, job_title=u.job_title, office=u.location, directory_group_ids=[])
            db.add(p)
            people[u.email.lower()] = p
        else:
            if p.user_id is None:
                p.user_id = u.id
            if p.department_id is None and dept:
                p.department_id = dept
    db.flush()
    _ENSURED[org_id] = _fingerprint(db, org_id)


def person_out(p: DirectoryPerson, depts: dict | None = None) -> dict:
    return {"id": p.id, "name": p.name, "email": p.email, "department": (depts or {}).get(p.department_id) or p.department, "department_id": p.department_id,
            "job_title": p.job_title, "office": p.office, "status": p.status, "source": p.source, "has_login": p.user_id is not None}
