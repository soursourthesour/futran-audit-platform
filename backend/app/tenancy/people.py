"""Client departments, users and role holders (spec §4.2, §12, screen 10b). Used by the Client Admin and CAICO."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.documents.csvsafe import to_csv
from app.engagements.models import ClientContact, Engagement
from app.initiation.models import PackageDocument
from app.initiation.service import current_package
from app.invitations.service import invite_user
from app.notifications.service import futran_team, notify
from app.policy.roles import CLIENT_ROLES, ROLE_LABELS, SIGN_OFF_ROLES
from app.tenancy.csv_import import DEPARTMENT_ROLES, EMAIL, USER_HEADER
from app.tenancy.job_levels import job_level_label, parse_job_level
from app.tenancy.models import Department, Organization, RoleAssignment, User
from app.tenancy.service import assign_role, create_department, create_user, find_user_by_email, roles_of

CROSS_ORG_EMAIL = "This email can't be used. Check the address, or contact your Futran Chief Auditor."

CLIENT_ROLE_KEYS = {r.value for r in CLIENT_ROLES}
SIGN_OFF_KEYS = {r.value for r in SIGN_OFF_ROLES}


def current_engagement(db: Session, org: Organization) -> Engagement | None:
    return db.scalar(
        select(Engagement)
        .where(Engagement.client_id == org.id, Engagement.deleted_at.is_(None), Engagement.status.not_in(["draft", "pending_approval"]), Engagement.type != "incident_response")
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


def user_template(db: Session, org: Organization) -> str:
    """The user list CSV with two example rows, using this client's own department names."""
    names = [d.name for d in departments(db, org) if d.in_scope] or ["Human Resources"]
    return to_csv(
        USER_HEADER,
        [["Priya Shah", "priya.shah@example.com", names[0], "Head of department", "Department head", "Department Compliance Lead"],
         ["Tom Reyes", "tom.reyes@example.com", names[0], "Analyst", "Level 2", "Contributor"]],
    )


def scope_changed(db: Session, org: Organization) -> None:
    """The in-scope department list is fixed once setup ends; during setup any change needs the list confirmed again."""
    e = current_engagement(db, org)
    if e is None:
        return
    if e.stage > 2:
        raise Conflict("Department scope is fixed after setup. Ask your Futran engagement manager if a department was missed.")
    e.departments_confirmed_at = None


def add_department(db: Session, actor: User, org: Organization, name: str, headcount: int | None = None) -> Department:
    name = " ".join(str(name or "").split())
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Enter the department name."}])
    if len(name) > 120:
        raise Invalid(errors=[{"field": "name", "message": "Department name must be 120 characters or fewer."}])
    if any(x.name.casefold() == name.casefold() for x in departments(db, org)):
        raise Conflict(f"{name} is already in the department list.")
    scope_changed(db, org)
    d = create_department(db, org, name=name, actor_id=actor.id, headcount=headcount)
    audit.record(db, actor_id=actor.id, action="department.create", obj=d, summary=f"Added department {d.name}")
    return d


def confirm_departments(db: Session, settings: Settings | None, actor: User, org: Organization) -> None:
    in_scope = [d for d in departments(db, org) if d.in_scope]
    if not in_scope:
        raise Conflict("Add at least one department before confirming the list.")
    e = current_engagement(db, org)
    if e is not None and e.stage <= 2:
        e.departments_confirmed_at = utcnow()
    _mark_item(db, e, 4, actor)
    audit.record(db, actor_id=actor.id, action="department.confirm", obj=org, summary=f"Confirmed the department list ({len(in_scope)} in scope)")
    if e is not None:
        notify(db, futran_team(db, e), "departments_confirmed", f"{org.name} confirmed its department list", f"{len(in_scope)} departments in scope: {', '.join(d.name for d in in_scope)}.", f"/clients/{org.id}", engagement=e, settings=settings)
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


def active_holders(db: Session, org: Organization, role: str, exclude_assignment: str | None = None) -> list[User]:
    """Users who hold `role` today: active account, not deleted, assignment in date."""
    from app.core.clock import today

    d = today()
    q = (
        select(User, RoleAssignment.start_date, RoleAssignment.end_date)
        .join(RoleAssignment, RoleAssignment.user_id == User.id)
        .where(RoleAssignment.organization_id == org.id, RoleAssignment.role == role, RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None), User.status != "disabled")
    )
    if exclude_assignment:
        q = q.where(RoleAssignment.id != exclude_assignment)
    out: dict[str, User] = {}
    for u, start, end in db.execute(q):
        if (start is None or start <= d) and (end is None or end >= d):
            out[u.id] = u
    return list(out.values())


def _notify_sign_off_role(db: Session, settings: Settings, actor: User, org: Organization, e: Engagement | None, user: User, role: str, assigned: bool) -> None:
    if role not in SIGN_OFF_KEYS or e is None:
        return
    title = f"{org.name}: {user.name} {'named' if assigned else 'removed'} as {ROLE_LABELS[role]}"
    recipients = {u.id: u for u in [*futran_team(db, e), *active_holders(db, org, "caico")]}
    notify(db, list(recipients.values()), "sign_off_role_changed", title, f"Changed by {actor.name}. Sign-off roles approve client sign-offs, so check any pending sign-offs.", f"/clients/{org.id}", engagement=e, settings=settings)


def add_user(db: Session, settings: Settings, actor: User, org: Organization, data: dict, defer: list | None = None) -> User:
    """Create a client user (or add a role to an existing one in this organization) and invite them.

    With `defer`, the invitation and notifications are appended to it as callables instead of being sent, so an import
    can send them only once every row has been applied."""
    role = data.get("role")
    if not isinstance(role, str) or role not in CLIENT_ROLE_KEYS:
        raise Invalid(errors=[{"field": "role", "message": "Choose a role."}])
    email = str(data.get("email") or "").strip().lower()
    first, last = " ".join(str(data.get("first_name") or "").split()), " ".join(str(data.get("last_name") or "").split())
    errs = []
    if data.get("name"):  # one "Full name" instead of first and last
        if len(" ".join(str(data["name"]).split())) > 160:
            errs.append({"field": "name", "message": "Full name must be 160 characters or fewer."})
    else:
        if not first:
            errs.append({"field": "first_name", "message": "Enter the first name."})
        if not last:
            errs.append({"field": "last_name", "message": "Enter the last name."})
        if len(first) > 80 or len(last) > 80:
            errs.append({"field": "last_name" if len(last) > 80 else "first_name", "message": "Names must be 80 characters or fewer."})
    if not EMAIL.match(email) or len(email) > 254:
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
        raise Conflict(CROSS_ORG_EMAIL, [{"field": "email", "message": CROSS_ORG_EMAIL}])
    if user is None:
        removed_org = db.scalar(select(User.organization_id).where(func.lower(User.email) == email).limit(1))
        if removed_org == org.id:
            raise Conflict("This email belonged to a user who was removed. Ask Futran to restore the account.", [{"field": "email", "message": "This email belonged to a user who was removed. Ask Futran to restore the account."}])
        if removed_org is not None:
            raise Conflict(CROSS_ORG_EMAIL, [{"field": "email", "message": CROSS_ORG_EMAIL}])
    if user is not None and user.id == actor.id and role in SIGN_OFF_KEYS and not any(r.role == role and r.scope_type == "org" for r in roles_of(db, user.id)):
        raise Forbidden(f"You can't make yourself {ROLE_LABELS[role]}. Ask another administrator or your Futran engagement manager.")
    try:
        level = parse_job_level(data.get("job_level"))
    except ValueError as exc:
        raise Invalid(errors=[{"field": "job_level", "message": str(exc)}]) from exc
    created = user is None
    full_name = " ".join(str(data.get("name") or "").split()) or f"{first} {last}"
    if created:
        user = create_user(db, org, name=full_name, email=email, job_title=str(data.get("job_title") or "").strip()[:160] or None, actor_id=actor.id)
        user.job_level = level
    else:
        if data.get("job_title") and not user.job_title:
            user.job_title = str(data["job_title"]).strip()[:160]
        if level and not user.job_level:
            user.job_level = level
    names = {d.id: d.name for d in departments(db, org)}
    shown_before = None if created else user_department(db, user, names)
    scope = ("department", dept.id) if role in DEPARTMENT_ROLES else ("org", None)
    already = any(r.role == role and r.scope_type == scope[0] and r.scope_id == scope[1] for r in roles_of(db, user.id))
    if not already:
        ra = assign_role(db, user, role, scope_type=scope[0], scope_id=scope[1], actor_id=actor.id)
        audit.record(db, actor_id=actor.id, action="role.assign", object_type="User", object_id=user.id, organization_id=org.id, after={"role": role, "department": dept.name if dept else None, "assignment_id": ra.id}, summary=f"Gave {user.name} the role {ROLE_LABELS[role]}{f' for {dept.name}' if dept else ''}")
    if dept is not None and shown_before is None:
        user.department_id = dept.id  # the person's own department, also for org-wide roles
    db.flush()
    record_department_change(db, actor, org, user, shown_before, user_department(db, user, names))  # also when a department role moves them
    e = current_engagement(db, org)
    if role in SIGN_OFF_KEYS or role == "client_admin":
        _sync_contact(db, e, role, user)
    if not already:
        if defer is None:
            _notify_sign_off_role(db, settings, actor, org, e, user, role, assigned=True)
        else:
            defer.append(lambda u=user, r=role, e=e: _notify_sign_off_role(db, settings, actor, org, e, u, r, assigned=True))
    if created:
        def send(u: User = user) -> None:
            invite_user(db, settings, actor, u, template_key="client_invitation", extra_context={"client_message": None, "chief_name": actor.name})

        if defer is None:
            send()
        else:
            defer.append(send)
    if dept is not None:
        _mark_item(db, e, 3, actor)
    advance_if_ready(db, actor, e)
    return user


def remove_role(db: Session, settings: Settings, actor: User, org: Organization, user: User, assignment_id: str) -> None:
    ra = db.get(RoleAssignment, assignment_id)
    if ra is None or ra.user_id != user.id or ra.deleted_at is not None:
        raise NotFound()
    if ra.role == "caico":
        if not [u for u in active_holders(db, org, "caico", exclude_assignment=ra.id) if u.id != user.id]:
            raise Conflict("Name another Chief AI Compliance Officer before removing this one.")
    names = {d.id: d.name for d in departments(db, org)}
    shown_before = user_department(db, user, names)
    ra.deleted_at, ra.updated_by = utcnow(), actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="role.remove", object_type="User", object_id=user.id, organization_id=org.id, before={"role": ra.role, "assignment_id": ra.id}, summary=f"Removed the role {ROLE_LABELS.get(ra.role, ra.role)} from {user.name}")
    record_department_change(db, actor, org, user, shown_before, user_department(db, user, names))  # their department role was what placed them
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


# ---- People > Departments and People > Users grids
def _clean_name(value, field: str, label: str, limit: int) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise Invalid(errors=[{"field": field, "message": f"Enter the {label}."}])
    if len(name) > limit:
        raise Invalid(errors=[{"field": field, "message": f"The {label} must be {limit} characters or fewer."}])
    return name


def department_members(db: Session, d: Department) -> list[User]:
    """People whose role or record places them in this department."""
    by_role = select(RoleAssignment.user_id).where(RoleAssignment.scope_type == "department", RoleAssignment.scope_id == d.id, RoleAssignment.deleted_at.is_(None))
    return list(db.scalars(select(User).where(User.deleted_at.is_(None), (User.id.in_(by_role)) | (User.department_id == d.id)).order_by(User.name)))


def edit_department(db: Session, actor: User, org: Organization, d: Department, body: dict) -> Department:
    before = {"name": d.name, "in_scope": d.in_scope, "headcount": d.headcount, "head_name": d.head_name, "head_email": d.head_email, "parent_id": d.parent_id}
    errs = []
    parent = None
    if body.get("parent_id"):
        by_id = {x.id: x for x in departments(db, org)}
        parent = by_id.get(body["parent_id"])
        node, hops = parent, 0
        while node is not None and node.id != d.id and hops < 100:
            node, hops = by_id.get(node.parent_id) if node.parent_id else None, hops + 1
        if parent is None:
            errs.append({"field": "parent_id", "message": "Choose a department from the list."})
        elif node is not None:
            errs.append({"field": "parent_id", "message": "A department can't sit under itself or under one of its own sub-departments."})
    if "in_scope" in body and not isinstance(body["in_scope"], bool):
        errs.append({"field": "in_scope", "message": "Choose in scope or out of scope."})
    hc = None
    if "headcount" in body:
        hc = str(body["headcount"] if body["headcount"] is not None else "").strip()
        if hc and not (hc.isascii() and hc.isdecimal() and len(hc) < 8):
            errs.append({"field": "headcount", "message": "Headcount must be a whole number."})
    name = None
    if "name" in body:
        name = _clean_name(body["name"], "name", "department name", 120)
        if any(x.id != d.id and x.name.casefold() == name.casefold() for x in departments(db, org)):
            raise Conflict(f"{name} is already in the department list.", [{"field": "name", "message": f"{name} is already in the department list."}])
    head_email = None
    if "head_email" in body:
        head_email = str(body["head_email"] or "").strip().lower()
        if head_email and (not EMAIL.match(head_email) or len(head_email) > 254):
            errs.append({"field": "head_email", "message": "Enter a valid email for the department head."})
    if "head_name" in body and len(" ".join(str(body["head_name"] or "").split())) > 120:
        errs.append({"field": "head_name", "message": "The head's name must be 120 characters or fewer."})
    if errs:
        raise Invalid(errors=errs)
    if "in_scope" in body and body["in_scope"] != d.in_scope:
        scope_changed(db, org)
        d.in_scope = body["in_scope"]
    if hc is not None:
        d.headcount = int(hc) if hc else None
    if name is not None:
        d.name = name
    if "head_name" in body:
        d.head_name = " ".join(str(body["head_name"] or "").split()) or None
    if head_email is not None:
        d.head_email = head_email or None
    if "parent_id" in body:
        d.parent_id = parent.id if parent else None
    d.updated_by = actor.id
    after = {"name": d.name, "in_scope": d.in_scope, "headcount": d.headcount, "head_name": d.head_name, "head_email": d.head_email, "parent_id": d.parent_id}
    changed = {k: v for k, v in after.items() if before[k] != v}
    if changed:
        audit.record(db, actor_id=actor.id, action="department.edit", obj=d, before={k: before[k] for k in changed}, after=changed, summary=f"Edited department {d.name}")
    advance_if_ready(db, actor, current_engagement(db, org))
    return d


def delete_department(db: Session, actor: User, org: Organization, d: Department) -> None:
    """Departments can be deleted during setup only, and only when nothing refers to them."""
    from app.attestation.models import Attestation
    from app.inventory.models import UseCase
    from app.systems.models import AISystem

    e = current_engagement(db, org)
    if e is not None and e.stage > 2:
        raise Conflict("Departments can't be deleted after setup. Exclude the department from scope instead, or ask your Futran engagement manager.")
    members = department_members(db, d)
    if members:
        names = ", ".join(u.name for u in members[:3]) + (f" and {len(members) - 3} more" if len(members) > 3 else "")
        raise Conflict(f"{d.name} still has people in it ({names}). Move them to another department or remove them first.")
    for model, what in ((UseCase, "AI use cases"), (AISystem, "AI systems"), (Attestation, "attestation answers")):
        if db.scalar(select(func.count()).select_from(model).where(model.department_id == d.id, model.deleted_at.is_(None))):
            raise Conflict(f"{d.name} has {what} recorded against it, so it can't be deleted. Exclude it from scope instead.")
    scope_changed(db, org)
    d.deleted_at, d.updated_by = utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="department.delete", obj=d, before={"name": d.name, "in_scope": d.in_scope}, summary=f"Deleted department {d.name}")
    advance_if_ready(db, actor, e)


DEPARTMENT_CHANGE = "user.department_change"


def record_department_change(db: Session, actor: User, org: Organization, user: User, before: str | None, after: str | None) -> None:
    """One audit row per change of a person's department, by name, like the role.assign and role.remove rows."""
    if before == after:
        return
    summary = (f"Moved {user.name} from {before} to {after}" if before and after else f"Put {user.name} in {after}" if after else f"Took {user.name} out of {before}")
    audit.record(db, actor_id=actor.id, action=DEPARTMENT_CHANGE, object_type="User", object_id=user.id, organization_id=org.id,
                 before={"department": before}, after={"department": after}, summary=summary)


def change_history(db: Session, org: Organization, user: User | None = None, limit: int = 500) -> list[dict]:
    """Role and department changes, newest first, read from the audit log: for one person, or for the whole client."""
    from app.audit_log.models import AuditLog

    q = select(AuditLog).where(AuditLog.organization_id == org.id, AuditLog.action.in_(("role.assign", "role.remove", DEPARTMENT_CHANGE, "user.edit", "role_holder.not_appointed")))
    if user is not None:
        q = q.where(AuditLog.object_type == "User", AuditLog.object_id == user.id)
    rows = list(db.scalars(q.order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit * 2)))
    dept_names = dict(db.execute(select(Department.id, Department.name).where(Department.organization_id == org.id)).all())  # deleted ones too
    user_ids = {a.object_id for a in rows if a.object_type == "User"}
    people = dict(db.execute(select(User.id, User.name).where(User.id.in_(user_ids))).all()) if user_ids else {}
    now: dict[str, list[str]] = {}
    if user_ids:
        for uid, role in db.execute(select(RoleAssignment.user_id, RoleAssignment.role).where(RoleAssignment.user_id.in_(user_ids), RoleAssignment.deleted_at.is_(None))):
            now.setdefault(uid, []).append(ROLE_LABELS.get(role, role))
    out = []
    for a in rows:
        b, f = a.before or {}, a.after or {}
        ev = {"id": a.id, "at": a.at.isoformat(), "by": a.actor_name, "user_id": a.object_id if a.object_type == "User" else None,
              "name": people.get(a.object_id) if a.object_type == "User" else None, "summary": a.summary, "role": None, "department": None,
              "from": None, "to": None, "sign_off_role": False, "current_roles": sorted(set(now.get(a.object_id, []))) if a.object_type == "User" else []}
        if a.action in ("role.assign", "role.remove"):
            role = f.get("role") if a.action == "role.assign" else b.get("role")
            label = ROLE_LABELS.get(role, role) if role else None
            ev |= {"kind": "role", "change": "Role given" if a.action == "role.assign" else "Role removed", "role": label, "department": f.get("department") if a.action == "role.assign" else None,
                   "from": label if a.action == "role.remove" else None, "to": label if a.action == "role.assign" else None, "sign_off_role": role in SIGN_OFF_KEYS}
        elif a.action == DEPARTMENT_CHANGE:
            ev |= {"kind": "department", "change": "Department changed" if b.get("department") else "Department set", "department": f.get("department"),
                   "from": b.get("department"), "to": f.get("department")}
        elif a.action == "user.edit" and ("department_id" in f or "department" in f):  # rows written before department changes had their own action
            to = f.get("department") or dept_names.get(f.get("department_id"))
            ev |= {"kind": "department", "change": "Department changed", "department": to, "from": dept_names.get(b.get("department_id")), "to": to}
        elif a.action == "role_holder.not_appointed":
            role = f.get("role")
            ev |= {"kind": "role", "change": "Marked not appointed" if f.get("not_appointed") else "Marked to be appointed", "role": ROLE_LABELS.get(role, role), "sign_off_role": role in SIGN_OFF_KEYS}
        else:
            continue
        out.append(ev)
        if len(out) >= limit:
            break
    return out


def user_department(db: Session, user: User, names: dict[str, str]) -> str | None:
    """The department shown for a person: from their department role, else from their record."""
    for r in roles_of(db, user.id):
        if r.scope_type == "department" and r.scope_id in names:
            return names[r.scope_id]
    return names.get(user.department_id) if user.department_id else None


def edit_user(db: Session, actor: User, org: Organization, user: User, data: dict) -> User:
    """Change a person's name, job title, email (until they first sign in) or department. Roles change separately."""
    before = {"name": user.name, "job_title": user.job_title, "job_level": user.job_level, "email": user.email}
    names = {d.id: d.name for d in departments(db, org)}
    before_dept = user_department(db, user, names)
    errs = []
    name = email = dept = level = None
    if "name" in data:
        try:
            name = _clean_name(data["name"], "name", "name", 160)
        except Invalid as exc:
            errs.extend(exc.errors)
    if "email" in data:
        email = str(data["email"] or "").strip().lower()
        if not EMAIL.match(email) or len(email) > 254:
            errs.append({"field": "email", "message": "Enter a valid work email."})
    if "job_title" in data and len(str(data["job_title"] or "").strip()) > 160:
        errs.append({"field": "job_title", "message": "Job title must be 160 characters or fewer."})
    if "job_level" in data:
        try:
            level = parse_job_level(data["job_level"])
        except ValueError as exc:
            errs.append({"field": "job_level", "message": str(exc)})
    if data.get("department"):
        dept = next((d for d in departments(db, org) if d.name.casefold() == str(data["department"]).strip().casefold()), None)
        if dept is None:
            errs.append({"field": "department", "message": f"Department '{data['department']}' is not in the department list."})
    elif "department" in data and any(r.role in DEPARTMENT_ROLES for r in roles_of(db, user.id)):
        errs.append({"field": "department", "message": "A Department Compliance Lead or Contributor needs a department."})
    if errs:
        raise Invalid(errors=errs)
    if email is not None and email != user.email:
        if user.password_hash or user.status == "active":
            raise Conflict(f"{user.name} has already signed in, so their email can't be changed here. Ask your Futran engagement manager.", [{"field": "email", "message": "This person has already signed in."}])
        if db.scalar(select(User.id).where(func.lower(User.email) == email, User.id != user.id)):
            raise Conflict("Another account already uses this email.", [{"field": "email", "message": "Another account already uses this email."}])
        user.email = email
        from app.invitations.service import revoke_pending_invitations

        if revoke_pending_invitations(db, user.id):
            user.status = "invited"
    if name is not None:
        user.name = name
    if "job_title" in data:
        user.job_title = str(data["job_title"] or "").strip() or None
    if "job_level" in data:
        user.job_level = level
    if "department" in data:
        user.department_id = dept.id if dept else None
        for r in roles_of(db, user.id):
            if r.scope_type == "department" and dept is not None and r.scope_id != dept.id:
                r.scope_id, r.updated_by = dept.id, actor.id
    user.updated_by = actor.id
    after = {"name": user.name, "job_title": user.job_title, "job_level": user.job_level, "email": user.email}
    changed = {k: v for k, v in after.items() if before[k] != v}
    if changed:
        audit.record(db, actor_id=actor.id, action="user.edit", obj=user, before={k: before[k] for k in changed}, after=changed, summary=f"Edited {user.name}")
    if "department" in data:
        db.flush()
        after_dept = user_department(db, user, names)
        if after_dept != before_dept:
            record_department_change(db, actor, org, user, before_dept, after_dept)
    e = current_engagement(db, org)
    if e is not None and {"name", "email"} & changed.keys():  # keep the engagement's contact record in step
        for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.user_id == user.id, ClientContact.deleted_at.is_(None))):
            c.name, c.email = user.name, user.email
    advance_if_ready(db, actor, e)
    return user


def add_role(db: Session, settings: Settings, actor: User, org: Organization, user: User, role: str, department: str | None) -> User:
    parts = user.name.split(" ", 1)
    return add_user(db, settings, actor, org, {"first_name": parts[0], "last_name": parts[1] if len(parts) > 1 else parts[0], "email": user.email, "role": role, "department": department or ""})


def has_history(db: Session, user: User) -> bool:
    """True when the person has signed anything or done anything recorded in the audit log."""
    from app.audit_log.models import AuditLog
    from app.signoffs.models import Signature

    if db.scalar(select(func.count()).select_from(Signature).where(Signature.user_id == user.id)):
        return True
    return bool(db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.actor_id == user.id)))


def remove_user(db: Session, settings: Settings, actor: User, org: Organization, user: User) -> str:
    """Take a person off the user list. Anyone with history is deactivated so their records keep their name;
    someone who never signed in or did anything is soft-deleted. Returns "deactivated" or "removed"."""
    from app.invitations.service import revoke_pending_invitations

    if user.id == actor.id:
        raise Conflict("You can't remove yourself. Ask another administrator.")
    if user.deleted_at is not None:
        raise NotFound()
    roles = roles_of(db, user.id)
    if any(r.role == "caico" for r in roles) and not [u for u in active_holders(db, org, "caico") if u.id != user.id]:
        raise Conflict("Name another Chief AI Compliance Officer before removing this one.")
    e = current_engagement(db, org)
    revoke_pending_invitations(db, user.id)
    if has_history(db, user):
        before = user.status
        user.status, user.updated_by = "disabled", actor.id
        from app.auth.models import AuthSession

        for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))):
            s.revoked_at = utcnow()
        audit.record(db, actor_id=actor.id, action="user.deactivate", obj=user, before={"status": before}, after={"status": "disabled"}, summary=f"Deactivated {user.name}; their records are kept")
        result = "deactivated"
    else:
        now = utcnow()
        for r in roles:
            r.deleted_at, r.updated_by = now, actor.id
        user.deleted_at, user.updated_by = now, actor.id
        audit.record(db, actor_id=actor.id, action="user.remove", obj=user, before={"email": user.email, "roles": [r.role for r in roles]}, summary=f"Removed {user.name} from the user list")
        result = "removed"
    for r in roles:
        if r.role in SIGN_OFF_KEYS or r.role == "client_admin":
            holder = next(iter(u for u in active_holders(db, org, r.role) if u.id != user.id), None)
            _sync_contact(db, e, r.role, holder)
        if r.role in SIGN_OFF_KEYS:
            _notify_sign_off_role(db, settings, actor, org, e, user, r.role, assigned=False)
    advance_if_ready(db, actor, e)
    return result
