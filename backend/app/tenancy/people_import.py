"""Department and user uploads (11-03 review C4–C6): plan first, then apply all or nothing.

`plan_import` reads a CSV or workbook and works out, without writing anything, what would change: departments added
or updated (parent, head, headcount), people added or given new AI compliance roles, and every error and warning with
its sheet and row. `apply_import` re-plans the same file, refuses it while any error remains, and otherwise applies it
through the same functions the People screen uses, so the audit log and notifications are the same. Invitations and
notifications go out only after every row has been applied; any failure rolls the whole upload back."""
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, Invalid
from app.policy.roles import ROLE_LABELS
from app.tenancy import people as ppl
from app.tenancy.csv_import import (
    DEPARTMENT_ROLES, CsvResult, FileRefused, Table, is_department_table, is_user_table, issue, key, parse_departments, parse_users, read_file,
)
from app.tenancy.job_levels import job_level_label
from app.tenancy.models import Department, Organization, User
from app.tenancy.service import find_user_by_email, roles_of

NOTHING_IMPORTED = "Nothing was imported. Fix the rows listed and upload the file again."


def sheet_title(name: str) -> str:
    """The worksheet name the template gives a department (Excel allows 31 characters and no []:*?/\\)."""
    t = "".join(c for c in name if c not in '[]:*?/\\').strip()
    t = t.lstrip("=+-@'\t\r ").strip("'")  # never looks like a formula, never starts or ends with a quote
    return t[:31].strip().strip("'") or "Department"


@dataclass
class Plan:
    departments: list[dict] = field(default_factory=list)
    users: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    target: str | None = None

    @property
    def ready(self) -> bool:
        return not self.errors and bool(self.departments or self.users)

    def to_json(self) -> dict:
        order = lambda x: (x.get("sheet") or "", x.get("row") or 0)  # noqa: E731
        changes = [x for x in self.departments + self.users if x["action"] != "unchanged"]
        return {
            "target": self.target, "ready": self.ready,
            "departments": [{k: v for k, v in d.items() if not k.startswith("_")} for d in self.departments],
            "users": [{k: v for k, v in u.items() if not k.startswith("_")} for u in self.users],
            "errors": sorted(self.errors, key=order), "warnings": sorted(self.warnings, key=order),
            "summary": {
                "departments_added": sum(d["action"] == "add" for d in self.departments), "departments_updated": sum(d["action"] == "update" for d in self.departments),
                "users_added": sum(u["action"] == "add" for u in self.users), "users_updated": sum(u["action"] == "update" for u in self.users),
                "heads_set": sum(bool(d.get("_head_user")) and d.get("head_changes", False) for d in self.departments), "changes": len(changes),
            },
        }


def _role_scope_held(db: Session, user: User, role: str, dept: Department | None) -> bool:
    scope = ("department", dept.id) if role in DEPARTMENT_ROLES and dept else ("org", None)
    return any(r.role == role and r.scope_type == scope[0] and r.scope_id == scope[1] for r in roles_of(db, user.id))


def plan_import(db: Session, actor: User, org: Organization, filename: str, data: bytes, target: Department | None = None) -> Plan:
    p = Plan(target=target.name if target else None)
    try:
        tables = read_file(filename, data, p.errors)
    except FileRefused as exc:
        raise Invalid(str(exc), [issue(None, None, "file", str(exc))]) from exc
    if p.errors:
        return p
    existing = {key(d.name): d for d in ppl.departments(db, org)}
    e = ppl.current_engagement(db, org)
    locked = bool(e and e.stage > 2)

    dept_tables = [t for t in tables if is_department_table(t)]
    user_tables = [t for t in tables if is_user_table(t)]
    for t in tables:
        if t not in dept_tables and t not in user_tables and t.rows:
            p.warnings.append(issue(t.sheet, 1, "header", f"{'Sheet ' + repr(t.sheet) if t.sheet else 'This file'} was not read: its first row has neither a Department nor a Work email column."))
    if target is not None:
        if dept_tables:
            p.warnings.append(issue(dept_tables[0].sheet, None, "file", f"Only people for {target.name} are read from this file; the department list in it is not."))
            dept_tables = []
        if len(user_tables) > 1:
            mine = [t for t in user_tables if t.sheet and key(t.sheet) in (key(target.name), key(sheet_title(target.name)))]
            if len(mine) != 1:
                p.errors.append(issue(None, None, "file", f"This workbook has several sheets of people and none is named {sheet_title(target.name)}. Upload that department's sheet, or a CSV."))
                return p
            user_tables = mine
        if not user_tables:
            p.errors.append(issue(None, None, "file", "This file has no list of people. Use the user template's columns: Full name, Work email, Job title, Job level, AI compliance role."))
            return p
    if not dept_tables and not user_tables and not p.errors:
        p.errors.append(issue(None, None, "file", "This file has no department or user list in it. Download the template and copy your rows into it."))
        return p

    # ---- departments
    parsed = CsvResult()
    for t in dept_tables:
        parse_departments(t, parsed)
    p.errors += parsed.errors
    p.warnings += parsed.warnings
    in_file = {key(r["department"]): r for r in parsed.rows_ok}
    known = {k: d.name for k, d in existing.items()} | {k: r["department"] for k, r in in_file.items()}
    for r in parsed.rows_ok:
        d = existing.get(key(r["department"]))
        row = {"sheet": r.get("sheet"), "row": r["row"], "name": d.name if d else r["department"], "parent": None, "head": None, "headcount": r["headcount"], "changes": [], "_src": r, "_dept": d}
        if d is None:
            if locked:
                p.errors.append(issue(r.get("sheet"), r["row"], "department", f"{r['department']} is not in the department list, and department scope is fixed after setup. Ask your Futran engagement manager if a department was missed."))
                continue
            row["action"] = "add"
        if r.get("parent"):
            pk = key(r["parent"])
            if pk == key(r["department"]):
                p.errors.append(issue(r.get("sheet"), r["row"], "parent", "A department can't be its own parent."))
            elif pk not in known:
                p.errors.append(issue(r.get("sheet"), r["row"], "parent", f"Parent department '{r['parent']}' is not in this file or the department list."))
            else:
                row["parent"] = known[pk]
        if d is not None:
            cur_parent = next((x.name for x in existing.values() if x.id == d.parent_id), None) if d.parent_id else None
            if row["parent"] and row["parent"] != cur_parent:
                row["changes"].append("parent")
            if r["headcount"] is not None and r["headcount"] != d.headcount:
                row["changes"].append("headcount")
            if (r["head_name"] and r["head_name"] != d.head_name) or (r["head_email"] and r["head_email"] != d.head_email):
                row["changes"].append("head")
        p.departments.append(row)
    # a parent chain that loops back on itself
    parents = {key(x.name): key(next((y.name for y in existing.values() if y.id == x.parent_id), "")) for x in existing.values() if x.parent_id}
    parents |= {key(r["name"]): key(r["parent"]) for r in p.departments if r["parent"]}
    for r in p.departments:
        seen, k = set(), key(r["name"])
        while k in parents and k not in seen:
            seen.add(k)
            k = parents[k]
        if k in seen:
            p.errors.append(issue(r["sheet"], r["row"], "parent", f"{r['name']} would end up under itself. Check the parent departments."))

    # ---- people
    file_dept_names = [r["department"] for r in parsed.rows_ok]
    all_depts = list({key(n): n for n in [d.name for d in existing.values()] + file_dept_names}.values())
    seen: set[str] = set()
    users = CsvResult()
    for t in user_tables:
        default = target.name if target else None
        if default is None and t.sheet:
            default = next((n for n in all_depts if key(t.sheet) in (key(n), key(sheet_title(n)))), None)
        before = len(users.rows_ok)
        parse_users(t, users, all_depts, default, seen)
        if target is not None:
            for r in users.rows_ok[before:]:
                if r["department"] and key(r["department"]) != key(target.name):
                    users.errors.append(issue(r.get("sheet"), r["row"], "department", f"This row is for {r['department']}, but you are uploading people to {target.name}. Remove the row or upload it with that department."))
                    r["_skip"] = True
    p.errors += users.errors
    p.warnings += users.warnings
    for r in users.rows_ok:
        if r.get("_skip"):
            continue
        sheet, n = r.get("sheet"), r["row"]
        dept = existing.get(key(r["department"])) if r["department"] else None
        u = find_user_by_email(db, r["email"])
        if u is not None and u.organization_id != org.id:
            p.errors.append(issue(sheet, n, "email", ppl.CROSS_ORG_EMAIL))
            continue
        if u is None:
            removed_org = db.scalar(select(User.organization_id).where(func.lower(User.email) == r["email"]).limit(1))
            if removed_org == org.id:
                p.errors.append(issue(sheet, n, "email", "This email belonged to a user who was removed. Ask Futran to restore the account."))
                continue
            if removed_org is not None:
                p.errors.append(issue(sheet, n, "email", ppl.CROSS_ORG_EMAIL))
                continue
        if u is not None and u.id == actor.id:
            if not all(_role_scope_held(db, u, x, None) for x in r["roles"] if x in ppl.SIGN_OFF_KEYS):
                p.errors.append(issue(sheet, n, "role", "You can't give yourself a sign-off role. Ask another administrator or your Futran engagement manager."))
                continue
        row = {"sheet": sheet, "row": n, "name": r["name"], "email": r["email"], "department": r["department"], "job_title": r["job_title"],
               "job_level": job_level_label(r["job_level"]), "roles": [ROLE_LABELS[x] for x in r["roles"]], "changes": [], "_src": r}
        if u is None:
            row["action"] = "add"
        else:
            row["name"] = u.name
            new_roles = [x for x in r["roles"] if (dept is None and x in DEPARTMENT_ROLES) or not _role_scope_held(db, u, x, dept)]
            names = {d.id: d.name for d in existing.values()}
            cur = ppl.user_department(db, u, names)
            if new_roles:
                row["changes"].append("roles")
            if r["job_title"] and not u.job_title:
                row["changes"].append("job_title")
            if r["job_level"] and not u.job_level:
                row["changes"].append("job_level")
            elif r["job_level"] and r["job_level"] != u.job_level:
                p.warnings.append(issue(sheet, n, "job_level", f"{u.name} already has the job level {job_level_label(u.job_level)}; it was kept. Change it on the People screen."))
            if r["department"] and cur is None:
                row["changes"].append("department")
            elif r["department"] and key(cur) != key(r["department"]):
                p.warnings.append(issue(sheet, n, "department", f"{u.name} is already in {cur}. They were not moved; use Department on their row to move them."
                                         + (" The role in this file is added for " + r["department"] + "." if new_roles and DEPARTMENT_ROLES & set(new_roles) else "")))
        if "action" not in row:
            row["action"] = "update" if row["changes"] else "unchanged"
        p.users.append(row)

    # ---- heads of department: email first, then the exact full name, among this client's people and those this file adds
    pool = [(u.name, u.email) for u in db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None), User.status != "disabled"))]
    pool += [(u["name"], u["email"]) for u in p.users if u["action"] == "add"]
    for row in p.departments:
        value = row["_src"].get("head")
        d = row["_dept"]
        if not value:
            continue
        if d is not None and key(value) in (key(d.head_name or ""), key(d.head_email or "")):
            row["head"] = d.head_name or d.head_email  # the head the department already has
            continue
        if "@" in value:
            hits = list({em: (nm, em) for nm, em in pool if em.lower() == value.lower()}.values())
            if not hits:
                p.warnings.append(issue(row["sheet"], row["row"], "head", f"No one with the email {value} is on the user list, so the head of {row['name']} was not set. Add them as a user, or set the head on the People screen."))
                continue
        else:
            hits = list({em: (nm, em) for nm, em in pool if key(nm) == key(value)}.values())
            if len(hits) > 1:
                p.warnings.append(issue(row["sheet"], row["row"], "head", f"{len(hits)} people are called {value}, so the head of {row['name']} was not set. Give the head's work email instead."))
                continue
            if not hits:
                p.warnings.append(issue(row["sheet"], row["row"], "head", f"No one called {value} is on the user list, so the head of {row['name']} was not set. Check the spelling, give their work email, or add them as a user."))
                continue
        name, email = hits[0]
        row["head"], row["_head_user"] = name, (name, email)
        row["head_changes"] = d is None or (d.head_name, d.head_email) != (name, email)
        if d is not None and row["head_changes"] and "head" not in row["changes"]:
            row["changes"].append("head")
    for row in p.departments:
        if "action" not in row:
            row["action"] = "update" if row["changes"] else "unchanged"
    return p


def apply_import(db: Session, settings: Settings, actor: User, org: Organization, filename: str, data: bytes, target: Department | None = None) -> dict:
    """Apply the whole file or nothing. Raises Invalid (nothing written) while any row has an error."""
    p = plan_import(db, actor, org, filename, data, target)
    if p.errors:
        raise Invalid(NOTHING_IMPORTED, sorted(p.errors, key=lambda x: (x.get("sheet") or "", x.get("row") or 0)))
    if not p.departments and not p.users:
        raise Invalid("There is nothing to import in this file.")
    defer: list = []
    try:
        by_key = {key(d.name): d for d in ppl.departments(db, org)}
        for row in p.departments:
            if row["action"] == "add":
                by_key[key(row["name"])] = ppl.add_department(db, actor, org, row["name"], row["headcount"])
        for row in p.departments:
            d, r = by_key[key(row["name"])], row["_src"]
            body: dict = {}
            if row["parent"]:
                body["parent_id"] = by_key[key(row["parent"])].id
            if r["headcount"] is not None and row["action"] != "add":
                body["headcount"] = r["headcount"]
            if r["head_name"]:
                body["head_name"] = r["head_name"]
            if r["head_email"]:
                body["head_email"] = r["head_email"]
            if body:
                ppl.edit_department(db, actor, org, d, body)
        for row in p.users:
            r = row["_src"]
            for role in r["roles"]:
                ppl.add_user(db, settings, actor, org, {**r, "role": role, "department": r["department"] or ""}, defer=defer)
        for row in p.departments:  # heads last: they may be people this file added
            if row.get("_head_user") and row.get("head_changes"):
                name, email = row["_head_user"]
                ppl.edit_department(db, actor, org, by_key[key(row["name"])], {"head_name": name, "head_email": email})
        db.flush()
    except AppError as exc:
        raise Invalid(NOTHING_IMPORTED, exc.errors or [{"row": None, "field": "file", "message": exc.detail}]) from exc
    for send in defer:
        send()
    out = p.to_json()
    return {"imported": sum(1 for x in p.departments + p.users if x["action"] != "unchanged"), "summary": out["summary"], "warnings": out["warnings"],
            "invited": sum(1 for u in p.users if u["action"] == "add")}
