"""Email groups (spec §26.3). Groups live only in the platform; they are never created in Microsoft 365 or Google.

Sources:
- manual: a list of people (and nested groups) someone keeps;
- rule: computed from roles, departments, offices, an engagement team or the governance committee;
- directory: members copied from a directory group at each sync (or, for "Employees · All", everyone the sync imports).

A group may include another group. Adding a nested group that would make a loop is rejected.
"""
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.mail.models import DirectoryGroup, DirectoryPerson, MailGroup, MailGroupMember
from app.mail.people import ensure_platform_people
from app.tenancy.models import Department, Organization, RoleAssignment, User

SOURCES = ("manual", "rule", "directory")
RULE_KINDS = ("all_users", "role", "dept_heads", "department", "office", "engagement_team", "committee", "all_people")

# The governance committee (R5) is owned by the register workstream. It registers a resolver here:
# resolver(db, org_id) -> list of user IDs or emails of committee members.
COMMITTEE_RESOLVERS: list[Callable[[Session, str], list[str]]] = []

CLIENT_DEFAULTS = [
    {"system_key": "ai_compliance_team", "name": "AIComplianceTeam", "purpose": "Runs the AI program", "source": "manual", "rule": None, "used_by": "Policies, findings"},
    {"system_key": "dept_heads", "name": "DeptHeads", "purpose": "All department heads", "source": "rule", "rule": {"kind": "dept_heads"}, "used_by": "Inventory approvals"},
    {"system_key": "all_employees", "name": "Employees · All", "purpose": "Everyone who must attest", "source": "directory", "rule": {"kind": "all_people"}, "used_by": "Attestation"},
    {"system_key": "committee", "name": "AI Governance Committee", "purpose": "Committee members (from company roles)", "source": "rule", "rule": {"kind": "committee"}, "used_by": "Committee papers"},
]
FUTRAN_DEFAULTS = [
    {"system_key": "audit_team", "name": "AuditTeam", "purpose": "All Futran roles", "source": "rule", "rule": {"kind": "all_users"}, "used_by": "All templates"},
    {"system_key": "chief_auditors", "name": "ChiefAuditors", "purpose": "Approvals and sign-offs", "source": "rule", "rule": {"kind": "role", "role": "chief_auditor"}, "used_by": "Package approval, findings"},
    {"system_key": "auditors", "name": "Auditors", "purpose": "Fieldwork", "source": "rule", "rule": {"kind": "role", "role": "auditor"}, "used_by": "Evidence requests"},
    {"system_key": "qa_reviewers", "name": "QAReviewers", "purpose": "Quality review", "source": "rule", "rule": {"kind": "role", "role": "qa_reviewer"}, "used_by": "Findings QA"},
    {"system_key": "futran_admins", "name": "FutranAdmins", "purpose": "Platform admin", "source": "rule", "rule": {"kind": "role", "role": "admin"}, "used_by": "System alerts"},
]


def _org(db: Session, org_id: str) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise NotFound()
    return org


def ensure_default_groups(db: Session, org_id: str) -> None:
    """Create the default groups once: four for a client; five role groups and one per engagement team for Futran."""
    org = _org(db, org_id)
    existing = {g.system_key for g in db.scalars(select(MailGroup).where(MailGroup.organization_id == org_id, MailGroup.system_key.is_not(None)))}
    owner = "futran" if org.type == "futran" else "client"
    for d in FUTRAN_DEFAULTS if owner == "futran" else CLIENT_DEFAULTS:
        if d["system_key"] not in existing:
            db.add(MailGroup(organization_id=org_id, owner=owner, owner_role="futran_admin", is_default=True, exclusions=[], **d))
    if owner == "futran":
        from app.engagements.models import Engagement

        for e in db.scalars(select(Engagement).where(Engagement.deleted_at.is_(None))):
            key = f"engagement:{e.id}"
            if key not in existing:
                client = db.get(Organization, e.client_id)
                db.add(MailGroup(organization_id=org_id, owner="futran", owner_role="futran_admin", is_default=True, system_key=key, engagement_id=e.id, exclusions=[],
                                 name=f"Engagement · {client.name if client else e.name}"[:120], purpose="Team on one client", source="rule",
                                 rule={"kind": "engagement_team", "engagement_id": e.id}, used_by="Client threads"))
    db.flush()


def default_group(db: Session, org_id: str, system_key: str) -> MailGroup:
    ensure_default_groups(db, org_id)
    return db.scalar(select(MailGroup).where(MailGroup.organization_id == org_id, MailGroup.system_key == system_key, MailGroup.deleted_at.is_(None)))


def _check_rule(source: str, rule: dict | None, directory_group_id: str | None) -> None:
    if source not in SOURCES:
        raise Invalid(errors=[{"field": "source", "message": "Choose where the members come from."}])
    if source == "rule":
        if not isinstance(rule, dict) or rule.get("kind") not in RULE_KINDS:
            raise Invalid(errors=[{"field": "rule", "message": "Choose the rule that picks the members."}])
        need = {"role": "role", "department": "department_id", "office": "office", "engagement_team": "engagement_id"}.get(rule["kind"])
        if need and not rule.get(need):
            raise Invalid(errors=[{"field": "rule", "message": "Complete the rule."}])


def create_group(db: Session, actor: User | None, org_id: str, *, name: str, source: str, purpose: str | None = None, rule: dict | None = None,
                 directory_group_id: str | None = None, department_id: str | None = None, exclude_on_leave: bool = True, used_by: str | None = None) -> MailGroup:
    org = _org(db, org_id)
    name = " ".join((name or "").split())[:120]
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Give the group a name."}])
    _check_rule(source, rule, directory_group_id)
    clash = db.scalar(select(MailGroup.id).where(MailGroup.organization_id == org_id, MailGroup.name == name, MailGroup.deleted_at.is_(None)))
    if clash:
        raise Conflict(f"There is already a group called {name}.")
    actor_futran = actor is not None and db.get(Organization, actor.organization_id).type == "futran"
    g = MailGroup(organization_id=org_id, owner="futran" if org.type == "futran" else "client", owner_role="futran_admin" if actor_futran else "client_admin",
                  name=name, purpose=(purpose or "").strip()[:300] or None, source=source, rule=rule if source != "manual" else None,
                  directory_group_id=directory_group_id if source == "directory" else None, department_id=department_id, exclude_on_leave=exclude_on_leave,
                  exclusions=[], used_by=used_by, created_by=actor.id if actor else None)
    db.add(g)
    db.flush()
    return g


def _nested_ids(db: Session, group_id: str) -> list[str]:
    return list(db.scalars(select(MailGroupMember.nested_group_id).where(MailGroupMember.group_id == group_id, MailGroupMember.nested_group_id.is_not(None),
                                                                         MailGroupMember.deleted_at.is_(None))))


def would_loop(db: Session, parent_id: str, child_id: str) -> bool:
    """True if `child` already includes `parent`, directly or further down (or they are the same group)."""
    stack, seen = [child_id], set()
    while stack:
        gid = stack.pop()
        if gid == parent_id:
            return True
        if gid in seen:
            continue
        seen.add(gid)
        stack.extend(_nested_ids(db, gid))
    return False


def add_member(db: Session, actor: User | None, group: MailGroup, *, person_id: str | None = None, nested_group_id: str | None = None) -> MailGroupMember:
    if group.source != "manual":
        raise Conflict("Only a list you keep can have members added. Rule and directory groups update themselves.")
    if bool(person_id) == bool(nested_group_id):
        raise Invalid(errors=[{"field": "member", "message": "Add one person or one group."}])
    if person_id:
        p = db.get(DirectoryPerson, person_id)
        if p is None or p.organization_id != group.organization_id or p.deleted_at is not None:
            raise NotFound()
        dup = select(MailGroupMember.id).where(MailGroupMember.group_id == group.id, MailGroupMember.person_id == person_id, MailGroupMember.deleted_at.is_(None))
    else:
        child = db.get(MailGroup, nested_group_id)
        if child is None or child.organization_id != group.organization_id or child.deleted_at is not None:
            raise NotFound()
        if would_loop(db, group.id, child.id):
            raise Conflict(f"{child.name} already includes {group.name}, so adding it would make a loop.")
        dup = select(MailGroupMember.id).where(MailGroupMember.group_id == group.id, MailGroupMember.nested_group_id == nested_group_id, MailGroupMember.deleted_at.is_(None))
    found = db.scalar(dup)
    if found:
        return db.get(MailGroupMember, found)
    m = MailGroupMember(organization_id=group.organization_id, group_id=group.id, person_id=person_id, nested_group_id=nested_group_id, added_by=actor.id if actor else None,
                        added_at=utcnow(), created_by=actor.id if actor else None)
    db.add(m)
    db.flush()
    return m


def remove_member(db: Session, group: MailGroup, member_id: str) -> None:
    m = db.get(MailGroupMember, member_id)
    if m is None or m.group_id != group.id or m.deleted_at is not None:
        raise NotFound()
    m.deleted_at = utcnow()


# ---- resolution
def _people_by_user(db: Session, org_id: str, user_ids: set[str]) -> list[DirectoryPerson]:
    if not user_ids:
        return []
    return list(db.scalars(select(DirectoryPerson).where(DirectoryPerson.organization_id == org_id, DirectoryPerson.user_id.in_(user_ids), DirectoryPerson.deleted_at.is_(None))))


def _active_user_ids(db: Session, org_id: str, role: str | None = None) -> set[str]:
    stmt = select(User.id).where(User.organization_id == org_id, User.deleted_at.is_(None), User.status == "active")
    if role:
        stmt = stmt.join(RoleAssignment, RoleAssignment.user_id == User.id).where(RoleAssignment.role == role, RoleAssignment.deleted_at.is_(None))
    return set(db.scalars(stmt))


def _rule_people(db: Session, g: MailGroup) -> list[DirectoryPerson]:
    rule = g.rule or {}
    kind = rule.get("kind")
    org_id = g.organization_id
    ensure_platform_people(db, org_id)
    base = select(DirectoryPerson).where(DirectoryPerson.organization_id == org_id, DirectoryPerson.deleted_at.is_(None))
    if kind == "all_users":
        return _people_by_user(db, org_id, _active_user_ids(db, org_id))
    if kind == "role":
        return _people_by_user(db, org_id, _active_user_ids(db, org_id, rule.get("role")))
    if kind == "dept_heads":
        ids = _active_user_ids(db, org_id, "dept_compliance_lead")
        depts = list(db.scalars(select(Department).where(Department.organization_id == org_id, Department.deleted_at.is_(None))))
        ids |= {d.head_user_id for d in depts if d.head_user_id}
        people = {p.id: p for p in _people_by_user(db, org_id, ids)}
        emails = {d.head_email.lower() for d in depts if d.head_email and not d.head_user_id}
        if emails:
            from sqlalchemy import func

            for p in db.scalars(base.where(func.lower(DirectoryPerson.email).in_(emails))):
                people[p.id] = p
        return list(people.values())
    if kind == "department":
        return list(db.scalars(base.where(DirectoryPerson.department_id == rule.get("department_id"))))
    if kind == "office":
        return [p for p in db.scalars(base) if (p.office or "").strip().lower() == str(rule.get("office", "")).strip().lower()]
    if kind == "engagement_team":
        from app.engagements.models import EngagementTeam

        ids = set(db.scalars(select(EngagementTeam.user_id).where(EngagementTeam.engagement_id == rule.get("engagement_id"), EngagementTeam.deleted_at.is_(None))))
        return _people_by_user(db, org_id, ids & _active_user_ids(db, org_id))
    if kind == "committee":
        refs = {r for resolver in COMMITTEE_RESOLVERS for r in resolver(db, org_id)}
        return [p for p in db.scalars(base) if p.user_id in refs or p.email in refs]
    if kind == "all_people":
        return [p for p in db.scalars(base) if not p.is_guest or (rule.get("include_guests"))]
    return []


def _directory_people(db: Session, g: MailGroup) -> list[DirectoryPerson]:
    if g.directory_group_id is None:
        return _rule_people(db, g) if (g.rule or {}).get("kind") == "all_people" else []
    dg = db.get(DirectoryGroup, g.directory_group_id)
    if dg is None:
        return []
    rows = db.scalars(select(DirectoryPerson).where(DirectoryPerson.organization_id == g.organization_id, DirectoryPerson.deleted_at.is_(None)))
    return [p for p in rows if dg.directory_id in (p.directory_group_ids or [])]


def resolve(db: Session, group: MailGroup, _seen: set[str] | None = None) -> dict[str, DirectoryPerson]:
    """Every person in the group, nested groups included, before leavers and people on leave are taken out. A loop that
    somehow exists is cut, never followed forever."""
    seen = _seen if _seen is not None else set()
    if group.id in seen or group.deleted_at is not None:
        return {}
    seen.add(group.id)
    out: dict[str, DirectoryPerson] = {}
    if group.source == "manual":
        for m in db.scalars(select(MailGroupMember).where(MailGroupMember.group_id == group.id, MailGroupMember.deleted_at.is_(None))):
            if m.person_id:
                p = db.get(DirectoryPerson, m.person_id)
                if p is not None and p.deleted_at is None:
                    out[p.id] = p
            elif m.nested_group_id:
                child = db.get(MailGroup, m.nested_group_id)
                if child is not None:
                    out.update(resolve(db, child, seen))
    elif group.source == "rule":
        out = {p.id: p for p in _rule_people(db, group)}
    else:
        out = {p.id: p for p in _directory_people(db, group)}
    for pid in group.exclusions or []:
        out.pop(pid, None)
    if group.exclude_on_leave:
        out = {k: p for k, p in out.items() if p.status != "on_leave"}
    return out


def active_members(db: Session, group: MailGroup) -> list[DirectoryPerson]:
    return sorted((p for p in resolve(db, group).values() if p.status == "active"), key=lambda p: p.name.lower())


def rule_text(db: Session, g: MailGroup) -> str:
    """How the members are chosen, in words (the "Who is in it" column)."""
    if g.source == "manual":
        return "Manual list"
    rule = g.rule or {}
    kind = rule.get("kind")
    if g.source == "directory":
        if g.directory_group_id:
            dg = db.get(DirectoryGroup, g.directory_group_id)
            return f"Directory group: {dg.name}" if dg else "Directory group"
        return "Everyone the directory sync imports"
    from app.policy.roles import role_label

    if kind == "all_users":
        return "Rule: every active user"
    if kind == "role":
        return f"Rule: role = {role_label(rule.get('role', ''))}"
    if kind == "dept_heads":
        return "Rule: role = Department Head"
    if kind == "department":
        d = db.get(Department, rule.get("department_id"))
        return f"Rule: department = {d.name if d else 'removed department'}"
    if kind == "office":
        return f"Rule: office = {rule.get('office')}"
    if kind == "engagement_team":
        return "Rule: engagement team"
    if kind == "committee":
        return "Rule: committee members"
    return "Rule: everyone"
