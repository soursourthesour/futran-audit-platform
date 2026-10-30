"""Governance roles on register systems (spec §24.1, §24.2).

Which roles a system needs is computed from the laws on it: the union of the LawRoleMap rows of each law's current
version. Where laws differ, the stricter level and the earlier stage win and every source is listed (§25.4). Catalogue
roles no law maps are shown as recommended, citing the catalogue's main sources (NIST AI RMF, ISO 42001).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.errors import Forbidden, Invalid, NotFound
from app.register import service as svc
from app.register.models import ROLE_STATUSES, GovernanceRoleAssignment, RegisterSystem
from app.tenancy.models import User

STAGE_ORDER = {"program_setup": 0, "procurement": 1, "development": 2, "go_live": 3, "ongoing": 4, "yearly": 5}
STAGE_LABELS = {"program_setup": "Program set-up", "procurement": "Procurement", "development": "Development", "go_live": "Go-live", "ongoing": "Ongoing", "yearly": "Yearly"}
GATE_STAGES = {"program_setup", "procurement", "development", "go_live"}  # needed at or before go-live (§24.3)
STATUS_LABELS = {"assigned": "Assigned", "external": "External party", "no_such_person": "No such person", "pending_committee": "Pending committee", "not_applicable": "Not applicable"}
FILLED = {"assigned", "external", "not_applicable"}
BOUGHT = {"vendor", "shadow"}


def _catalog():
    from app.regmaster.models import RoleCatalog

    return RoleCatalog


def catalog_roles(db: Session) -> list:
    RoleCatalog = _catalog()
    return list(db.scalars(select(RoleCatalog).where(RoleCatalog.active.is_(True)).order_by(RoleCatalog.number)))


def catalog_role(db: Session, role_id: str | None) -> dict | None:
    """The catalogue role as a dict, or None."""
    if not role_id:
        return None
    r = db.get(_catalog(), role_id)
    if r is None:
        return None
    return {"id": r.id, "code": r.code, "number": r.number, "name": r.name, "level": r.level, "default_stage": r.default_stage, "description": r.description,
            "main_sources": r.main_sources, "extra_checks": r.extra_checks}


def current_version(db: Session, regulation_id: str):
    from app.regmaster.models import LawVersion

    reg = svc.current_regulation(db, regulation_id)
    if reg is None:
        return None, None
    v = db.get(LawVersion, reg.current_version_id) if getattr(reg, "current_version_id", None) else None
    if v is None:
        v = db.scalar(select(LawVersion).where(LawVersion.regulation_id == reg.id).order_by(LawVersion.version_no.desc()).limit(1))
    return reg, v


def developer_only(applies_to: list | None) -> bool:
    return bool(applies_to) and set(applies_to) <= {"developer"}


def _maps(db: Session, s: RegisterSystem) -> dict[str, list[tuple]]:
    """role_id -> [(map, regulation)] over the system's laws (active, or waiting for removal approval)."""
    from app.regmaster.models import LawRoleMap

    out: dict[str, list[tuple]] = {}
    for link in svc.law_links(db, s):
        reg, v = current_version(db, link.regulation_id)
        if v is None:
            continue
        for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == v.id)):
            if s.sourcing in BOUGHT and developer_only(m.applies_to):
                continue  # development-side duties sit with the vendor (§24.3)
            out.setdefault(m.role_id, []).append((m, reg))
    return out


def assignments(db: Session, org_id: str, system_id: str | None) -> dict[str, GovernanceRoleAssignment]:
    stmt = select(GovernanceRoleAssignment).where(GovernanceRoleAssignment.organization_id == org_id, GovernanceRoleAssignment.deleted_at.is_(None))
    stmt = stmt.where(GovernanceRoleAssignment.register_system_id == system_id) if system_id else stmt.where(GovernanceRoleAssignment.register_system_id.is_(None))
    return {a.role_id: a for a in db.scalars(stmt)}


def _person(db: Session, uid: str | None) -> dict | None:
    if not uid:
        return None
    u = db.get(User, uid)
    return {"id": u.id, "name": u.name, "job_title": u.job_title} if u else None


def assignment_out(db: Session, a: GovernanceRoleAssignment | None) -> dict | None:
    if a is None:
        return None
    return {"id": a.id, "status": a.status, "user": _person(db, a.user_id), "extra_users": [p for p in (_person(db, u) for u in a.extra_user_ids or []) if p],
            "external_party": a.external_party, "external_contact": a.external_contact, "backup_user": _person(db, a.backup_user_id),
            "target_date": a.target_date.isoformat() if a.target_date else None, "reason": a.reason, "effective_from": a.effective_from.isoformat() if a.effective_from else None,
            "training_completed": a.training_completed, "has_authority_to_override": a.has_authority_to_override, "override": a.override, "override_reason": a.override_reason,
            "evidence_ids": a.evidence_ids or [], "notes": a.notes, "updated_at": a.updated_at.isoformat() if a.updated_at else None}


def who(db: Session, a: GovernanceRoleAssignment | None) -> str:
    if a is None:
        return "Not answered"
    if a.status == "assigned":
        p = _person(db, a.user_id)
        extra = [x["name"] for x in (_person(db, u) for u in a.extra_user_ids or []) if x]
        return f"Assigned: {p['name'] if p else 'unknown'}" + (f" and {', '.join(extra)}" if extra else "")
    if a.status == "external":
        return f"External party: {a.external_party}"
    if a.status == "pending_committee":
        return f"Pending committee, target {a.target_date.isoformat() if a.target_date else 'not set'}"
    if a.status == "not_applicable":
        return f"Not applicable: {a.reason}"
    return STATUS_LABELS.get(a.status, a.status)


def role_rows(db: Session, s: RegisterSystem) -> list[dict]:
    """One row per catalogue role that applies to the system, with its requirement and its assignment."""
    roles = catalog_roles(db)
    maps = _maps(db, s)
    own = assignments(db, s.organization_id, s.id)
    company = assignments(db, s.organization_id, None)
    rows = []
    for r in roles:
        if r.level == "agent" and s.type != "agent":
            continue
        ms = maps.get(r.id, [])
        required = [m for m in ms if m[0].level == "required"]
        chosen = required or ms
        if chosen:
            stage = min((m[0].needed_by_stage or r.default_stage for m in chosen), key=lambda x: STAGE_ORDER.get(x, 9))
            sources = list(dict.fromkeys(reg.short_name for _, reg in required + [m for m in ms if m not in required]))  # every source, strictest first
            basis = "; ".join(dict.fromkeys(m[0].basis_text for m in ms if m[0].basis_text)) or None
        else:
            stage, sources, basis = r.default_stage, [r.main_sources] if r.main_sources else [], None
        requirement = "required" if required else "recommended"
        if r.level == "company":
            a = own.get(r.id) if own.get(r.id) is not None and own[r.id].override else company.get(r.id)
            inherited = a is not None and a.register_system_id is None
        else:
            a, inherited = own.get(r.id), False
        status = a.status if a else None
        rows.append({
            "role_id": r.id, "code": r.code, "number": r.number, "name": r.name, "description": r.description, "level": r.level, "extra_checks": r.extra_checks,
            "requirement": requirement, "needed_by": stage, "needed_by_label": STAGE_LABELS.get(stage, stage) if requirement == "required" else "Recommended",
            "required_by": sources, "basis": basis, "status": status, "status_label": STATUS_LABELS.get(status or "", "Not answered"),
            "filled": status in FILLED, "due_for_gate": requirement == "required" and stage in GATE_STAGES, "inherited": inherited,
            "assignment": assignment_out(db, a),
        })
    return rows


# ---- setting a role
def clean_assignment(db: Session, org_id: str, data: dict, role: dict) -> dict:
    errs: list[dict] = []
    status = data.get("status")
    if status not in ROLE_STATUSES:
        raise Invalid(errors=[{"field": "status", "message": "Say whether there is such a person."}])
    v: dict = {"status": status, "user_id": None, "external_party": None, "external_contact": None, "target_date": None, "reason": None, "extra_user_ids": []}
    if status == "assigned":
        v["user_id"] = svc._user(db, org_id, data.get("user_id"), "user_id", errs)
        if not v["user_id"] and not errs:
            errs.append({"field": "user_id", "message": "Choose the person."})
        v["backup_user_id"] = svc._user(db, org_id, data.get("backup_user_id"), "backup_user_id", errs)
        if v["backup_user_id"] and v["backup_user_id"] == v["user_id"]:
            errs.append({"field": "backup_user_id", "message": "The backup must be a different person."})
        v["effective_from"] = svc._date(data.get("effective_from"), "effective_from", errs)
    else:
        v["backup_user_id"] = None
    if status == "external":
        v["external_party"] = svc._text(data.get("external_party"), 200)
        v["external_contact"] = svc._text(data.get("external_contact"), 254)
        if not v["external_party"]:
            errs.append({"field": "external_party", "message": "Name the vendor, auditor firm or service provider."})
    if status == "pending_committee":
        v["target_date"] = svc._date(data.get("target_date"), "target_date", errs)
        if v["target_date"] is None and not any(e["field"] == "target_date" for e in errs):
            errs.append({"field": "target_date", "message": "Enter the date the committee should be formed by."})
    if status == "not_applicable":
        v["reason"] = svc._text(data.get("reason"), 1000)
        if not v["reason"]:
            errs.append({"field": "reason", "message": "Say why this role does not apply."})
    if role.get("extra_checks") == "oversight_confirmations" and status in ("assigned", "external"):
        for f in ("training_completed", "has_authority_to_override"):
            if f in data and data[f] is not None and not isinstance(data[f], bool):
                errs.append({"field": f, "message": "Answer yes or no."})
            v[f] = data.get(f) if isinstance(data.get(f), bool) else None
    else:
        v["training_completed"] = v["has_authority_to_override"] = None
    if "evidence_ids" in data:
        ids = data.get("evidence_ids") or []
        v["evidence_ids"] = [x for x in ids if isinstance(x, str) and svc._file(db, org_id, x, "evidence_ids", errs)]
    if "notes" in data:
        v["notes"] = str(data.get("notes") or "").strip()[:2000] or None
    if errs:
        raise Invalid(errors=errs)
    return v


def set_assignment(db: Session, actor: User, org_id: str, role: dict, system: RegisterSystem | None, v: dict, *, override: bool = False, override_reason: str | None = None,
                   reason: str | None = None, batch_id: str | None = None) -> GovernanceRoleAssignment:
    current = (assignments(db, org_id, system.id if system else None)).get(role["id"])
    before = who(db, current) if current is not None else None
    if current is None:
        current = GovernanceRoleAssignment(organization_id=org_id, register_system_id=system.id if system else None, role_id=role["id"], created_by=actor.id, extra_user_ids=[], evidence_ids=[])
        db.add(current)
    for k, val in v.items():
        setattr(current, k, val)
    current.override, current.override_reason = (override, override_reason) if system is not None and role["level"] == "company" else (False, None)
    current.updated_by = actor.id
    db.flush()
    after = who(db, current)
    if before != after:
        field = f"role:{role['code']}"
        if system is not None:
            svc.log_change(db, actor, system, field, before, after, reason or override_reason, entity="GovernanceRoleAssignment", entity_id=current.id, batch_id=batch_id, raw=True)
        else:
            from app.core.clock import utcnow
            from app.register.models import ChangeLog

            db.add(ChangeLog(organization_id=org_id, entity="GovernanceRoleAssignment", entity_id=current.id, register_system_id=None, field=field, old_value=before, new_value=after,
                             reason=reason, user_id=actor.id, at=utcnow()))
        audit.record(db, actor_id=actor.id, action="register.role_set", organization_id=org_id, object_type="GovernanceRoleAssignment", object_id=current.id,
                     before={"value": before}, after={"value": after, "system": system.reference if system else "company-wide"},
                     summary=f"{role['name']}: {after}" + (f" on {system.reference} {system.name}" if system else " (company-wide)"))
    return current


def row_for(db: Session, s: RegisterSystem, role_id: str) -> dict:
    row = next((r for r in role_rows(db, s) if r["role_id"] == role_id), None)
    if row is None:
        raise NotFound("This role does not apply to this system.")
    return row


def people_options(db: Session, org_id: str) -> list[dict]:
    from app.register.committee import COMMITTEE_ROLE_LABELS, committee_for, members
    from app.tenancy.models import Organization

    org = db.get(Organization, org_id)
    c = committee_for(db, org, create=False)
    on = {m.user_id: COMMITTEE_ROLE_LABELS.get(m.committee_role, m.committee_role) for m in (members(db, c) if c else []) if m.user_id}
    users = db.scalars(select(User).where(User.organization_id == org_id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name))
    return [{"id": u.id, "name": u.name, "job_title": u.job_title, "committee_role": on.get(u.id)} for u in users]


# ---- bulk (R2 section 3)
def plan_bulk_roles(db: Session, actor, systems: list[RegisterSystem], roles: list[dict]) -> list[dict]:
    """`actor` is the signed-in Actor (its roles decide Not applicable and override rights)."""
    """Validate the roles part of a bulk edit and find conflicts. One entry per system the role applies to."""
    if not isinstance(roles, list):
        raise Invalid(errors=[{"field": "roles", "message": "Choose the roles to set."}])
    plan = []
    for i, entry in enumerate(roles):
        if not isinstance(entry, dict):
            raise Invalid(errors=[{"field": f"roles.{i}", "message": "Choose the role."}])
        role = catalog_role(db, entry.get("role_id"))
        if role is None:
            raise Invalid(errors=[{"field": f"roles.{i}.role_id", "message": "Choose a governance role."}])
        if role["level"] == "company" and not entry.get("override"):
            raise Invalid(errors=[{"field": f"roles.{i}.role_id", "message": f"{role['name']} is company-wide. Set it under Governance roles, or override it for these systems."}])
        on_conflict = entry.get("on_conflict") or "keep"
        if on_conflict not in ("keep", "replace", "add"):
            raise Invalid(errors=[{"field": f"roles.{i}.on_conflict", "message": "Choose keep, replace or add."}])
        v = clean_assignment(db, systems[0].organization_id, entry, role)
        for s in systems:
            row = next((r for r in role_rows(db, s) if r["role_id"] == role["id"]), None)
            if row is None:
                continue
            check_role_rights(db, actor, s, role, row, v["status"], override=bool(entry.get("override")))
            cur = assignments(db, s.organization_id, s.id).get(role["id"])
            conflict = cur is not None and cur.status in ("assigned", "external") and not (v["status"] == "assigned" and cur.user_id == v["user_id"] and cur.status == "assigned")
            plan.append({"system_id": s.id, "system": s.name, "role_id": role["id"], "role": role["name"], "conflict": conflict, "current": (who(db, cur).split(": ", 1)[-1] if conflict else None),
                         "on_conflict": on_conflict, "_role": role, "_v": v, "_override": bool(entry.get("override")), "_override_reason": svc._text(entry.get("override_reason"), 1000)})
    return plan


def apply_bulk_roles(db: Session, actor: User, s: RegisterSystem, plan: list[dict], reason: str, batch_id: str) -> int:
    n = 0
    for p in plan:
        if p["conflict"] and p["on_conflict"] == "keep":
            continue
        if p["conflict"] and p["on_conflict"] == "add":
            cur = assignments(db, s.organization_id, s.id).get(p["role_id"])
            uid = p["_v"].get("user_id")
            if p["_v"]["status"] != "assigned" or not uid:
                raise Invalid(errors=[{"field": "roles", "message": "Only a named person can be added as a second person."}])
            if cur.status == "assigned" and uid != cur.user_id and uid not in (cur.extra_user_ids or []):
                before = who(db, cur)
                cur.extra_user_ids = [*(cur.extra_user_ids or []), uid]
                cur.updated_by = actor.id
                svc.log_change(db, actor, s, f"role:{p['_role']['code']}", before, who(db, cur), reason, entity="GovernanceRoleAssignment", entity_id=cur.id, batch_id=batch_id, raw=True)
                n += 1
            continue
        before = who(db, assignments(db, s.organization_id, s.id).get(p["role_id"]))
        a = set_assignment(db, actor, s.organization_id, p["_role"], s, dict(p["_v"]), override=p["_override"], override_reason=p["_override_reason"] or reason, reason=reason, batch_id=batch_id)
        n += int(who(db, a) != before)
    for p in plan:
        for k in [k for k in p if k.startswith("_")]:
            p.pop(k)
    return n


def check_role_rights(db: Session, actor, s: RegisterSystem | None, role: dict, row: dict | None, status: str, *, override: bool = False) -> None:
    """§24.7: per-system roles by the Department Head or the AI Compliance Officer; company-wide roles and overrides by the
    officer; Not applicable on a required role by the officer only."""
    from app.policy.actions import Action
    from app.register.router import check

    if role["level"] == "company":
        if s is None:
            from app.policy.authorize import authorize

            authorize(db, actor, Action.SET_COMPANY_ROLES, org_id=actor.organization.id)
        else:
            if not override:
                raise Forbidden("This role is set company-wide under Governance roles. The AI Compliance Officer can override it for this system.")
            check(db, actor, Action.SET_COMPANY_ROLES, s)
    else:
        check(db, actor, Action.FILL_SYSTEM_ROLES, s)
    if status == "not_applicable" and row is not None and row["requirement"] == "required":
        if s is None:
            from app.policy.authorize import authorize

            authorize(db, actor, Action.MARK_REQUIRED_ROLE_NA, org_id=actor.organization.id)
        else:
            check(db, actor, Action.MARK_REQUIRED_ROLE_NA, s)


def company_required_anywhere(db: Session, org_id: str, role_id: str) -> bool:
    for s in svc.systems_for(db, org_id, None):
        if s.stage == "retired":
            continue
        if any(r["role_id"] == role_id and r["requirement"] == "required" for r in role_rows(db, s)):
            return True
    return False


def company_page(db: Session, org_id: str) -> dict:
    from app.register.gate import gate_for, role_summary
    from app.tenancy.models import Department

    systems = [s for s in svc.systems_for(db, org_id, None) if s.stage != "retired"]
    per = {s.id: role_rows(db, s) for s in systems}
    company = assignments(db, org_id, None)
    rows = []
    for r in catalog_roles(db):
        if r.level != "company":
            continue
        required_on = [s for s in systems if any(x["role_id"] == r.id and x["requirement"] == "required" for x in per[s.id])]
        blocks = [s for s in required_on if s.stage == "ready_for_go_live" and any(x["role_id"] == r.id and x["due_for_gate"] and not x["filled"] for x in per[s.id])]
        overrides = sum(1 for s in systems if (assignments(db, org_id, s.id).get(r.id) or GovernanceRoleAssignment(override=False)).override)
        a = company.get(r.id)
        rows.append({"role_id": r.id, "code": r.code, "number": r.number, "name": r.name, "description": r.description, "main_sources": r.main_sources,
                     "required_by": sorted({reg for s in required_on for x in per[s.id] if x["role_id"] == r.id for reg in x["required_by"]}),
                     "status": a.status if a else None, "status_label": STATUS_LABELS.get(a.status if a else "", "Not answered"), "assignment": assignment_out(db, a),
                     "applies_to": len(required_on), "blocks_go_live_on": len(blocks), "overrides": overrides})
    summaries = {s.id: role_summary(db, s) for s in systems}
    gates = {s.id: gate_for(db, s, summaries[s.id]) for s in systems}
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == org_id, Department.deleted_at.is_(None)))}
    by: dict[str, dict] = {}
    for s in systems:
        name = depts.get(s.department_id) if s.department_id else ("Company-wide" if s.company_wide else "Not assigned")
        d = by.setdefault(name or "Not assigned", {"department": name or "Not assigned", "systems": 0, "no_such_person": 0, "pending": 0, "blocked": 0})
        d["systems"] += 1
        d["no_such_person"] += summaries[s.id]["no_such_person"]
        d["pending"] += summaries[s.id]["pending_committee"]
        d["blocked"] += int(gates[s.id]["state"] == "blocked")
    return {"rows": rows,
            "kpis": {"systems": len(systems), "departments": len({s.department_id for s in systems if s.department_id}),
                     "roles_no_person": sum(x["no_such_person"] for x in summaries.values()), "roles_pending": sum(x["pending_committee"] for x in summaries.values()),
                     "systems_blocked": sum(1 for g in gates.values() if g["state"] == "blocked")},
            "by_department": sorted(by.values(), key=lambda d: d["department"])}
