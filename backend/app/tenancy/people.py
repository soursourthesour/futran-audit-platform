"""Client departments, users and role holders (spec §4.2, §12, screen 10b). Used by the Client Admin and CAICO."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Invalid, NotFound
from app.documents.csvsafe import to_csv
from app.engagements.models import ClientContact, Engagement
from app.initiation.models import PackageDocument
from app.initiation.service import current_package
from app.invitations.service import invite_user
from app.notifications.service import futran_team, notify
from app.policy.roles import CLIENT_ROLES, ROLE_LABELS, SIGN_OFF_ROLES
from app.tenancy.csv_import import DEPARTMENT_ROLES, EMAIL, parse_department_csv, parse_user_csv
from app.tenancy.models import Department, Organization, RoleAssignment, User
from app.tenancy.service import assign_role, create_department, create_user, find_user_by_email, roles_of

CLIENT_ROLE_KEYS = {r.value for r in CLIENT_ROLES}
SIGN_OFF_KEYS = {r.value for r in SIGN_OFF_ROLES}


def current_engagement(db: Session, org: Organization) -> Engagement | None:
    return db.scalar(
        select(Engagement)
        .where(Engagement.client_id == org.id, Engagement.deleted_at.is_(None), Engagement.status.not_in(["draft", "pending_approval"]))
        .order_by(Engagement.created_at.desc())
        .limit(1)
    )


def departments(db: Session, org: Organization) -> list[Department]:
    return list(db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None)).order_by(Department.name)))


def _mark_item(db: Session, e: Engagement | None, item: int, actor: User) -> None:
    pkg = current_package(db, e) if e else None
    if pkg is None:
        return
    doc = db.scalar(select(PackageDocument).where(PackageDocument.package_id == pkg.id, PackageDocument.item == item))
    if doc is not None and doc.completed_at is None:
        doc.completed_at, doc.completed_by = utcnow(), actor.id


def advance_if_ready(db: Session, actor: User, e: Engagement | None) -> None:
    """Setup (stage 2) finishes on its own once every in-scope department has a lead."""
    from app.engagements.gates import advance_if_ready as advance

    if e is not None and e.stage == 2:
        advance(db, actor, e)


# ---- departments
def department_template(db: Session, org: Organization) -> str:
    existing = departments(db, org)
    if existing:
        rows = [[d.name, d.head_name, d.head_email, d.headcount] for d in existing]
    else:
        e = current_engagement(db, org)
        rows = [[name, "", "", ""] for name in ((e.wizard_state or {}).get("departments") or [] if e else [])]
    return to_csv(["department", "head_name", "head_email", "headcount"], rows)


def add_department(db: Session, actor: User, org: Organization, name: str, headcount: int | None = None) -> Department:
    name = " ".join((name or "").split())
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Enter the department name."}])
    d = create_department(db, org, name=name, actor_id=actor.id, headcount=headcount)
    audit.record(db, actor_id=actor.id, action="department.create", obj=d, summary=f"Added department {d.name}")
    return d


def import_departments(db: Session, actor: User, org: Organization, text: str) -> dict:
    result = parse_department_csv(text)
    have = {d.name.casefold(): d for d in departments(db, org)}
    n = 0
    for row in result.rows_ok:
        d = have.get(row["department"].casefold()) or add_department(db, actor, org, row["department"])
        d.head_name, d.head_email = row["head_name"] or d.head_name, row["head_email"] or d.head_email
        d.headcount = row["headcount"] if row["headcount"] is not None else d.headcount
        n += 1
    return {"imported": n, "errors": result.errors}


def confirm_departments(db: Session, actor: User, org: Organization) -> None:
    if not [d for d in departments(db, org) if d.in_scope]:
        raise Conflict("Add at least one department before confirming the list.")
    e = current_engagement(db, org)
    _mark_item(db, e, 4, actor)
    audit.record(db, actor_id=actor.id, action="department.confirm", obj=org, summary=f"Confirmed the department list ({len(departments(db, org))} departments)")
    advance_if_ready(db, actor, e)


# ---- users and roles
def _sync_contact(db: Session, e: Engagement | None, role: str, user: User | None) -> None:
    if e is None or role not in ("caico", "exec_sponsor", "dpo", "client_admin"):
        return
    c = db.scalar(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.contact_role == role, ClientContact.deleted_at.is_(None)))
    if c is None:
        c = ClientContact(organization_id=e.client_id, engagement_id=e.id, contact_role=role)
        db.add(c)
    c.user_id = user.id if user else None
    c.name, c.email = (user.name, user.email) if user else (None, None)
    if user is not None:
        c.not_appointed = False


def _notify_sign_off_role(db: Session, settings: Settings, actor: User, org: Organization, e: Engagement | None, user: User, role: str, assigned: bool) -> None:
    if role not in SIGN_OFF_KEYS or e is None:
        return
    verb = "named" if assigned else "removed"
    title = f"{org.name}: {user.name} {verb} as {ROLE_LABELS[role]}" if assigned else f"{org.name}: {user.name} removed as {ROLE_LABELS[role]}"
    notify(db, futran_team(db, e), "sign_off_role_changed", title, f"Changed by {actor.name}. Sign-off roles approve client sign-offs, so check any pending sign-offs.", f"/clients/{org.id}", engagement=e, settings=settings)


def add_user(db: Session, settings: Settings, actor: User, org: Organization, data: dict) -> User:
    """Create a client user (or add a role to an existing one in this organization) and invite them."""
    role = data.get("role")
    if role not in CLIENT_ROLE_KEYS:
        raise Invalid(errors=[{"field": "role", "message": "Choose a role."}])
    email = (data.get("email") or "").strip().lower()
    first, last = (data.get("first_name") or "").strip(), (data.get("last_name") or "").strip()
    errs = []
    if not first:
        errs.append({"field": "first_name", "message": "Enter the first name."})
    if not last:
        errs.append({"field": "last_name", "message": "Enter the last name."})
    if not EMAIL.match(email):
        errs.append({"field": "email", "message": "Enter a valid work email."})
    dept = None
    if data.get("department"):
        dept = next((d for d in departments(db, org) if d.name.casefold() == str(data["department"]).strip().casefold()), None)
        if dept is None:
            errs.append({"field": "department", "message": f"Department '{data['department']}' is not in the department list."})
    elif role in DEPARTMENT_ROLES:
        errs.append({"field": "department", "message": f"A {ROLE_LABELS[role]} needs a department."})
    if errs:
        raise Invalid(errors=errs)
    user = find_user_by_email(db, email)
    if user is not None and user.organization_id != org.id:
        raise Conflict("This email belongs to a user in another organization.")
    if user is None and db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise Conflict("This email belonged to a user who was removed. Ask Futran to restore the account.")
    created = user is None
    if created:
        user = create_user(db, org, name=f"{first} {last}", email=email, job_title=data.get("job_title") or None, actor_id=actor.id)
    elif data.get("job_title") and not user.job_title:
        user.job_title = data["job_title"]
    scope = ("department", dept.id) if role in DEPARTMENT_ROLES else ("org", None)
    already = any(r.role == role and r.scope_type == scope[0] and r.scope_id == scope[1] for r in roles_of(db, user.id))
    if not already:
        ra = assign_role(db, user, role, scope_type=scope[0], scope_id=scope[1], actor_id=actor.id)
        audit.record(db, actor_id=actor.id, action="role.assign", object_type="User", object_id=user.id, organization_id=org.id, after={"role": role, "department": dept.name if dept else None, "assignment_id": ra.id}, summary=f"Gave {user.name} the role {ROLE_LABELS[role]}{f' for {dept.name}' if dept else ''}")
    e = current_engagement(db, org)
    if role in SIGN_OFF_KEYS or role == "client_admin":
        _sync_contact(db, e, role, user)
    if not already:
        _notify_sign_off_role(db, settings, actor, org, e, user, role, assigned=True)
    if created:
        invite_user(db, settings, actor, user, template_key="client_invitation", extra_context={"client_message": None, "chief_name": actor.name})
    if dept is not None:
        _mark_item(db, e, 3, actor)
    advance_if_ready(db, actor, e)
    return user


def import_users(db: Session, settings: Settings, actor: User, org: Organization, text: str) -> dict:
    result = parse_user_csv(text, [d.name for d in departments(db, org)])
    errors = list(result.errors)
    imported = 0
    for row in result.rows_ok:
        try:
            with db.begin_nested():
                add_user(db, settings, actor, org, row)
            imported += 1
        except (Invalid, Conflict) as exc:
            errors.append({"row": None, "field": "email", "message": f"{row['email']}: {exc.detail if not exc.errors else exc.errors[0]['message']}"})
    return {"imported": imported, "errors": errors}


def remove_role(db: Session, settings: Settings, actor: User, org: Organization, user: User, assignment_id: str) -> None:
    ra = db.get(RoleAssignment, assignment_id)
    if ra is None or ra.user_id != user.id or ra.deleted_at is not None:
        raise NotFound()
    if ra.role == "caico":
        others = db.scalar(select(func.count()).select_from(RoleAssignment).where(RoleAssignment.organization_id == org.id, RoleAssignment.role == "caico", RoleAssignment.deleted_at.is_(None), RoleAssignment.id != ra.id))
        if not others:
            raise Conflict("Name another Chief AI Compliance Officer before removing this one.")
    ra.deleted_at, ra.updated_by = utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="role.remove", object_type="User", object_id=user.id, organization_id=org.id, before={"role": ra.role, "assignment_id": ra.id}, summary=f"Removed the role {ROLE_LABELS.get(ra.role, ra.role)} from {user.name}")
    e = current_engagement(db, org)
    if ra.role in SIGN_OFF_KEYS:
        holder = db.scalar(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(RoleAssignment.organization_id == org.id, RoleAssignment.role == ra.role, RoleAssignment.deleted_at.is_(None)).limit(1))
        _sync_contact(db, e, ra.role, holder)
    _notify_sign_off_role(db, settings, actor, org, e, user, ra.role, assigned=False)


def set_not_appointed(db: Session, actor: User, org: Organization, role: str, value: bool) -> None:
    if role not in ("exec_sponsor", "dpo"):
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise Conflict("There is no engagement in progress.")
    c = db.scalar(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.contact_role == role, ClientContact.deleted_at.is_(None)))
    if c is None:
        c = ClientContact(organization_id=org.id, engagement_id=e.id, contact_role=role)
        db.add(c)
    c.not_appointed = value
    audit.record(db, actor_id=actor.id, action="role_holder.not_appointed", obj=e, after={"role": role, "not_appointed": value}, summary=f"{ROLE_LABELS[role]} marked as {'not appointed' if value else 'to be appointed'}")


def role_holders(db: Session, org: Organization) -> dict:
    e = current_engagement(db, org)
    contacts = {c.contact_role: c for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.deleted_at.is_(None)))} if e else {}
    out = {}
    for role in ("caico", "exec_sponsor", "dpo"):
        holder = db.scalar(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(RoleAssignment.organization_id == org.id, RoleAssignment.role == role, RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None)).limit(1))
        c = contacts.get(role)
        out[role] = {"user": {"id": holder.id, "name": holder.name} if holder else None, "not_appointed": bool(c and c.not_appointed and holder is None)}
    return out
