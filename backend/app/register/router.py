"""AI system register endpoints (client app, spec §24 and §27.2). The tenant is always the signed-in user's organization."""
from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, Invalid, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.register import service as svc
from app.register.models import ChangeLog, RegisterSystem, RegisterSystemLaw
from app.register.serialize import system_out
from app.systems.models import Vendor
from app.tenancy.models import Department, User

router = APIRouter(tags=["register"])


class ReasonIn(BaseModel):
    reason: str | None = None


class LawIn(BaseModel):
    regulation_id: str
    reason: str | None = None


class DecideIn(BaseModel):
    approve: bool
    comment: str | None = None


# ---- access
def client_org(actor: Actor):
    if actor.is_futran:
        raise NotFound()  # the register is a client screen; auditors read it through the audit system
    return actor.organization


def may(db: Session, actor: Actor, action: Action, s: RegisterSystem | None = None, *, department_id: str | None = None) -> bool:
    try:
        check(db, actor, action, s, department_id=department_id)
    except (Forbidden, NotFound):
        return False
    return True


def check(db: Session, actor: Actor, action: Action, s: RegisterSystem | None = None, *, department_id: str | None = None) -> None:
    """Authorize `action` on a system (or a department when creating). Company-wide systems need organization-wide rights."""
    org = client_org(actor)
    dept = s.department_id if s is not None else department_id
    if s is not None and s.company_wide and departments_for(actor, action) is not None:
        raise Forbidden("Company-wide tools are managed by the Chief AI Compliance Officer.")
    authorize(db, actor, action, org_id=org.id, department_id=dept)


def load(db: Session, actor: Actor, system_id: str) -> RegisterSystem:
    org = client_org(actor)
    s = db.get(RegisterSystem, system_id)
    if s is None or s.deleted_at is not None or s.organization_id != org.id:
        raise NotFound()
    if s.owner_user_id == actor.id:
        return s  # the system owner reads their own system (and signs its no-incident statement) whatever their role
    authorize(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    depts = departments_for(actor, Action.VIEW_REGISTER)
    if depts is not None and not s.company_wide and s.department_id not in depts:
        raise NotFound()
    return s


def check_edit_payload(db: Session, actor: Actor, data: dict, s: RegisterSystem | None) -> None:
    """Moving a system to another department, or making it company-wide, needs rights there too."""
    if "department_id" in data and data.get("department_id") and (s is None or data["department_id"] != s.department_id):
        check(db, actor, Action.EDIT_REGISTER, department_id=data["department_id"])
    if data.get("company_wide") and departments_for(actor, Action.EDIT_REGISTER) is not None:
        raise Forbidden("Only the Chief AI Compliance Officer or Client Admin can mark a tool company-wide.")


def kpis(db: Session, rows: list[dict]) -> dict:
    return {
        "systems": len(rows),
        "agents": sum(1 for r in rows if r["type"] == "agent"),
        "go_live_blocked": sum(1 for r in rows if r["gate"]["state"] == "blocked"),
        "roles_no_person": sum(r["roles"]["no_such_person"] for r in rows),
        "bias_overdue": sum(1 for r in rows if r["bias"]["overdue"]),
        "consent_missing": sum(1 for r in rows if r["consent"]["missing"]),
    }


def options(db: Session, actor: Actor) -> dict:
    org = client_org(actor)
    depts = db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None)).order_by(Department.name))
    users = db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name))
    vendors = db.scalars(select(Vendor).where(Vendor.organization_id == org.id, Vendor.deleted_at.is_(None)).order_by(Vendor.legal_name))
    edit_depts = departments_for(actor, Action.EDIT_REGISTER)
    return {
        "departments": [{"id": d.id, "name": d.name, "can_edit": edit_depts is None or d.id in edit_depts} for d in depts],
        "people": [{"id": u.id, "name": u.name, "job_title": u.job_title, "department_id": u.department_id} for u in users],
        "vendors": [{"id": v.id, "name": v.legal_name} for v in vendors],
    }


def capabilities(db: Session, actor: Actor) -> dict:
    org = client_org(actor)
    def has(a: Action) -> bool:
        try:
            authorize(db, actor, a, org_id=org.id, list_view=True)
            return True
        except (Forbidden, NotFound):
            return False
    return {
        "edit": has(Action.EDIT_REGISTER), "org_wide": departments_for(actor, Action.VIEW_REGISTER) is None, "import_inventory": has(Action.IMPORT_INVENTORY_TO_REGISTER),
        "add_law": has(Action.ADD_SYSTEM_LAW), "remove_law": has(Action.REMOVE_SYSTEM_LAW), "fill_roles": has(Action.FILL_SYSTEM_ROLES),
        "company_roles": has(Action.SET_COMPANY_ROLES), "approve_go_live": has(Action.APPROVE_GO_LIVE), "submit_go_live": has(Action.SUBMIT_GO_LIVE),
        "record_history": has(Action.RECORD_SYSTEM_HISTORY), "committee_members": has(Action.MANAGE_COMMITTEE_MEMBERS), "record_committee": has(Action.RECORD_COMMITTEE),
    }


# ---- grid and record
@router.get("/register")
def get_register(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    rows = [system_out(db, s, actor) for s in svc.systems_for(db, org.id, departments_for(actor, Action.VIEW_REGISTER))]
    return {"systems": rows, "kpis": kpis(db, [r for r in rows if r["stage"] != "retired"]), "can": capabilities(db, actor), **options(db, actor)}


@router.post("/register")
def post_register(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    if data.get("company_wide"):
        authorize(db, actor, Action.EDIT_REGISTER, org_id=org.id)
        check_edit_payload(db, actor, data, None)
    else:
        check(db, actor, Action.EDIT_REGISTER, department_id=data.get("department_id") if isinstance(data.get("department_id"), str) else None)
    v = svc.clean(db, org, data)
    laws = data.get("regulation_ids") or []
    if laws:
        check(db, actor, Action.ADD_SYSTEM_LAW, department_id=v.get("department_id"))
    s = svc.create_system(db, actor.user, org, data, cleaned=v)
    for rid in laws:
        svc.add_law(db, actor.user, s, rid, source="manual")
    if isinstance(data.get("history_answers"), dict):
        from app.register.history import answer_questions

        answer_questions(db, actor.user, s, data["history_answers"])
    return system_out(db, s, actor)


@router.get("/register/{system_id}")
def get_system(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return system_out(db, load(db, actor, system_id), actor, full=True)


@router.patch("/register/{system_id}")
def patch_system(system_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = load(db, actor, system_id)
    check(db, actor, Action.EDIT_REGISTER, s)
    check_edit_payload(db, actor, data, s)
    reason = " ".join(str(data.get("reason") or "").split()) or None
    svc.update_system(db, actor.user, s, {k: v for k, v in data.items() if k != "reason"}, reason=reason)
    return system_out(db, s, actor, full=True)


@router.post("/register/{system_id}/retire")
def post_retire(system_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = load(db, actor, system_id)
    check(db, actor, Action.EDIT_REGISTER, s)
    return system_out(db, svc.retire(db, actor.user, s, body.reason or ""), actor, full=True)


@router.post("/register/{system_id}/duplicate")
def post_duplicate(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = load(db, actor, system_id)
    check(db, actor, Action.EDIT_REGISTER, s)
    return system_out(db, svc.duplicate(db, actor.user, s), actor, full=True)


@router.get("/register/{system_id}/changes")
def get_changes(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = load(db, actor, system_id)
    rows = db.scalars(select(ChangeLog).where(ChangeLog.register_system_id == s.id).order_by(ChangeLog.at.desc(), ChangeLog.id))
    names: dict[str, str] = {}

    def who(uid):
        if uid and uid not in names:
            u = db.get(User, uid)
            names[uid] = u.name if u else "Unknown"
        return names.get(uid) if uid else "System"
    return [{"id": c.id, "at": c.at.isoformat(), "field": c.field, "field_label": svc.FIELD_LABELS.get(c.field, c.field.replace("_", " ").capitalize()),
             "old_value": c.old_value, "new_value": c.new_value, "reason": c.reason, "user": who(c.user_id), "batch_id": c.batch_id, "entity": c.entity} for c in rows]


# ---- laws
@router.post("/register/{system_id}/laws")
def post_law(system_id: str, body: LawIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = load(db, actor, system_id)
    check(db, actor, Action.ADD_SYSTEM_LAW, s)
    svc.add_law(db, actor.user, s, body.regulation_id, reason=body.reason)
    return system_out(db, s, actor, full=True)


def _link(db: Session, s: RegisterSystem, link_id: str) -> RegisterSystemLaw:
    link = db.get(RegisterSystemLaw, link_id)
    if link is None or link.register_system_id != s.id or link.deleted_at is not None or link.status == "removed":
        raise NotFound()
    return link


@router.post("/register/{system_id}/laws/{link_id}/remove")
def post_law_remove(system_id: str, link_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = load(db, actor, system_id)
    link = _link(db, s, link_id)
    direct = may(db, actor, Action.REMOVE_SYSTEM_LAW, s)
    if not direct:
        check(db, actor, Action.ADD_SYSTEM_LAW, s)  # a Department Head may ask
    svc.remove_law(db, actor.user, s, link, reason=body.reason, direct=direct)
    return system_out(db, s, actor, full=True)


@router.post("/register/{system_id}/laws/{link_id}/decide")
def post_law_decide(system_id: str, link_id: str, body: DecideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = load(db, actor, system_id)
    check(db, actor, Action.REMOVE_SYSTEM_LAW, s)
    svc.decide_law_removal(db, actor.user, s, _link(db, s, link_id), body.approve, body.comment)
    return system_out(db, s, actor, full=True)


# ---- bulk edit (R2)
@router.post("/register/bulk")
def post_bulk(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.bulk import bulk_edit

    ids = body.get("system_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise Invalid(errors=[{"field": "system_ids", "message": "Select at least one AI system."}])
    systems = [load(db, actor, i) for i in dict.fromkeys(ids)]
    changes = body.get("changes") or {}
    for s in systems:
        if changes or body.get("request_bias_test"):
            check(db, actor, Action.EDIT_REGISTER, s)
            check_edit_payload(db, actor, changes, s)
        if body.get("add_regulation_ids") or body.get("remove_regulation_ids"):
            check(db, actor, Action.ADD_SYSTEM_LAW, s)
        if body.get("roles"):
            check(db, actor, Action.FILL_SYSTEM_ROLES, s)
    direct = all(may(db, actor, Action.REMOVE_SYSTEM_LAW, s) for s in systems)
    return bulk_edit(db, actor.user, systems, body, can_remove_law_directly=direct, rights=actor)


# ---- history log, first-entry questions, bias tests (R6)
class SignIn(BaseModel):
    typed_name: str


@router.get("/register/{system_id}/history")
def get_history(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.history import history_out

    s = load(db, actor, system_id)
    return history_out(db, s) | {"can_record": may(db, actor, Action.RECORD_SYSTEM_HISTORY, s), "is_owner": s.owner_user_id == actor.id}


@router.post("/register/{system_id}/history")
def post_history(system_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.history import add_entry, entry_out

    s = load(db, actor, system_id)
    check(db, actor, Action.RECORD_SYSTEM_HISTORY, s)
    return entry_out(db, add_entry(db, actor.user, s, data))


@router.patch("/register/{system_id}/history/{entry_id}")
def patch_history(system_id: str, entry_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.history import entry_out, get_entry, update_entry

    s = load(db, actor, system_id)
    check(db, actor, Action.RECORD_SYSTEM_HISTORY, s)
    return entry_out(db, update_entry(db, actor.user, s, get_entry(db, s, entry_id), data))


@router.delete("/register/{system_id}/history/{entry_id}")
def delete_history(system_id: str, entry_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.history import delete_entry, get_entry

    s = load(db, actor, system_id)
    check(db, actor, Action.RECORD_SYSTEM_HISTORY, s)
    delete_entry(db, actor.user, s, get_entry(db, s, entry_id), body.reason)
    return {"ok": True}


@router.post("/register/{system_id}/history/bulk")
def post_history_bulk(system_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.history import delete_entry, get_entry, update_entry

    s = load(db, actor, system_id)
    check(db, actor, Action.RECORD_SYSTEM_HISTORY, s)
    ids = body.get("entry_ids")
    if not isinstance(ids, list) or not ids:
        raise Invalid(errors=[{"field": "entry_ids", "message": "Select at least one entry."}])
    entries = [get_entry(db, s, i) for i in dict.fromkeys(ids) if isinstance(i, str)]
    action = body.get("action")
    if action == "delete":
        for e in entries:
            delete_entry(db, actor.user, s, e, body.get("reason"))
    elif action == "link_requirement":
        rid = body.get("requirement_id")
        if not isinstance(rid, str) or not rid:
            raise Invalid(errors=[{"field": "requirement_id", "message": "Choose a requirement."}])
        for e in entries:
            update_entry(db, actor.user, s, e, {"requirement_ids": list(dict.fromkeys([*(e.requirement_ids or []), rid])), "reason": body.get("reason")})
    else:
        raise Invalid(errors=[{"field": "action", "message": "Choose an action."}])
    return {"ok": True, "count": len(entries)}


@router.post("/register/{system_id}/history-answers")
def post_history_answers(system_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.history import answer_questions, history_out

    s = load(db, actor, system_id)
    check(db, actor, Action.RECORD_SYSTEM_HISTORY, s)
    answer_questions(db, actor.user, s, body)
    return history_out(db, s)


@router.post("/register/{system_id}/no-incident/sign")
def post_sign_statement(system_id: str, body: SignIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.history import history_out, sign_statement

    s = load(db, actor, system_id)  # the owner may be any user who can see the system; the check is ownership
    sign_statement(db, actor.user, s, body.typed_name)
    return history_out(db, s)


@router.post("/register/{system_id}/bias-tests")
def post_bias_test(system_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.history import entry_out, record_bias_test

    s = load(db, actor, system_id)
    check(db, actor, Action.RECORD_SYSTEM_HISTORY, s)
    bt, e = record_bias_test(db, actor.user, s, data)
    return entry_out(db, e)


# ---- evidence (files attached to a system: vendor documents, consent, appointment letters, test reports)
@router.post("/register/{system_id}/evidence")
async def post_evidence(system_id: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.files.service import upload

    s = load(db, actor, system_id)
    if not (may(db, actor, Action.EDIT_REGISTER, s) or may(db, actor, Action.RECORD_SYSTEM_HISTORY, s) or may(db, actor, Action.FILL_SYSTEM_ROLES, s)):
        raise Forbidden()
    f = upload(db, request.app.state.settings, actor.user, data=await file.read(), filename=file.filename or "file", content_type=file.content_type,
               organization_id=s.organization_id, linked_type="register_evidence", linked_id=s.id)
    svc.log_change(db, actor.user, s, "evidence", None, f"Uploaded {f.filename}", None, entity="File", entity_id=f.id, raw=True)
    return {"id": f.id, "filename": f.filename, "uploaded_at": f.created_at.isoformat(), "size": f.size}


@router.get("/register/{system_id}/evidence")
def get_evidence(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.files.models import FileObject

    s = load(db, actor, system_id)
    rows = db.scalars(select(FileObject).where(FileObject.linked_type == "register_evidence", FileObject.linked_id == s.id, FileObject.deleted_at.is_(None)).order_by(FileObject.created_at.desc()))
    return [{"id": f.id, "filename": f.filename, "uploaded_at": f.created_at.isoformat(), "size": f.size, "uploaded_by": (db.get(User, f.uploaded_by).name if f.uploaded_by and db.get(User, f.uploaded_by) else None)} for f in rows]


def file_access(db: Session, actor: Actor, f) -> None:
    """Download rule for register evidence (registered in app.files.router.FILE_ACCESS)."""
    s = db.get(RegisterSystem, f.linked_id) if f.linked_id else None
    if s is None or s.organization_id != f.organization_id:
        raise NotFound()
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_REGISTER, org_id=s.organization_id)
        return
    load(db, actor, s.id)


# ---- governance roles (R3) and the go-live gate (§24.3)
@router.get("/register/{system_id}/roles")
def get_roles(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.gate import gate_for, role_summary
    from app.register.roles import people_options, role_rows

    s = load(db, actor, system_id)
    summary = role_summary(db, s)
    return {"system": system_out(db, s, actor), "rows": role_rows(db, s), "summary": summary, "gate": gate_for(db, s, summary), "people": people_options(db, s.organization_id),
            "can": {"fill": may(db, actor, Action.FILL_SYSTEM_ROLES, s), "company": may(db, actor, Action.SET_COMPANY_ROLES, s), "mark_na": may(db, actor, Action.MARK_REQUIRED_ROLE_NA, s),
                    "submit": may(db, actor, Action.SUBMIT_GO_LIVE, s), "approve": may(db, actor, Action.APPROVE_GO_LIVE, s)}}


@router.put("/register/{system_id}/roles/{role_id}")
def put_role(system_id: str, role_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.roles import catalog_role, check_role_rights, clean_assignment, row_for, set_assignment

    s = load(db, actor, system_id)
    role = catalog_role(db, role_id)
    if role is None:
        raise NotFound()
    row = row_for(db, s, role_id)
    override = bool(data.get("override"))
    check_role_rights(db, actor, s, role, row, str(data.get("status") or ""), override=override)
    v = clean_assignment(db, s.organization_id, data, role)
    override_reason = svc._text(data.get("override_reason"), 1000)
    if role["level"] == "company" and override and not override_reason:
        raise Invalid(errors=[{"field": "override_reason", "message": "Say why this system does not use the company-wide person."}])
    set_assignment(db, actor.user, s.organization_id, role, s, v, override=override, override_reason=override_reason, reason=svc._text(data.get("reason"), 1000) if data.get("status") != "not_applicable" else None)
    return row_for(db, s, role_id)


@router.post("/register/{system_id}/go-live/submit")
def post_go_live_submit(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.gate import submit_go_live

    s = load(db, actor, system_id)
    check(db, actor, Action.SUBMIT_GO_LIVE, s)
    return system_out(db, submit_go_live(db, actor.user, s), actor, full=True)


@router.post("/register/{system_id}/go-live/decide")
def post_go_live_decide(system_id: str, body: DecideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.gate import decide_go_live

    s = load(db, actor, system_id)
    check(db, actor, Action.APPROVE_GO_LIVE, s)
    return system_out(db, decide_go_live(db, actor.user, s, body.approve, body.comment), actor, full=True)


# ---- requirements checklist (R6)
@router.get("/register/{system_id}/requirements")
def get_requirements(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.requirements import checklist

    s = load(db, actor, system_id)
    return checklist(db, s) | {"can_edit": may(db, actor, Action.RECORD_SYSTEM_HISTORY, s)}


@router.put("/register/{system_id}/requirements/{requirement_id}")
def put_requirement(system_id: str, requirement_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.requirements import checklist, set_status

    s = load(db, actor, system_id)
    check(db, actor, Action.RECORD_SYSTEM_HISTORY, s)
    set_status(db, actor.user, s, requirement_id, data)
    return next(r for r in checklist(db, s)["rows"] if r["id"] == requirement_id)
