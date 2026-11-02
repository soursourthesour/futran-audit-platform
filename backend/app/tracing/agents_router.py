"""Agent oversight endpoints (spec §21 F14).

Client app: `/register/{id}/agent` (read with the register, edit with the register's edit right on that system).
Futran app: `/clients/{id}/agents` and decision samples, for the audit team on the client's current engagement (the
Chief Auditor on any). Every endpoint calls `authorize`.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor, get_settings_dep
from app.core.db import get_db
from app.core.errors import Conflict, NotFound
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.register.models import RegisterSystem
from app.tenancy.models import Department, Organization
from app.tracing import agents as svc
from app.tracing.models import ActionTrace, AgentDecisionSample

router = APIRouter(tags=["agents"])


class SampleIn(BaseModel):
    size: int = Field(default=25)
    period_days: int = Field(default=90)
    seed: int | None = None


class ReviewIn(BaseModel):
    trace_id: str
    verdict: str
    note: str | None = None


class CompleteIn(BaseModel):
    conclusion: str | None = None


# ---------------------------------------------------------------- client: the registration
@router.get("/register/{system_id}/agent")
def get_registration(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.router import load, may

    s = load(db, actor, system_id)
    r = svc.registration(db, s)
    tr, flags = svc.trend(db, s)
    samples = db.scalars(select(AgentDecisionSample).where(AgentDecisionSample.register_system_id == s.id, AgentDecisionSample.status == "complete",
                                                           AgentDecisionSample.deleted_at.is_(None)).order_by(AgentDecisionSample.completed_at.desc()))
    return {"system": {"id": s.id, "reference": s.reference, "name": s.name, "type": s.type, "autonomy": s.autonomy}, "is_agent": s.type == "agent",
            "registration": svc.registration_out(r), "can_edit": s.type == "agent" and may(db, actor, Action.EDIT_REGISTER, s),
            "unregistered_tools": svc.unregistered_tools(db, s, r) if s.type == "agent" else [], "trend": tr, "flags": flags,
            "reviews": [{"id": x.id, "completed_at": x.completed_at.isoformat() if x.completed_at else None, "size": len(x.trace_ids or []), "summary": svc.summary(db, x)} for x in samples],
            "autonomy_options": [{"value": k, "label": v} for k, v in svc.AUTONOMY_LABELS.items()]}


@router.put("/register/{system_id}/agent")
def put_registration(system_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    from app.register.router import check, load

    s = load(db, actor, system_id)
    check(db, actor, Action.EDIT_REGISTER, s)
    return svc.registration_out(svc.save(db, settings, actor, s, data))


# ---------------------------------------------------------------- Futran: agents of a client, samples
def _engagement(db: Session, actor: Actor, client_id: str) -> Engagement:
    from app.tenancy.people import current_engagement

    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or not actor.is_futran:
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, Action.REVIEW_AGENT_DECISIONS, engagement_id=e.id)
    return e


def _agent(db: Session, client_id: str, system_id: str) -> RegisterSystem:
    s = db.get(RegisterSystem, system_id)
    if s is None or s.deleted_at is not None or s.organization_id != client_id:
        raise NotFound()
    return s


@router.get("/clients/{client_id}/agents")
def list_agents(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _engagement(db, actor, client_id)
    out = []
    for s in db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == client_id, RegisterSystem.type == "agent", RegisterSystem.deleted_at.is_(None)).order_by(RegisterSystem.reference)):
        r = svc.registration(db, s)
        tr, flags = svc.trend(db, s)
        dept = db.get(Department, s.department_id) if s.department_id else None
        samples = db.scalars(select(AgentDecisionSample).where(AgentDecisionSample.register_system_id == s.id, AgentDecisionSample.deleted_at.is_(None)).order_by(AgentDecisionSample.created_at.desc()))
        out.append({"id": s.id, "reference": s.reference, "name": s.name, "stage": s.stage, "department": dept.name if dept else None, "registration": svc.registration_out(r),
                    "unregistered_tools": svc.unregistered_tools(db, s, r), "decisions": db.scalar(select(func.count()).select_from(ActionTrace).where(ActionTrace.register_system_id == s.id)) or 0,
                    "trend": tr, "flags": flags, "samples": [svc.sample_out(db, x) for x in samples]})
    return {"client": db.get(Organization, client_id).name, "engagement": e.audit_ref, "agents": out, "verdicts": [{"value": k, "label": v} for k, v in svc.VERDICT_LABELS.items()]}


@router.post("/clients/{client_id}/agents/{system_id}/samples")
def post_sample(client_id: str, system_id: str, body: SampleIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _engagement(db, actor, client_id)
    s = _agent(db, client_id, system_id)
    return svc.sample_out(db, svc.draw(db, actor, s, e.id, body.size, body.period_days, body.seed))


def _sample(db: Session, actor: Actor, sample_id: str) -> AgentDecisionSample:
    smp = svc.load_sample(db, sample_id)
    if not actor.is_futran:
        raise NotFound()
    _engagement(db, actor, smp.organization_id)
    return smp


@router.get("/agent-samples/{sample_id}")
def get_sample(sample_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.sample_out(db, _sample(db, actor, sample_id))


@router.post("/agent-samples/{sample_id}/reviews")
def post_review(sample_id: str, body: ReviewIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    smp = _sample(db, actor, sample_id)
    svc.review(db, actor, smp, body.trace_id, body.verdict, body.note)
    return svc.sample_out(db, smp)


@router.post("/agent-samples/{sample_id}/complete")
def post_complete(sample_id: str, body: CompleteIn | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    smp = _sample(db, actor, sample_id)
    if smp.status == "complete":
        raise Conflict("This sample is already complete.")
    return svc.sample_out(db, svc.complete(db, actor, smp, body.conclusion if body else None))
