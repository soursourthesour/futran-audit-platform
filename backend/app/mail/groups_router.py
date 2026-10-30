"""E3 groups, E4 send to groups, E5 email and admin log, and templates. Permissions per spec §26.9."""
import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor, get_settings_dep
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.documents.csvsafe import to_csv
from app.engagements.models import Engagement
from app.mail import adminlog, connections as cx, directory, library, reminders, sending
from app.mail.groups import active_members, add_member, create_group, ensure_default_groups, remove_member, rule_text
from app.mail.models import (FUTRAN_OWNER, DirectoryGroup, DirectoryPerson, MailGroup, MailGroupMember, MailRecipient, MailReply, MailSend, MailTemplate, MailThread,
                             OutboxMessage)
from app.mail.people import person_out, upsert_person
from app.policy.actions import Action
from app.policy.authorize import assigned_engagement_ids, authorize, departments_for, sees_all_engagements
from app.tenancy.models import Department, Organization
from app.tenancy.people import current_engagement

router = APIRouter(prefix="/mail", tags=["email"])


def _may(db: Session, actor: Actor, action: Action, **kw) -> bool:
    try:
        authorize(db, actor, action, **kw)
        return True
    except (Forbidden, NotFound):
        return False


# ---- whose groups: Futran's (owner=futran) or one client's
def _org(db: Session, actor: Actor, client_id: str | None, owner: str | None) -> Organization:
    if owner == "futran":
        if not actor.is_futran:
            raise Forbidden()
        return actor.organization
    if not actor.is_futran:
        if client_id and client_id != actor.organization.id:
            raise NotFound()
        return actor.organization
    org = db.get(Organization, client_id) if client_id else None
    if org is None or org.type != "client":
        raise NotFound("Choose a client.")
    return org


def _view(db: Session, actor: Actor, org: Organization) -> None:
    if org.type == "futran":
        authorize(db, actor, Action.VIEW_FUTRAN_GROUPS)
    else:
        authorize(db, actor, Action.VIEW_CLIENT_GROUPS, org_id=org.id, list_view=True)


def _manage(db: Session, actor: Actor, org: Organization, department_id: str | None) -> None:
    if org.type == "futran":
        authorize(db, actor, Action.MANAGE_FUTRAN_GROUPS)
    else:
        authorize(db, actor, Action.MANAGE_CLIENT_GROUPS, org_id=org.id, department_id=department_id)


def _dept_scope(actor: Actor, action: Action) -> set[str] | None:
    """None: the whole organisation. A set: a Department Compliance Lead's own departments."""
    return None if actor.is_futran else departments_for(actor, action)


def _group(db: Session, actor: Actor, group_id: str) -> tuple[MailGroup, Organization]:
    g = db.get(MailGroup, group_id)
    if g is None or g.deleted_at is not None:
        raise NotFound()
    org = db.get(Organization, g.organization_id)
    if org.type == "futran":
        if not actor.is_futran:
            raise NotFound()
    else:
        if not actor.is_futran and actor.organization.id != org.id:
            raise NotFound()
    _view(db, actor, org)
    scope = _dept_scope(actor, Action.VIEW_CLIENT_GROUPS) if org.type == "client" else None
    if scope is not None and g.department_id not in scope:
        raise NotFound()
    return g, org


def group_out(db: Session, g: MailGroup, depts: dict | None = None, can_edit: bool = False) -> dict:
    members = active_members(db, g)
    labels = {"manual": "Manual list", "rule": "Rule", "directory": "Directory group"}
    return {"id": g.id, "name": g.name, "purpose": g.purpose, "source": g.source, "source_label": labels[g.source], "rule": g.rule, "rule_text": rule_text(db, g),
            "directory_group_id": g.directory_group_id, "member_count": len(members), "last_synced_at": g.last_synced_at.isoformat() if g.last_synced_at else None,
            "used_by": g.used_by, "is_default": g.is_default, "system_key": g.system_key, "owner_role": g.owner_role, "department_id": g.department_id,
            "department": (depts or {}).get(g.department_id), "exclude_on_leave": g.exclude_on_leave, "can_edit": can_edit}


def _depts(db: Session, org_id: str) -> dict:
    return {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == org_id, Department.deleted_at.is_(None)))}


@router.get("/groups")
def list_groups(client_id: str | None = None, owner: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, owner)
    _view(db, actor, org)
    ensure_default_groups(db, org.id)
    rows = list(db.scalars(select(MailGroup).where(MailGroup.organization_id == org.id, MailGroup.deleted_at.is_(None)).order_by(MailGroup.is_default.desc(), MailGroup.name)))
    scope = _dept_scope(actor, Action.VIEW_CLIENT_GROUPS) if org.type == "client" else None
    if scope is not None:
        rows = [g for g in rows if g.department_id in scope]
    depts = _depts(db, org.id)
    out = [group_out(db, g, depts, _may(db, actor, Action.MANAGE_FUTRAN_GROUPS) if org.type == "futran" else _may(db, actor, Action.MANAGE_CLIENT_GROUPS, org_id=org.id, department_id=g.department_id))
           for g in rows]
    conn = cx.org_connection(db, org)
    dgroups = list(db.scalars(select(DirectoryGroup).where(DirectoryGroup.organization_id == org.id, DirectoryGroup.deleted_at.is_(None)).order_by(DirectoryGroup.name)))
    return {"organization": {"id": org.id, "name": org.name, "type": org.type}, "groups": out,
            "can_create": _may(db, actor, Action.MANAGE_FUTRAN_GROUPS) if org.type == "futran" else (_may(db, actor, Action.MANAGE_CLIENT_GROUPS, org_id=org.id, list_view=True)),
            "my_departments": sorted(scope) if scope is not None else None, "departments": [{"id": k, "name": v} for k, v in sorted(depts.items(), key=lambda x: x[1])],
            "directory_connected": bool(conn and conn.status == "connected"), "directory_groups": [{"id": d.id, "directory_id": d.directory_id, "name": d.name, "member_count": d.member_count} for d in dgroups]}


@router.post("/groups")
def new_group(data: dict, client_id: str | None = None, owner: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, owner)
    dept = data.get("department_id") or None
    _manage(db, actor, org, dept)
    if dept and dept not in _depts(db, org.id):
        raise Invalid(errors=[{"field": "department_id", "message": "Choose one of your departments."}])
    g = create_group(db, actor.user, org.id, name=data.get("name", ""), source=data.get("source", "manual"), purpose=data.get("purpose"), rule=data.get("rule"),
                     directory_group_id=data.get("directory_group_id"), department_id=dept, exclude_on_leave=bool(data.get("exclude_on_leave", True)), used_by=data.get("used_by"))
    adminlog.write(db, organization_id=org.id, category="group", action="created", actor=actor.user, department_id=dept,
                   summary=f"Added group {g.name} ({rule_text(db, g)})")
    return group_out(db, g, _depts(db, org.id), True)


@router.get("/groups/{group_id}")
def get_group(group_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    g, org = _group(db, actor, group_id)
    depts = _depts(db, org.id)
    can = _may(db, actor, Action.MANAGE_FUTRAN_GROUPS) if org.type == "futran" else _may(db, actor, Action.MANAGE_CLIENT_GROUPS, org_id=org.id, department_id=g.department_id)
    out = group_out(db, g, depts, can)
    if g.source == "manual":
        members = []
        for m in db.scalars(select(MailGroupMember).where(MailGroupMember.group_id == g.id, MailGroupMember.deleted_at.is_(None)).order_by(MailGroupMember.added_at)):
            if m.person_id:
                p = db.get(DirectoryPerson, m.person_id)
                if p is not None:
                    members.append({"member_id": m.id, "kind": "person", **person_out(p, depts)})
            elif m.nested_group_id:
                child = db.get(MailGroup, m.nested_group_id)
                if child is not None and child.deleted_at is None:
                    members.append({"member_id": m.id, "kind": "group", "id": child.id, "name": child.name, "member_count": len(active_members(db, child))})
        out["members"] = sorted(members, key=lambda x: (x["kind"] != "group", x["name"].lower()))
    else:
        out["members"] = [{"member_id": None, "kind": "person", **person_out(p, depts)} for p in active_members(db, g)[:1000]]
    excl = [db.get(DirectoryPerson, pid) for pid in g.exclusions or []]
    out["exclusions"] = [person_out(p, depts) for p in excl if p is not None]
    return out


@router.patch("/groups/{group_id}")
def edit_group(group_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    g, org = _group(db, actor, group_id)
    _manage(db, actor, org, g.department_id)
    before = {"name": g.name, "purpose": g.purpose, "rule": g.rule, "exclude_on_leave": g.exclude_on_leave, "exclusions": list(g.exclusions or [])}
    if "name" in data:
        name = " ".join(str(data["name"] or "").split())[:120]
        if not name:
            raise Invalid(errors=[{"field": "name", "message": "Give the group a name."}])
        if g.is_default and name != g.name:
            raise Conflict("Default groups keep their names; change the purpose instead.")
        if db.scalar(select(MailGroup.id).where(MailGroup.organization_id == org.id, MailGroup.name == name, MailGroup.id != g.id, MailGroup.deleted_at.is_(None))):
            raise Conflict(f"There is already a group called {name}.")
        g.name = name
    if "purpose" in data:
        g.purpose = (str(data.get("purpose") or "").strip()[:300]) or None
    if "used_by" in data:
        g.used_by = (str(data.get("used_by") or "").strip()[:200]) or None
    if "exclude_on_leave" in data:
        g.exclude_on_leave = bool(data["exclude_on_leave"])
    if "rule" in data and g.source == "rule":
        from app.mail.groups import _check_rule

        _check_rule("rule", data["rule"], None)
        g.rule = data["rule"]
    if "exclusions" in data and isinstance(data["exclusions"], list):
        valid = set(db.scalars(select(DirectoryPerson.id).where(DirectoryPerson.organization_id == org.id, DirectoryPerson.id.in_([x for x in data["exclusions"] if isinstance(x, str)]))))
        g.exclusions = [x for x in data["exclusions"] if x in valid]
    after = {"name": g.name, "purpose": g.purpose, "rule": g.rule, "exclude_on_leave": g.exclude_on_leave, "exclusions": list(g.exclusions or [])}
    changed = [k for k in before if before[k] != after[k]]
    if changed:
        adminlog.write(db, organization_id=org.id, category="group", action="changed", actor=actor.user, department_id=g.department_id,
                       summary=f"{g.name}: " + ("rule changed to " + rule_text(db, g).removeprefix("Rule: ") if "rule" in changed else "changed " + ", ".join(c.replace("_", " ") for c in changed)))
    db.flush()
    return get_group(group_id, actor, db)


@router.delete("/groups/{group_id}")
def delete_group(group_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    g, org = _group(db, actor, group_id)
    _manage(db, actor, org, g.department_id)
    if g.is_default:
        raise Conflict("Default groups cannot be deleted.")
    g.deleted_at = utcnow()
    for m in db.scalars(select(MailGroupMember).where(MailGroupMember.nested_group_id == g.id, MailGroupMember.deleted_at.is_(None))):
        m.deleted_at = g.deleted_at
    adminlog.write(db, organization_id=org.id, category="group", action="deleted", actor=actor.user, department_id=g.department_id, summary=f"Deleted group {g.name}")
    return {"deleted": True}


@router.post("/groups/{group_id}/members")
def add_group_member(group_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    g, org = _group(db, actor, group_id)
    _manage(db, actor, org, g.department_id)
    person_id = data.get("person_id")
    if not person_id and data.get("email"):
        email = str(data["email"]).strip().lower()
        if "@" not in email or " " in email:
            raise Invalid(errors=[{"field": "email", "message": "Enter a valid email address."}])
        person_id = upsert_person(db, org.id, email=email, name=str(data.get("name") or email.split("@")[0]).strip()[:160],
                                  **({"department_id": data["department_id"]} if data.get("department_id") in _depts(db, org.id) else {})).id
    m = add_member(db, actor.user, g, person_id=person_id, nested_group_id=data.get("nested_group_id"))
    what = db.get(MailGroup, m.nested_group_id).name if m.nested_group_id else db.get(DirectoryPerson, m.person_id).name
    adminlog.write(db, organization_id=org.id, category="group", action="member_added", actor=actor.user, department_id=g.department_id, summary=f"{g.name}: added {what}")
    return get_group(group_id, actor, db)


@router.delete("/groups/{group_id}/members/{member_id}")
def remove_group_member(group_id: str, member_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    g, org = _group(db, actor, group_id)
    _manage(db, actor, org, g.department_id)
    remove_member(db, g, member_id)
    adminlog.write(db, organization_id=org.id, category="group", action="member_removed", actor=actor.user, department_id=g.department_id, summary=f"{g.name}: removed a member")
    return get_group(group_id, actor, db)


@router.post("/groups/{group_id}/import")
def import_members(group_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """CSV with columns email and name (a header row is optional)."""
    g, org = _group(db, actor, group_id)
    _manage(db, actor, org, g.department_id)
    rows = list(csv.reader(io.StringIO(str(data.get("csv") or ""))))
    added, errors = 0, []
    for i, row in enumerate(rows, start=1):
        if not row or (i == 1 and row[0].strip().lower() in ("email", "email address")):
            continue
        email = row[0].strip().lower()
        if "@" not in email:
            errors.append({"row": i, "field": "email", "message": f"Row {i}: “{row[0][:60]}” is not an email address."})
            continue
        p = upsert_person(db, org.id, email=email, name=(row[1].strip() if len(row) > 1 and row[1].strip() else email.split("@")[0])[:160])
        add_member(db, actor.user, g, person_id=p.id)
        added += 1
    adminlog.write(db, organization_id=org.id, category="group", action="imported", actor=actor.user, department_id=g.department_id, summary=f"{g.name}: imported {added} people from CSV")
    return {"added": added, "errors": errors}


@router.post("/groups/{group_id}/duplicate")
def duplicate_group(group_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    g, org = _group(db, actor, group_id)
    _manage(db, actor, org, g.department_id)
    n, name = 2, f"{g.name} (copy)"
    while db.scalar(select(MailGroup.id).where(MailGroup.organization_id == org.id, MailGroup.name == name, MailGroup.deleted_at.is_(None))):
        name, n = f"{g.name} (copy {n})", n + 1
    src = g.source if g.source != "directory" or g.directory_group_id else "rule"
    copy = create_group(db, actor.user, org.id, name=name, source=src, purpose=g.purpose, rule=g.rule, directory_group_id=g.directory_group_id,
                        department_id=g.department_id, exclude_on_leave=g.exclude_on_leave, used_by=g.used_by)
    copy.exclusions = list(g.exclusions or [])
    if g.source == "manual":
        for m in db.scalars(select(MailGroupMember).where(MailGroupMember.group_id == g.id, MailGroupMember.deleted_at.is_(None))):
            add_member(db, actor.user, copy, person_id=m.person_id, nested_group_id=m.nested_group_id)
    adminlog.write(db, organization_id=org.id, category="group", action="duplicated", actor=actor.user, department_id=g.department_id, summary=f"Duplicated {g.name} as {copy.name}")
    return group_out(db, copy, _depts(db, org.id), True)


@router.get("/groups/{group_id}/export")
def export_group(group_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    g, org = _group(db, actor, group_id)
    depts = _depts(db, org.id)
    rows = [[p.name, p.email, depts.get(p.department_id) or p.department or "", p.job_title or "", p.office or ""] for p in active_members(db, g)]
    name = "".join(c if c.isalnum() else "_" for c in g.name)[:60]
    return Response(to_csv(["Name", "Email", "Department", "Job title", "Office"], rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}_members.csv"'})


@router.post("/groups/sync")
def sync_groups(data: dict, client_id: str | None = None, owner: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db),
                settings=Depends(get_settings_dep)):
    """Sync now: run the directory sync (when connected) and refresh the chosen groups."""
    org = _org(db, actor, client_id, owner)
    _manage(db, actor, org, None) if org.type == "futran" else authorize(db, actor, Action.MANAGE_CLIENT_GROUPS, org_id=org.id, list_view=True)
    conn = cx.org_connection(db, org)
    ran = False
    if conn is not None and conn.status == "connected":
        ds = directory.for_connection(db, conn) or directory.configure(db, actor.user, conn, {})
        directory.run_directory_sync(db, settings, ds, actor=actor.user)
        ran = ds.status == "ok"
    now = utcnow()
    ids = [i for i in data.get("group_ids") or [] if isinstance(i, str)]
    for g in db.scalars(select(MailGroup).where(MailGroup.organization_id == org.id, MailGroup.id.in_(ids) if ids else MailGroup.source != "manual")):
        g.last_synced_at = now
    return {"directory_synced": ran, "synced_at": now.isoformat()}


@router.post("/groups/import-directory")
def import_directory_groups(data: dict, client_id: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, None)
    authorize(db, actor, Action.MANAGE_CLIENT_GROUPS, org_id=org.id)
    made = []
    for dg in db.scalars(select(DirectoryGroup).where(DirectoryGroup.organization_id == org.id, DirectoryGroup.id.in_([i for i in data.get("ids") or [] if isinstance(i, str)]))):
        if db.scalar(select(MailGroup.id).where(MailGroup.organization_id == org.id, MailGroup.directory_group_id == dg.id, MailGroup.deleted_at.is_(None))):
            continue
        name = dg.name if not db.scalar(select(MailGroup.id).where(MailGroup.organization_id == org.id, MailGroup.name == dg.name, MailGroup.deleted_at.is_(None))) else f"{dg.name} (directory)"
        g = create_group(db, actor.user, org.id, name=name, source="directory", directory_group_id=dg.id, purpose=f"Copied from the directory group {dg.name}")
        g.last_synced_at = dg.synced_at
        made.append(g.name)
    if made:
        adminlog.write(db, organization_id=org.id, category="group", action="imported_directory", actor=actor.user, summary=f"Added directory groups: {', '.join(made)[:400]}")
    return {"created": made}


@router.get("/people")
def search_people(q: str = "", client_id: str | None = None, owner: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, owner)
    if org.type == "futran":
        authorize(db, actor, Action.MANAGE_FUTRAN_GROUPS)
    else:
        authorize(db, actor, Action.MANAGE_CLIENT_GROUPS, org_id=org.id, list_view=True)
    from app.mail.people import ensure_platform_people

    ensure_platform_people(db, org.id)
    stmt = select(DirectoryPerson).where(DirectoryPerson.organization_id == org.id, DirectoryPerson.deleted_at.is_(None), DirectoryPerson.status != "left")
    term = q.strip().lower()
    if term:
        stmt = stmt.where(func.lower(DirectoryPerson.name).contains(term) | func.lower(DirectoryPerson.email).contains(term))
    scope = _dept_scope(actor, Action.MANAGE_CLIENT_GROUPS) if org.type == "client" else None
    if scope is not None:
        stmt = stmt.where(DirectoryPerson.department_id.in_(scope))
    depts = _depts(db, org.id)
    return [person_out(p, depts) for p in db.scalars(stmt.order_by(DirectoryPerson.name).limit(20))]


# ---- E4: sending
def _send_context(db: Session, actor: Actor, data: dict) -> dict:
    """Who may send what to whom. Futran sends engagement emails only, with Futran's templates."""
    org = _org(db, actor, data.get("client_id"), None)
    if actor.is_futran:
        e = current_engagement(db, org)
        if e is None:
            raise Conflict("This client has no engagement to send for.")
        authorize(db, actor, Action.SEND_TO_CLIENT_GROUPS, engagement_id=e.id)
        return {"org": org, "engagement": e, "scope": None}
    authorize(db, actor, Action.SEND_TO_CLIENT_GROUPS, org_id=org.id, list_view=True)
    scope = departments_for(actor, Action.SEND_TO_CLIENT_GROUPS)
    return {"org": org, "engagement": current_engagement(db, org), "scope": scope}


def _template_for(db: Session, actor: Actor, org: Organization, data: dict) -> MailTemplate:
    t = sending._template(db, org.id, data.get("template_key"), data.get("template_id"))
    if actor.is_futran and t.organization_id != FUTRAN_OWNER:
        raise Forbidden("Futran sends engagement emails with Futran's templates only.")
    return t


def _campaign(db: Session, t: MailTemplate, e: Engagement | None) -> tuple[str, str] | None:
    if t.purpose == "attestation" and e is not None:
        from app.attestation.service import current_campaign

        c = current_campaign(db, e)
        if c is not None:
            return ("attestation", c.id)
    return None


def _check_groups(db: Session, org: Organization, ids: list, scope: set[str] | None) -> list[str]:
    ids = [i for i in dict.fromkeys(ids or []) if isinstance(i, str)]
    for g in db.scalars(select(MailGroup).where(MailGroup.id.in_(ids))) if ids else []:
        if g.organization_id != org.id:
            raise NotFound("One of the groups no longer exists.")
        if scope is not None and g.department_id not in scope:
            raise Forbidden("You can send to your own department's groups only.")
    return ids


def _expand_args(db: Session, actor: Actor, data: dict) -> dict:
    ctx = _send_context(db, actor, data)
    t = _template_for(db, actor, ctx["org"], data)
    return {"ctx": ctx, "template": t, "group_ids": _check_groups(db, ctx["org"], data.get("group_ids"), ctx["scope"]),
            "exclude_group_ids": _check_groups(db, ctx["org"], data.get("exclude_group_ids"), None), "campaign": _campaign(db, t, ctx["engagement"])}


@router.get("/send/options")
def send_options(client_id: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    ctx = _send_context(db, actor, {"client_id": client_id})
    org, e = ctx["org"], ctx["engagement"]
    ensure_default_groups(db, org.id)
    templates = [t for t in library.available(db, org.id) if not actor.is_futran or t.organization_id == FUTRAN_OWNER]
    groups = list(db.scalars(select(MailGroup).where(MailGroup.organization_id == org.id, MailGroup.deleted_at.is_(None)).order_by(MailGroup.is_default.desc(), MailGroup.name)))
    if ctx["scope"] is not None:
        groups = [g for g in groups if g.department_id in ctx["scope"]]
    from app.mail.delivery import resolve_sender

    senders = [{"key": "organization", "label": resolve_sender(db, settings, org.id, prefer="organization").label}]
    uc = cx.user_connection(db, actor.user)
    if uc is not None and uc.status == "connected":
        senders.append({"key": "me", "label": f"{actor.user.name} · {uc.mailbox}"})
    offices = sorted({o for o in db.scalars(select(DirectoryPerson.office).where(DirectoryPerson.organization_id == org.id, DirectoryPerson.office.is_not(None)).distinct()) if o})
    depts = _depts(db, org.id)
    return {"organization": {"id": org.id, "name": org.name}, "engagement": {"id": e.id, "audit_ref": e.audit_ref, "name": e.name} if e else None,
            "templates": [library.template_out(t) for t in templates], "groups": [{"id": g.id, "name": g.name, "source": g.source, "member_count": len(active_members(db, g)),
                                                                                    "system_key": g.system_key} for g in groups],
            "senders": senders, "departments": [{"id": k, "name": v} for k, v in sorted(depts.items(), key=lambda x: x[1]) if ctx["scope"] is None or k in ctx["scope"]],
            "offices": offices, "defaults": {"link_days": settings.mail_link_days, "batch_size": settings.mail_bcc_batch_size, "reminder_days": [3, 7]},
            "pace_per_minute": settings.mail_pace_per_minute}


def _expansion(db: Session, a: dict, data: dict):
    return sending.preview_expansion(db, a["ctx"]["org"].id, a["group_ids"], exclude_group_ids=a["exclude_group_ids"], exclude_responded=bool(data.get("exclude_responded")),
                                     campaign=a["campaign"], department_ids=data.get("department_ids") or None, offices=data.get("offices") or None,
                                     department_scope=a["ctx"]["scope"])


def _sample(db: Session, a: dict, data: dict, person: DirectoryPerson | None, sender_label: str, actor: Actor) -> dict:
    t = a["template"]
    org = a["ctx"]["org"]
    fake = MailSend(organization_id=org.id, template_id=t.id, subject=data.get("subject") or t.subject, sent_by_name=sending._who(db, actor.user),
                    context={**({"_body": data["body"]} if data.get("body") else {})}, link_days=int(data.get("link_days") or 14))
    expires = utcnow() + timedelta(days=fake.link_days)
    link = "https://…/m/(personal link)" if (data.get("mode") or t.default_mode) == "personal" else "https://…/m/s/(shared link)"
    subject, html, text = sending.render(db, fake, person, link, expires, "FAP-0000")
    return {"from": sender_label, "to": person.name if person else "[Employee name]", "subject": subject, "html": html, "text": text}


@router.post("/send/preview")
def send_preview(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    a = _expand_args(db, actor, data)
    ex = _expansion(db, a, data)
    from app.mail.delivery import resolve_sender

    label = resolve_sender(db, settings, a["ctx"]["org"].id, prefer=data.get("sender") or "organization", user_id=actor.id).label
    depts = _depts(db, a["ctx"]["org"].id)
    return {"steps": ex.steps, "total": len(ex.people), "people": [person_out(p, depts) for p in ex.people[:200]], "message": _sample(db, a, data, ex.people[0] if ex.people else None, label, actor),
            "campaign": a["campaign"][0] if a["campaign"] else None}


@router.post("/send/people.csv")
def send_people_csv(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    a = _expand_args(db, actor, data)
    ex = _expansion(db, a, data)
    depts = _depts(db, a["ctx"]["org"].id)
    rows = [[p.name, p.email, depts.get(p.department_id) or p.department or "", p.office or ""] for p in ex.people]
    return Response(to_csv(["Name", "Email", "Department", "Office"], rows), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="recipients.csv"'})


@router.post("/send")
def send(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    a = _expand_args(db, actor, data)
    when = None
    if data.get("scheduled_at"):
        try:
            when = datetime.fromisoformat(str(data["scheduled_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as exc:
            raise Invalid(errors=[{"field": "scheduled_at", "message": "Choose when to send."}]) from exc
    e = a["ctx"]["engagement"]
    s = sending.send_to_groups(db, settings, actor.user, organization_id=a["ctx"]["org"].id, group_ids=a["group_ids"], template_id=a["template"].id,
                               engagement_id=e.id if e else None, exclude_group_ids=a["exclude_group_ids"], exclude_responded=bool(data.get("exclude_responded")),
                               campaign=a["campaign"], department_ids=data.get("department_ids") or None, offices=data.get("offices") or None,
                               department_scope=a["ctx"]["scope"], mode=data.get("mode"), reminder_days=data.get("reminder_days"), link_days=data.get("link_days"),
                               scheduled_at=when, subject=data.get("subject") or None, body=data.get("body") or None, sender=data.get("sender") or "organization")
    return send_out(db, s)


@router.post("/send/test")
def send_test_to_me(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    a = _expand_args(db, actor, {**data, "group_ids": data.get("group_ids") or []})
    from app.mail import delivery

    sender = delivery.resolve_sender(db, settings, a["ctx"]["org"].id, prefer=data.get("sender") or "organization", user_id=actor.id)
    me = DirectoryPerson(organization_id=a["ctx"]["org"].id, email=actor.user.email, name=actor.user.name, department_id=actor.user.department_id)
    sample = _sample(db, a, data, me, sender.label, actor)
    now = utcnow()
    s = MailSend(organization_id=a["ctx"]["org"].id, kind="test", mode="direct", template_id=a["template"].id, template_key=a["template"].key, template_name=a["template"].name,
                 subject=sample["subject"], channel=sender.channel, sender_label=sender.label, recipient_count=1, sent_by=actor.id, sent_by_name=actor.user.name, status="sent",
                 sent_at=now, retain_until=adminlog.retain_until(now), created_by=actor.id)
    db.add(s)
    db.flush()
    env = delivery.Envelope(to=[actor.user.email], subject=f"Test: {sample['subject']}", html=sample["html"], text=sample["text"])
    msg = delivery.record(db, organization_id=s.organization_id, env=env, stored=None, template_key=s.template_key, actor_id=actor.id, mail_send_id=s.id, channel=sender.channel)
    res = delivery.deliver(db, settings, sender, env, msg)
    db.add(MailRecipient(organization_id=s.organization_id, send_id=s.id, email=actor.user.email, status="sent" if res.ok else "bounced", error=res.error, attempts=1, last_event_at=now))
    return {"sent": res.ok, "to": actor.user.email}


# ---- E5: email and admin log
def _counts(db: Session, s: MailSend) -> dict:
    rows = list(db.scalars(select(MailRecipient.status).where(MailRecipient.send_id == s.id)))
    replies = db.scalar(select(func.count(MailReply.id)).join(MailThread, MailThread.id == MailReply.thread_id).where(MailThread.send_id == s.id, MailReply.kind == "reply")) or 0
    return {"recipients": len(rows), "delivered": sum(r in ("sent", "delivered", "opened", "completed") for r in rows), "bounced": sum(r == "bounced" for r in rows),
            "opened": sum(r in ("opened", "completed") for r in rows), "completed": sum(r == "completed" for r in rows), "queued": sum(r == "queued" for r in rows), "replies": replies}


def send_out(db: Session, s: MailSend) -> dict:
    batches = db.scalar(select(func.count(func.distinct(MailRecipient.batch_no))).where(MailRecipient.send_id == s.id)) if s.mode == "bcc" else None
    mode = {"personal": "Personal link", "bcc": f"BCC, {batches or 1} batch{'es' if (batches or 1) != 1 else ''}", "direct": "Direct"}.get(s.mode, s.mode)
    return {"id": s.id, "kind": s.kind, "sent_at": (s.sent_at or s.created_at).isoformat(), "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
            "template": s.template_name or s.template_key, "template_key": s.template_key, "groups": [g.get("name") for g in s.groups or [] if g.get("name")],
            "mode": s.mode, "mode_label": mode, "sent_by": s.sent_by_name or "System", "status": s.status, "channel": s.channel, "sender": s.sender_label,
            "subject": s.subject, "reminder_plan": s.reminder_plan, "parent_send_id": s.parent_send_id, "steps": s.expansion, "engagement_id": s.engagement_id, **_counts(db, s)}


def _log_scope(db: Session, actor: Actor, client_id: str | None):
    """(organisation IDs or None for all, engagement IDs or None, department IDs or None)."""
    if not actor.is_futran:
        if client_id and client_id != actor.organization.id:
            raise NotFound()
        authorize(db, actor, Action.VIEW_MAIL_LOG, org_id=actor.organization.id, list_view=True)
        return {actor.organization.id}, None, departments_for(actor, Action.VIEW_MAIL_LOG)
    authorize(db, actor, Action.VIEW_MAIL_LOG, org_id=client_id, list_view=True)
    if client_id:
        return {client_id}, (None if sees_all_engagements(actor) else assigned_engagement_ids(db, actor.id)), None
    if sees_all_engagements(actor):
        return None, None, None
    return None, assigned_engagement_ids(db, actor.id), None


def _visible_send(db: Session, actor: Actor, s: MailSend) -> bool:
    orgs, engs, depts = _log_scope(db, actor, None if actor.is_futran else actor.organization.id)
    if orgs is not None and s.organization_id not in orgs:
        return False
    if engs is not None and s.engagement_id not in engs:
        return False
    if depts is not None and not (set(s.department_scope or []) & depts or s.sent_by == actor.id):
        return False
    return True


@router.get("/log/sends")
def log_sends(client_id: str | None = None, template: str | None = None, group: str | None = None, days: int = 30, actor: Actor = Depends(current_actor),
              db: Session = Depends(get_db)):
    orgs, engs, depts = _log_scope(db, actor, client_id)
    stmt = select(MailSend).where(MailSend.kind != "test", MailSend.created_at >= utcnow() - timedelta(days=max(1, min(days, 3650))))
    if orgs is not None:
        stmt = stmt.where(MailSend.organization_id.in_(orgs))
    if engs is not None:
        stmt = stmt.where(MailSend.engagement_id.in_(engs))
    rows = list(db.scalars(stmt.order_by(MailSend.created_at.desc()).limit(500)))
    if depts is not None:
        rows = [s for s in rows if set(s.department_scope or []) & depts or s.sent_by == actor.id]
    if template:
        rows = [s for s in rows if s.template_key == template]
    if group:
        rows = [s for s in rows if any(g.get("id") == group for g in s.groups or [])]
    out = [send_out(db, s) for s in rows]
    return {"sends": out, "templates": sorted({(s["template_key"], s["template"]) for s in out if s["template_key"]}, key=lambda x: x[1] or ""),
            "groups": sorted({(g.get("id"), g.get("name")) for s in rows for g in s.groups or [] if g.get("id")}, key=lambda x: x[1] or "")}


def _send(db: Session, actor: Actor, send_id: str) -> MailSend:
    s = db.get(MailSend, send_id)
    if s is None or not _visible_send(db, actor, s):
        raise NotFound()
    return s


@router.get("/log/sends/{send_id}")
def log_send(send_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    s = _send(db, actor, send_id)
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.mail_send_id == s.id).order_by(OutboxMessage.created_at).limit(1))
    recips = list(db.scalars(select(MailRecipient).where(MailRecipient.send_id == s.id).order_by(MailRecipient.name, MailRecipient.email)))
    threads = [t.id for t in db.scalars(select(MailThread).where(MailThread.send_id == s.id))]
    replies = list(db.scalars(select(MailReply).where(MailReply.thread_id.in_(threads)).order_by(MailReply.received_at.desc()))) if threads else []
    ref = db.scalar(select(MailThread.subject_ref).where(MailThread.send_id == s.id))
    return {**send_out(db, s), "subject_ref": ref,
            "message": {"subject": msg.subject if msg else s.subject, "html": msg.body_html if msg else "", "to": msg.to if msg else [], "bcc_count": len(msg.bcc or []) if msg else 0},
            "recipients": [{"id": r.id, "name": r.name, "email": r.email, "status": r.status, "reminders_sent": r.reminders_sent, "opened_at": r.opened_at.isoformat() if r.opened_at else None,
                            "completed_at": r.completed_at.isoformat() if r.completed_at else None, "error": r.error, "out_of_office": r.out_of_office,
                            "link_expires_at": r.link_expires_at.isoformat() if r.link_expires_at else None} for r in recips],
            "replies": [{"id": x.id, "from": x.from_address, "received_at": x.received_at.isoformat(), "subject": x.subject, "snippet": x.snippet, "kind": x.kind} for x in replies],
            "can_remind": s.kind in ("group", "reminder") and s.mode in ("personal", "bcc")}


def _act_on_send(db: Session, actor: Actor, s: MailSend) -> None:
    if actor.is_futran:
        if s.engagement_id is None:
            raise Forbidden()
        authorize(db, actor, Action.SEND_TO_CLIENT_GROUPS, engagement_id=s.engagement_id)
    else:
        authorize(db, actor, Action.SEND_TO_CLIENT_GROUPS, org_id=s.organization_id, list_view=True)


@router.post("/log/sends/{send_id}/remind")
def log_remind(send_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    s = _send(db, actor, send_id)
    _act_on_send(db, actor, s)
    if s.kind not in ("group", "reminder"):
        raise Conflict("Reminders go only with emails sent to groups.")
    root = db.get(MailSend, s.parent_send_id) if s.parent_send_id else s
    targets = reminders.non_responders(db, root)
    rem = reminders.remind(db, settings, root, targets, utcnow(), actor=actor.user)
    return {"reminded": len(targets), "send_id": rem.id if rem else None}


@router.post("/log/sends/{send_id}/resend-bounced")
def log_resend_bounced(send_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    s = _send(db, actor, send_id)
    _act_on_send(db, actor, s)
    bounced = list(db.scalars(select(MailRecipient).where(MailRecipient.send_id == s.id, MailRecipient.status == "bounced")))
    for r in bounced:
        r.status, r.attempts, r.next_attempt_at, r.error = "queued", 0, None, None
    if bounced:
        s.status = "queued"
        sending.dispatch(db, settings, s)
        adminlog.write(db, organization_id=s.organization_id, category="send", action="resend_bounced", actor=actor.user, send_id=s.id, engagement_id=s.engagement_id,
                       summary=f"Sent {s.template_name or 'an email'} again to {len(bounced)} bounced {'address' if len(bounced) == 1 else 'addresses'}")
    return {"resent": len(bounced)}


@router.get("/log/sends/{send_id}/export")
def log_export(send_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    s = _send(db, actor, send_id)
    rows = [[r.name or "", r.email, r.status, r.reminders_sent, r.opened_at.strftime("%Y-%m-%d %H:%M") if r.opened_at else "", r.completed_at.strftime("%Y-%m-%d %H:%M") if r.completed_at else "",
             r.error or ""] for r in db.scalars(select(MailRecipient).where(MailRecipient.send_id == s.id).order_by(MailRecipient.email))]
    return Response(to_csv(["Name", "Email", "Status", "Reminders", "Opened link", "Completed", "Error"], rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="email_recipients.csv"'})


CATEGORY_LABELS = {"connection": "Email connection", "consent": "Approved access", "sender": "Changed sender", "group": "Changed group", "directory": "Directory sync",
                   "send": "Sent email", "template": "Changed template", "settings": "Changed settings"}


@router.get("/log/admin")
def log_admin(client_id: str | None = None, category: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    orgs, engs, depts = _log_scope(db, actor, client_id)
    if actor.is_futran and orgs is None and engs is not None:
        orgs = set(db.scalars(select(Engagement.client_id).where(Engagement.id.in_(engs)))) | {actor.organization.id}
    if actor.is_futran and client_id is None and orgs is not None and actor.organization.id not in orgs:
        orgs = orgs | {actor.organization.id}
    entries = adminlog.query(db, organization_ids=orgs, category=category, department_ids=depts)
    return {"entries": [{**adminlog.entry_out(e), "label": CATEGORY_LABELS.get(e.category, e.category)} for e in entries], "retention_years": adminlog.RETENTION_YEARS,
            "categories": [{"value": k, "label": v} for k, v in CATEGORY_LABELS.items()]}


# ---- templates
@router.get("/templates")
def list_templates(client_id: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.is_futran and not client_id:
        authorize(db, actor, Action.VIEW_FUTRAN_GROUPS)
        library.ensure_defaults(db)
        rows = library.available(db, None)
    else:
        org = _org(db, actor, client_id, None)
        _view(db, actor, org)
        rows = library.available(db, org.id)
    return [{**library.template_out(t), "can_edit": _may_edit(db, actor, t)} for t in rows]


def _may_edit(db: Session, actor: Actor, t: MailTemplate) -> bool:
    if t.organization_id == FUTRAN_OWNER:
        return actor.is_futran and _may(db, actor, Action.EDIT_MAIL_TEMPLATES)
    return not actor.is_futran and actor.organization.id == t.organization_id and _may(db, actor, Action.EDIT_MAIL_TEMPLATES, org_id=t.organization_id)


@router.post("/templates/{key}/copy")
def copy_template(key: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.is_futran:
        raise Forbidden("Clients copy and edit their own templates.")
    authorize(db, actor, Action.EDIT_MAIL_TEMPLATES, org_id=actor.organization.id)
    if key not in library.DEFAULT_KEYS:
        raise NotFound()
    t = library.copy_for_client(db, actor.id, actor.organization.id, key)
    adminlog.write(db, organization_id=actor.organization.id, category="template", action="copied", actor=actor.user, summary=f"Made an own copy of the template {t.name}")
    return library.template_out(t)


@router.put("/templates/{template_id}")
def edit_template(template_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    t = db.get(MailTemplate, template_id)
    if t is None or t.deleted_at is not None or (t.organization_id != FUTRAN_OWNER and (actor.is_futran or t.organization_id != actor.organization.id)):
        raise NotFound()
    if not _may_edit(db, actor, t):
        raise Forbidden("Futran's templates are edited by the Futran Admin; copy one to make your own version.")
    new = library.edit(db, actor.id, t, data)
    adminlog.write(db, organization_id=actor.organization.id if t.organization_id == FUTRAN_OWNER else t.organization_id, category="template", action="edited", actor=actor.user,
                   summary=f"Edited the template {new.name} (version {new.version})")
    return library.template_out(new)

