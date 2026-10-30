"""Company-wide roles and the AI Governance Committee (R5, spec §24.6–§24.7). Client app; tenant from the session."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.register import committee as com
from app.register.router import client_org

router = APIRouter(tags=["register"])


def _can(db: Session, actor: Actor, action: Action) -> bool:
    from app.core.errors import Forbidden, NotFound

    try:
        authorize(db, actor, action, org_id=actor.organization.id)
        return True
    except (Forbidden, NotFound):
        return False


def _out(db: Session, actor: Actor, c) -> dict:
    return {"committee": com.committee_out(db, c), "members": [com.member_out(db, m) for m in com.members(db, c)],
            "can": {"record": _can(db, actor, Action.RECORD_COMMITTEE), "members": _can(db, actor, Action.MANAGE_COMMITTEE_MEMBERS)}}


@router.get("/governance/committee")
def get_committee(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    return _out(db, actor, com.committee_for(db, org, actor.user))


@router.put("/governance/committee")
def put_committee(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.RECORD_COMMITTEE, org_id=org.id)
    c = com.committee_for(db, org, actor.user)
    com.save_settings(db, actor.user, c, data)
    return _out(db, actor, c)


@router.post("/governance/committee/formed")
def post_formed(data: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.RECORD_COMMITTEE, org_id=org.id)
    c = com.committee_for(db, org, actor.user)
    com.record_formed(db, request.app.state.settings, actor.user, c, data)
    return _out(db, actor, c)


@router.post("/governance/committee/members")
def post_member(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.MANAGE_COMMITTEE_MEMBERS, org_id=org.id)
    c = com.committee_for(db, org, actor.user)
    return com.member_out(db, com.add_member(db, actor.user, c, data))


@router.patch("/governance/committee/members/{member_id}")
def patch_member(member_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.MANAGE_COMMITTEE_MEMBERS, org_id=org.id)
    c = com.committee_for(db, org, actor.user)
    return com.member_out(db, com.update_member(db, actor.user, c, com.get_member(db, c, member_id), data))


@router.delete("/governance/committee/members/{member_id}")
def delete_member(member_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.MANAGE_COMMITTEE_MEMBERS, org_id=org.id)
    c = com.committee_for(db, org, actor.user)
    com.remove_member(db, actor.user, c, com.get_member(db, c, member_id))
    return {"ok": True}


# ---- company-wide roles (R5)
@router.get("/governance/company-roles")
def get_company_roles(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.roles import company_page, people_options

    org = client_org(actor)
    authorize(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    return company_page(db, org.id) | {"people": people_options(db, org.id), "can": {"set": _can(db, actor, Action.SET_COMPANY_ROLES), "mark_na": _can(db, actor, Action.MARK_REQUIRED_ROLE_NA)}}


@router.put("/governance/company-roles/{role_id}")
def put_company_role(role_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.core.errors import NotFound
    from app.register.roles import catalog_role, check_role_rights, clean_assignment, company_page, company_required_anywhere, set_assignment

    org = client_org(actor)
    role = catalog_role(db, role_id)
    if role is None or role["level"] != "company":
        raise NotFound()
    status = str(data.get("status") or "")
    row = {"requirement": "required" if status == "not_applicable" and company_required_anywhere(db, org.id, role_id) else "recommended"}
    check_role_rights(db, actor, None, role, row, status)
    v = clean_assignment(db, org.id, data, role)
    set_assignment(db, actor.user, org.id, role, None, v, reason=None)
    return next(r for r in company_page(db, org.id)["rows"] if r["role_id"] == role_id)
