"""New-client wizard API (screens NewClient1–4)."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Invalid, NotFound
from app.engagements import wizard
from app.engagements.models import Engagement, EngagementTeam
from app.engagements.service import create_engagement, transition
from app.engagements.suggest import suggest_requirements
from app.mail.service import send
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization, RoleAssignment, User
from app.tenancy.service import create_organization, roles_of

router = APIRouter(prefix="/clients", tags=["new client"])


class ReturnIn(BaseModel):
    comment: str = ""


def _load(db: Session, actor: Actor, client_id: str, action: Action = Action.CREATE_CLIENT_ENGAGEMENT) -> tuple[Organization, Engagement]:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at:
        raise NotFound()
    e = db.scalar(select(Engagement).where(Engagement.client_id == org.id, Engagement.deleted_at.is_(None)).order_by(Engagement.created_at.desc()).limit(1))
    if e is None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=e.id)
    return org, e


def _summary(e: Engagement) -> dict:
    return {"engagement_id": e.id, "client_id": e.client_id, "audit_ref": e.audit_ref, "status": e.status, "stage": e.stage}


@router.post("")
def new_client(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.CREATE_CLIENT_ENGAGEMENT)
    org = create_organization(db, name="New client", type="client", actor_id=actor.id, status="draft")
    e = create_engagement(db, actor.user, org, name="New client AI governance audit")
    e.wizard_state = {"auto_name": True}
    team_role = "chief_auditor" if actor.has_role("chief_auditor") else "auditor" if actor.has_role("auditor") else None
    if team_role:  # the author joins the team so the draft stays visible to them
        db.add(EngagementTeam(organization_id=org.id, engagement_id=e.id, user_id=actor.id, role=team_role, created_by=actor.id))
    db.flush()
    return {"client_id": org.id, "engagement_id": e.id}


@router.get("/team-options")
def team_options(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.CREATE_CLIENT_ENGAGEMENT)
    out = []
    users = db.scalars(select(User).join(Organization, Organization.id == User.organization_id).where(Organization.type == "futran", User.status != "disabled", User.deleted_at.is_(None)).order_by(User.name))
    for u in users:
        roles = sorted({r.role for r in roles_of(db, u.id)} - {"admin"})
        if roles:
            out.append({"user_id": u.id, "name": u.name, "email": u.email, "roles": roles})
    return out


@router.get("/{client_id}/wizard")
def get_wizard(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org, e = _load(db, actor, client_id, Action.VIEW_ENGAGEMENT)
    if not actor.is_futran:  # Futran-internal: engagement reason, conflict confirmations, suggestion reasoning
        raise NotFound()
    return wizard.wizard_out(db, org, e)


@router.put("/{client_id}/wizard/{step}")
def save_step(client_id: str, step: str, payload: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if step not in wizard.STEPS:
        raise NotFound()
    org, e = _load(db, actor, client_id)
    if e.status != "draft":
        raise Conflict("This engagement has been submitted for approval. Ask the Chief Auditor to return it if it needs changes.")
    before = wizard.snapshot(db, org, e, step)
    errors = wizard.SAVERS[step](db, actor.user, org, e, payload)
    state = dict(e.wizard_state or {})
    state["editors"] = list(dict.fromkeys([*(state.get("editors") or []), actor.id]))  # editors cannot approve (spec §6 rule 2)
    e.wizard_state = state | {"last_step": step}
    db.flush()
    after = wizard.snapshot(db, org, e, step)
    changed = [k for k in after if after[k] != before.get(k)]
    if changed:
        audit.record(db, actor_id=actor.id, action="wizard.save", obj=e, before={k: before.get(k) for k in changed}, after={k: after[k] for k in changed}, summary=f"Edited the {step} step of {e.audit_ref}")
    return {"saved_at": utcnow().isoformat(), "errors": errors}


@router.get("/{client_id}/suggestions")
def suggestions(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org, e = _load(db, actor, client_id, Action.VIEW_ENGAGEMENT)
    if not actor.is_futran:
        raise NotFound()
    return [s.to_json() for s in suggest_requirements(db, org, e)]


def _chief_auditors(db: Session, e: Engagement) -> list[User]:
    team = list(db.scalars(select(User).join(EngagementTeam, EngagementTeam.user_id == User.id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.role == "chief_auditor", EngagementTeam.deleted_at.is_(None))))
    if team:
        return team
    return list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(RoleAssignment.role == "chief_auditor", RoleAssignment.deleted_at.is_(None), User.status == "active")))


@router.post("/{client_id}/submit")
def submit(client_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org, e = _load(db, actor, client_id)
    if e.status != "draft":
        raise Conflict("This engagement has already been submitted.")
    errors = wizard.validate(db, org, e)
    if errors:
        raise Invalid("Some details are missing. Complete the fields listed before submitting.", errors)
    transition(db, actor.user, e, "pending_approval")
    settings = request.app.state.settings
    from app.initiation.service import generate_package

    generate_package(db, settings, actor.user, e)  # the Chief Auditor reviews exactly what was submitted
    for chief in _chief_auditors(db, e):
        send(db, settings, "engagement_submitted", to=[chief.email], organization_id=chief.organization_id, actor_id=actor.id, related=e,
             context={"name": chief.name, "preparer": actor.user.name, "client": org.name, "audit_ref": e.audit_ref, "link": f"{settings.base_url}/clients/{org.id}"})
    return _summary(e)


@router.post("/{client_id}/return")
def return_to_author(client_id: str, body: ReturnIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org, e = _load(db, actor, client_id, Action.APPROVE_ENGAGEMENT)
    transition(db, actor.user, e, "draft", comment=body.comment)
    author = db.get(User, e.created_by) if e.created_by else None
    if author is not None:
        settings = request.app.state.settings
        send(db, settings, "engagement_returned", to=[author.email], organization_id=author.organization_id, actor_id=actor.id, related=e,
             context={"name": author.name, "reviewer": actor.user.name, "client": org.name, "audit_ref": e.audit_ref, "comment": e.returned_comment, "link": f"{settings.base_url}/clients/{org.id}/setup/company"})
    audit.record(db, actor_id=actor.id, action="engagement.return_notified", obj=e, summary=f"Returned {e.audit_ref} to {author.name if author else 'the author'}")
    return _summary(e)
