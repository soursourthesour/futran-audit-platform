"""Departments, users and role holders for one client (screen 10b, mockup ClientUsers)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, Invalid, NotFound
from app.engagements.client_router import invite_status
from app.engagements.gates import gate_status
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.policy.roles import ROLE_LABELS
from app.tenancy import people
from app.tenancy.csv_import import parse_department_csv, parse_user_csv
from app.tenancy.models import Department, Organization, RoleAssignment, User
from app.tenancy.service import roles_of

router = APIRouter(prefix="/clients/{client_id}", tags=["client people"])


class CsvIn(BaseModel):
    csv_text: str


class DepartmentIn(BaseModel):
    name: str
    headcount: int | None = None


class ClientUserIn(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    job_title: str | None = None
    department: str | None = None
    role: str = ""


class NotAppointedIn(BaseModel):
    not_appointed: bool


def _org(db: Session, actor: Actor, client_id: str, action: Action) -> Organization:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at:
        raise NotFound()
    authorize(db, actor, action, org_id=org.id, list_view=True)
    return org


@router.get("/people")
def get_people(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.VIEW_CLIENT_USERS)
    manage = True
    try:
        authorize(db, actor, Action.MANAGE_CLIENT_USERS, org_id=org.id)
    except (Forbidden, NotFound):
        manage = False
    depts = people.departments(db, org)
    visible_depts = None if manage or actor.is_futran else (departments_for(actor, Action.VIEW_CLIENT_USERS) or set())
    names = {d.id: d.name for d in depts}
    lead_rows = db.execute(select(RoleAssignment.scope_id, User.name).join(User, User.id == RoleAssignment.user_id).where(RoleAssignment.role == "dept_compliance_lead", RoleAssignment.deleted_at.is_(None), RoleAssignment.organization_id == org.id, User.status != "disabled"))
    leads: dict[str, str] = {}
    for sid, name in lead_rows:
        leads.setdefault(sid, name)
    users = []
    for u in db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None)).order_by(User.name)):
        roles = [{"id": r.id, "role": r.role, "role_label": ROLE_LABELS.get(r.role, r.role), "department": names.get(r.scope_id) if r.scope_type == "department" else None, "sign_off_role": r.role in people.SIGN_OFF_KEYS} for r in roles_of(db, u.id)]
        if visible_depts is not None and not any(r.scope_type == "department" and r.scope_id in visible_depts for r in roles_of(db, u.id)):
            continue
        users.append({"id": u.id, "name": u.name, "email": u.email, "job_title": u.job_title, "status": u.status, "invite_status": invite_status(db, u), "roles": roles})
    e = people.current_engagement(db, org)
    gate = gate_status(db, e) if e is not None and e.stage == 2 else None
    return {
        "client": {"id": org.id, "name": org.name},
        "can_manage": manage,
        "departments": [{"id": d.id, "name": d.name, "headcount": d.headcount, "head_name": d.head_name, "in_scope": d.in_scope, "lead": leads.get(d.id)} for d in depts if visible_depts is None or d.id in visible_depts],
        "users": users,
        "role_holders": people.role_holders(db, org),
        "gate": {"stage": e.stage, "ready": gate.ready, "unmet": gate.unmet} if gate else ({"stage": e.stage, "ready": True, "unmet": []} if e else None),
    }


@router.get("/departments/template.csv")
def department_template(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    return Response(people.department_template(db, org), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="department_list.csv"'})


@router.post("/departments")
def post_department(client_id: str, body: DepartmentIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    d = people.add_department(db, actor.user, org, body.name, body.headcount)
    return {"id": d.id, "name": d.name}


@router.patch("/departments/{dept_id}")
def patch_department(client_id: str, dept_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    from app.audit_log import service as audit

    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    d = db.get(Department, dept_id)
    if d is None or d.organization_id != org.id or d.deleted_at:
        raise NotFound()
    before = {"in_scope": d.in_scope, "headcount": d.headcount}
    if "in_scope" in body and not isinstance(body["in_scope"], bool):
        raise Invalid(errors=[{"field": "in_scope", "message": "Choose in scope or out of scope."}])
    if "headcount" in body:
        hc = str(body["headcount"] if body["headcount"] is not None else "").strip()
        if hc and not (hc.isascii() and hc.isdecimal() and len(hc) < 8):
            raise Invalid(errors=[{"field": "headcount", "message": "Headcount must be a whole number."}])
    if "in_scope" in body and body["in_scope"] != d.in_scope:
        people.scope_changed(db, org)
        d.in_scope = body["in_scope"]
    if "headcount" in body:
        d.headcount = int(hc) if hc else None
    audit.record(db, actor_id=actor.id, action="department.edit", obj=d, before=before, after={"in_scope": d.in_scope, "headcount": d.headcount}, summary=f"Edited department {d.name}")
    people.advance_if_ready(db, actor.user, people.current_engagement(db, org))
    return {"id": d.id, "in_scope": d.in_scope, "headcount": d.headcount}


@router.post("/departments/import/preview")
def preview_departments(client_id: str, body: CsvIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    return parse_department_csv(body.csv_text).to_json()


@router.post("/departments/import")
def import_departments(client_id: str, body: CsvIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    return people.import_departments(db, actor.user, org, body.csv_text)


@router.post("/departments/confirm")
def confirm_departments(client_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    people.confirm_departments(db, request.app.state.settings, actor.user, org)
    return {"confirmed": True}


@router.post("/users/import/preview")
def preview_users(client_id: str, body: CsvIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    return parse_user_csv(body.csv_text, [d.name for d in people.departments(db, org)]).to_json()


@router.post("/users/import")
def import_users(client_id: str, body: CsvIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    return people.import_users(db, request.app.state.settings, actor.user, org, body.csv_text)


@router.post("/users")
def post_user(client_id: str, body: ClientUserIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    u = people.add_user(db, request.app.state.settings, actor.user, org, body.model_dump())
    return {"id": u.id, "name": u.name, "email": u.email}


@router.delete("/users/{user_id}/roles/{assignment_id}")
def delete_role(client_id: str, user_id: str, assignment_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    u = db.get(User, user_id)
    if u is None or u.organization_id != org.id:
        raise NotFound()
    people.remove_role(db, request.app.state.settings, actor.user, org, u, assignment_id)
    return {"removed": True}


@router.put("/role-holders/{role}")
def put_role_holder(client_id: str, role: str, body: NotAppointedIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = _org(db, actor, client_id, Action.MANAGE_CLIENT_USERS)
    people.set_not_appointed(db, actor.user, org, role, body.not_appointed)
    return people.role_holders(db, org)[role]
