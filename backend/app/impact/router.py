"""Screen 28 (client): new AI projects and their impact assessment; reassessment triggers on the register."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.impact import service as svc
from app.impact.assess import FEATURE_LABELS, assess, depth_for
from app.impact.models import ImpactAssessment
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.tenancy.models import Department, User

router = APIRouter(tags=["impact assessment"])


class ReviewIn(BaseModel):
    step: str
    recommendation: str
    comment: str | None = None


class DecideIn(BaseModel):
    decision: str
    note: str | None = None
    conditions: list[dict] | None = None
    link_register_system_id: str | None = None


class NoteIn(BaseModel):
    note: str | None = None
    reopen: bool = False


def client_org(actor: Actor):
    if actor.is_futran:
        raise NotFound()  # a client screen; Futran sees an independent-opinion request as an opportunity
    return actor.organization


def can(db: Session, actor: Actor, action: Action, department_id: str | None) -> bool:
    try:
        authorize(db, actor, action, org_id=actor.organization.id, department_id=department_id)
        return True
    except (Forbidden, NotFound):
        return False


def load(db: Session, actor: Actor, pid: str) -> ImpactAssessment:
    org = client_org(actor)
    ia = db.get(ImpactAssessment, pid)
    if ia is None or ia.deleted_at is not None or ia.organization_id != org.id:
        raise NotFound()
    if not can(db, actor, Action.VIEW_PROJECTS, ia.department_id) and ia.created_by != actor.id:
        raise NotFound()
    return ia


def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def project_out(db: Session, actor: Actor, ia: ImpactAssessment, full: bool = True) -> dict:
    dept = db.get(Department, ia.department_id) if ia.department_id else None
    i = ia.intake or {}
    out = {
        "id": ia.id, "reference": ia.reference, "project_name": ia.project_name, "department_id": ia.department_id, "department_name": dept.name if dept else None,
        "status": ia.status, "status_label": svc.STATUS_LABELS.get(ia.status, ia.status), "proposed_tier": ia.proposed_tier, "tier_reason": ia.tier_reason,
        "assessment_depth": ia.assessment_depth, "decision": ia.decision, "decision_label": svc.DECISION_LABELS.get(ia.decision) if ia.decision else None,
        "tool_or_vendor": i.get("tool_or_vendor"), "planned_go_live": i.get("planned_go_live"), "submitted_by_name": _name(db, ia.submitted_by),
        "submitted_at": ia.submitted_at.isoformat() if ia.submitted_at else None, "decided_at": ia.decided_at.isoformat() if ia.decided_at else None,
        "register_system_id": ia.register_system_id, "opinion_opportunity_id": ia.opinion_opportunity_id,
        "open_conditions": sum(c.status != "closed" for c in svc.conditions_of(db, ia)),
        "matched_law_count": sum(1 for x in ia.matched_regulations or [] if x.get("matched")),
    }
    if not full:
        return out
    from app.reference.models import Jurisdiction
    from app.register.models import RegisterSystem

    rv = svc.reviews(db, ia)
    a = assess(db, svc._intake_for_assess(db, ia)) if ia.status == "draft" else None
    s = db.get(RegisterSystem, ia.register_system_id) if ia.register_system_id else None
    dept_id = ia.department_id
    prepared = actor.id in svc.preparers(db, ia)
    out |= {
        "intake": i, "jurisdictions": [{"id": j.id, "name": j.name} for j in (db.get(Jurisdiction, x) for x in i.get("jurisdiction_ids") or []) if j],
        "depth_sections": ia.depth_sections or [], "depth_text": depth_for(ia.proposed_tier or 1, i)[2],
        "matched_regulations": ia.matched_regulations or [], "features": [FEATURE_LABELS[f] for f in (a or {}).get("features", [])] or None,
        "decision_note": ia.decision_note, "decided_by_name": _name(db, ia.decided_by),
        "register_system": {"id": s.id, "reference": s.reference, "name": s.name, "stage": s.stage} if s else None,
        "reviews": [{"step": st, "step_label": svc.STEP_LABELS[st], "reviewer_name": _name(db, r.reviewer_id), "recommendation": r.recommendation,
                     "recommendation_label": svc.RECOMMENDATION_LABELS[r.recommendation], "comment": r.comment, "reviewed_at": r.reviewed_at.isoformat()}
                    for st, r in rv.items()],
        "dpo_required": svc.dpo_required(db, ia),
        "reviewer_names": {"department": [u.name for u in svc._with_role(db, ia.organization_id, "dept_compliance_lead", dept_id)],
                           "dpo": [u.name for u in svc._with_role(db, ia.organization_id, "dpo")], "caico": [u.name for u in svc._with_role(db, ia.organization_id, "caico")]},
        "conditions": [{"id": c.id, "text": c.text, "owner_user_id": c.owner_user_id, "owner_name": _name(db, c.owner_user_id), "due_on": c.due_on.isoformat() if c.due_on else None,
                        "status": c.status, "met_note": c.met_note, "met_at": c.met_at.isoformat() if c.met_at else None,
                        "can_mark_met": c.status == "open" and (c.owner_user_id == actor.id or can(db, actor, Action.DECIDE_PROJECT, dept_id)),
                        "can_close": c.status == "met" and can(db, actor, Action.DECIDE_PROJECT, dept_id)} for c in svc.conditions_of(db, ia)],
        "can_edit": ia.status == "draft" and can(db, actor, Action.SUBMIT_PROJECT, dept_id),
        "can_review_department": ia.status == "in_review" and not prepared and can(db, actor, Action.REVIEW_PROJECT_DEPARTMENT, dept_id),
        "can_review_dpo": ia.status == "in_review" and not prepared and can(db, actor, Action.REVIEW_PROJECT_DPO, dept_id),
        "can_decide": ia.status == "in_review" and not prepared and can(db, actor, Action.DECIDE_PROJECT, dept_id),
        "can_request_opinion": ia.proposed_tier == 3 and ia.status != "withdrawn" and not ia.opinion_opportunity_id and can(db, actor, Action.SUBMIT_PROJECT, dept_id),
    }
    return out


@router.get("/projects")
def list_projects(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.VIEW_PROJECTS, org_id=org.id, list_view=True)
    depts = departments_for(actor, Action.VIEW_PROJECTS)
    rows = list(db.scalars(select(ImpactAssessment).where(ImpactAssessment.organization_id == org.id, ImpactAssessment.deleted_at.is_(None)).order_by(ImpactAssessment.created_at.desc())))
    rows = [r for r in rows if depts is None or r.department_id in depts or r.created_by == actor.id]
    from app.register.models import RegisterSystem

    systems = db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org.id, RegisterSystem.deleted_at.is_(None), RegisterSystem.stage != "retired").order_by(RegisterSystem.reference))
    return {"rows": [project_out(db, actor, r, full=False) for r in rows],
            "can_submit": can(db, actor, Action.SUBMIT_PROJECT, None) or bool(departments_for(actor, Action.SUBMIT_PROJECT)),
            "departments": [{"id": d.id, "name": d.name} for d in db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None)).order_by(Department.name))
                            if can(db, actor, Action.SUBMIT_PROJECT, d.id)],
            "register_systems": [{"id": s.id, "label": f"{s.reference} {s.name}"} for s in systems] if can(db, actor, Action.DECIDE_PROJECT, None) else [],
            "people": [{"id": u.id, "name": u.name} for u in db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name))]
            if can(db, actor, Action.DECIDE_PROJECT, None) else []}


@router.post("/projects/assess")
def live_assess(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The tier, depth and laws as the form is filled in. Nothing is saved."""
    org = client_org(actor)
    authorize(db, actor, Action.VIEW_PROJECTS, org_id=org.id, list_view=True)
    intake = svc.clean_intake(db, org, body | {"project_name": body.get("project_name") or "New project"}, current=_blank(org.id, body))["intake"]
    dept = db.get(Department, body.get("department_id")) if isinstance(body.get("department_id"), str) else None
    return assess(db, intake | {"project_name": body.get("project_name") or "", "department_name": dept.name if dept and dept.organization_id == org.id else ""})


def _blank(org_id: str, body: dict) -> ImpactAssessment:
    """A throw-away draft so the live preview validates only the intake answers, not the name or department."""
    return ImpactAssessment(organization_id=org_id, project_name=body.get("project_name") or "New project", department_id=None, intake={})


@router.post("/projects")
def create_project(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.SUBMIT_PROJECT, org_id=org.id, department_id=body.get("department_id") if isinstance(body.get("department_id"), str) else None)
    ia = svc.create(db, actor.user, org, body)
    return project_out(db, actor, ia)


@router.get("/projects/{pid}")
def get_project(pid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return project_out(db, actor, load(db, actor, pid))


@router.patch("/projects/{pid}")
def edit_project(pid: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    ia = load(db, actor, pid)
    authorize(db, actor, Action.SUBMIT_PROJECT, org_id=ia.organization_id, department_id=ia.department_id)
    if isinstance(body.get("department_id"), str) and body["department_id"] != ia.department_id:
        authorize(db, actor, Action.SUBMIT_PROJECT, org_id=ia.organization_id, department_id=body["department_id"])
    return project_out(db, actor, svc.update(db, actor.user, ia, body))


@router.post("/projects/{pid}/submit")
def submit_project(pid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    ia = load(db, actor, pid)
    authorize(db, actor, Action.SUBMIT_PROJECT, org_id=ia.organization_id, department_id=ia.department_id)
    return project_out(db, actor, svc.submit(db, actor.user, ia))


@router.post("/projects/{pid}/reviews")
def review_project(pid: str, body: ReviewIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    ia = load(db, actor, pid)
    action = Action.REVIEW_PROJECT_DPO if body.step == "dpo" else Action.REVIEW_PROJECT_DEPARTMENT
    authorize(db, actor, action, org_id=ia.organization_id, department_id=ia.department_id)
    svc.review(db, actor.user, ia, body.step, body.recommendation, body.comment)
    return project_out(db, actor, ia)


@router.post("/projects/{pid}/decide")
def decide_project(pid: str, body: DecideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    ia = load(db, actor, pid)
    authorize(db, actor, Action.DECIDE_PROJECT, org_id=ia.organization_id, department_id=ia.department_id)
    svc.decide(db, actor.user, ia, body.decision, body.note, body.conditions, body.link_register_system_id)
    return project_out(db, actor, ia)


@router.post("/projects/{pid}/opinion")
def ask_for_opinion(pid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    ia = load(db, actor, pid)
    authorize(db, actor, Action.SUBMIT_PROJECT, org_id=ia.organization_id, department_id=ia.department_id)
    return project_out(db, actor, svc.request_opinion(db, actor.user, ia))


@router.post("/projects/{pid}/conditions/{cid}/met")
def condition_met(pid: str, cid: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    ia = load(db, actor, pid)
    c = svc.get_condition(db, ia, cid)
    if c.owner_user_id != actor.id:
        authorize(db, actor, Action.DECIDE_PROJECT, org_id=ia.organization_id, department_id=ia.department_id)
    svc.mark_met(db, actor.user, ia, c, body.note)
    return {"id": c.id, "status": c.status}


@router.post("/projects/{pid}/conditions/{cid}/close")
def condition_close(pid: str, cid: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    ia = load(db, actor, pid)
    authorize(db, actor, Action.DECIDE_PROJECT, org_id=ia.organization_id, department_id=ia.department_id)
    c = svc.close_condition(db, actor.user, ia, svc.get_condition(db, ia, cid), reopen=body.reopen, note=body.note)
    return {"id": c.id, "status": c.status}


# ---------------------------------------------------------------- reassessment triggers (register record and client home)
class TriggerIn(BaseModel):
    type: str
    detail: str | None = None


def trigger_out(db: Session, t) -> dict:
    from app.impact.triggers import SOURCE_LABELS, TYPE_LABELS
    from app.register.models import RegisterSystem

    s = db.get(RegisterSystem, t.register_system_id)
    return {"id": t.id, "register_system_id": t.register_system_id, "system_reference": s.reference if s else None, "system_name": s.name if s else None,
            "type": t.type, "type_label": TYPE_LABELS.get(t.type, t.type), "source": t.source, "source_label": SOURCE_LABELS.get(t.source, t.source), "detail": t.detail,
            "detected_at": t.detected_at.isoformat(), "status": t.status, "reopened": t.reopened or [], "resolution_note": t.resolution_note,
            "resolved_by_name": _name(db, t.resolved_by), "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None}


def _system(db: Session, actor: Actor, sid: str):
    from app.register.router import load as load_system

    s = load_system(db, actor, sid)
    authorize(db, actor, Action.VIEW_REASSESSMENT, org_id=s.organization_id, department_id=None if s.company_wide else s.department_id)
    return s


@router.get("/register/{sid}/triggers")
def system_triggers(sid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.impact.models import ReassessmentTrigger
    from app.impact.triggers import TYPE_LABELS

    s = _system(db, actor, sid)
    rows = db.scalars(select(ReassessmentTrigger).where(ReassessmentTrigger.register_system_id == s.id, ReassessmentTrigger.deleted_at.is_(None)).order_by(ReassessmentTrigger.detected_at.desc()))
    return {"rows": [trigger_out(db, t) for t in rows], "can_manage": can(db, actor, Action.MANAGE_REASSESSMENT, None if s.company_wide else s.department_id),
            "types": [{"value": k, "label": v} for k, v in TYPE_LABELS.items() if k not in ("failed_monitor_check", "regulatory_update", "twelve_months")]}


@router.post("/register/{sid}/triggers")
def raise_by_hand(sid: str, body: TriggerIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.core.errors import Invalid
    from app.impact.triggers import raise_trigger

    s = _system(db, actor, sid)
    authorize(db, actor, Action.MANAGE_REASSESSMENT, org_id=s.organization_id, department_id=None if s.company_wide else s.department_id)
    if body.type in ("failed_monitor_check", "regulatory_update", "twelve_months") or body.type not in svc_trigger_types():
        raise Invalid(errors=[{"field": "type", "message": "Choose what changed."}])
    t = raise_trigger(db, s.id, type=body.type, source="manual", detail=(body.detail or "").strip() or None, actor_id=actor.id)
    if t is None:
        from app.core.errors import Conflict

        raise Conflict("A retired system is not reassessed.")
    return trigger_out(db, t)


def svc_trigger_types():
    from app.impact.models import TRIGGER_TYPES

    return TRIGGER_TYPES


@router.get("/reassessment")
def open_triggers(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Open triggers for the client home."""
    from app.impact.models import OPEN_TRIGGER, ReassessmentTrigger
    from app.register.models import RegisterSystem

    org = client_org(actor)
    authorize(db, actor, Action.VIEW_REASSESSMENT, org_id=org.id, list_view=True)
    depts = departments_for(actor, Action.VIEW_REASSESSMENT)
    out = []
    for t in db.scalars(select(ReassessmentTrigger).where(ReassessmentTrigger.organization_id == org.id, ReassessmentTrigger.status.in_(OPEN_TRIGGER),
                                                          ReassessmentTrigger.deleted_at.is_(None)).order_by(ReassessmentTrigger.detected_at)):
        s = db.get(RegisterSystem, t.register_system_id)
        if s is None or s.deleted_at is not None or (depts is not None and not s.company_wide and s.department_id not in depts):
            continue
        out.append(trigger_out(db, t))
    return {"rows": out}


class ResolveIn(BaseModel):
    note: str | None = None


def _trigger(db: Session, actor: Actor, tid: str):
    from app.impact.models import ReassessmentTrigger

    org = client_org(actor)
    t = db.get(ReassessmentTrigger, tid)
    if t is None or t.organization_id != org.id or t.deleted_at is not None:
        raise NotFound()
    s = _system(db, actor, t.register_system_id)
    authorize(db, actor, Action.MANAGE_REASSESSMENT, org_id=org.id, department_id=None if s.company_wide else s.department_id)
    return t, s


@router.post("/reassessment/{tid}/{action}")
def act_on_trigger(tid: str, action: str, body: ResolveIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.impact.lifecycle import act

    t, s = _trigger(db, actor, tid)
    return trigger_out(db, act(db, actor.user, t, s, action, body.note))
