"""New AI project impact assessment (spec §21 F8, screen 28): intake, reviews, the CAICO's decision, conditions, the
independent opinion and the register system the project becomes."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.impact.assess import assess
from app.impact.models import DECISIONS, RECOMMENDATIONS, REVIEW_STEPS, ImpactAssessment, ImpactCondition, ImpactReview
from app.tenancy.models import Department, Organization, User

DECISION_LABELS = {"approved": "Approved", "approved_with_conditions": "Approved with conditions", "rejected": "Rejected"}
RECOMMENDATION_LABELS = {"approve": "Approve", "approve_with_conditions": "Approve with conditions", "reject": "Reject"}
STATUS_LABELS = {"draft": "Draft", "in_review": "In review", "decided": "Decided", "withdrawn": "Withdrawn"}
STEP_LABELS = {"department": "Department Compliance Lead", "dpo": "Data Protection Officer"}
INTAKE_KEYS = ("purpose", "tool_or_vendor", "system_type", "sourcing", "planned_go_live", "jurisdiction_ids", "data_categories", "data_subjects",
               "decision_impact", "public_facing", "user_count", "autonomy")


# ---- intake
def clean_intake(db: Session, org: Organization, data: dict, current: ImpactAssessment | None = None) -> dict:
    """Validate what is given. Returns {"project_name", "department_id", "intake"} (intake merged over the current one)."""
    from app.reference.models import Jurisdiction
    from app.register.models import AUTONOMY, DECISION_IMPACT, SOURCING, TYPES
    from app.register.service import DATA_CATEGORIES, DATA_SUBJECTS

    errs: list[dict] = []
    out: dict = {}
    if "project_name" in data or current is None:
        name = " ".join(str(data.get("project_name") or "").split())
        if not name:
            errs.append({"field": "project_name", "message": "Name the project."})
        out["project_name"] = name[:160]
    if "department_id" in data or current is None:
        d = data.get("department_id")
        dept = db.get(Department, d) if isinstance(d, str) and d else None
        if dept is None or dept.deleted_at is not None or dept.organization_id != org.id:
            errs.append({"field": "department_id", "message": "Choose the department that will use it."})
        out["department_id"] = d
    intake = dict(current.intake or {}) if current else {}
    for k in ("purpose", "tool_or_vendor"):
        if k in data:
            intake[k] = (str(data.get(k) or "").strip()[: 4000 if k == "purpose" else 200]) or None
    for k, allowed, msg in (("system_type", TYPES, "Choose the type of AI."), ("sourcing", SOURCING, "Say whether it is bought or built."),
                            ("decision_impact", DECISION_IMPACT, "Choose what it decides about people."), ("autonomy", AUTONOMY, "Choose how much it acts on its own.")):
        if k in data:
            v = data.get(k) or None
            if v is not None and v not in allowed:
                errs.append({"field": k, "message": msg})
            intake[k] = v
    if "planned_go_live" in data:
        v = data.get("planned_go_live") or None
        if v is not None:
            try:
                v = date.fromisoformat(str(v)).isoformat()
            except ValueError:
                errs.append({"field": "planned_go_live", "message": "Enter a date."})
        intake["planned_go_live"] = v
    if "jurisdiction_ids" in data:
        ids = data.get("jurisdiction_ids") or []
        if not isinstance(ids, list) or any(not isinstance(i, str) or db.get(Jurisdiction, i) is None for i in ids):
            errs.append({"field": "jurisdiction_ids", "message": "Choose where the users are from the list."})
        else:
            intake["jurisdiction_ids"] = list(dict.fromkeys(ids))
    for k, allowed in (("data_categories", DATA_CATEGORIES), ("data_subjects", DATA_SUBJECTS)):
        if k in data:
            v = data.get(k)
            if v is None:
                intake[k] = None
            elif not isinstance(v, list) or any(x not in allowed for x in v):
                errs.append({"field": k, "message": "Choose from the list."})
            else:
                intake[k] = list(dict.fromkeys(v))
    if "public_facing" in data:
        intake["public_facing"] = None if data.get("public_facing") is None else bool(data.get("public_facing"))
    if "user_count" in data:
        v = data.get("user_count")
        try:
            intake["user_count"] = None if v in (None, "") else max(0, int(v))
        except (TypeError, ValueError):
            errs.append({"field": "user_count", "message": "Enter a whole number."})
    if errs:
        raise Invalid(errors=errs)
    out["intake"] = {k: intake.get(k) for k in INTAKE_KEYS if k in intake}
    return out


def missing_for_submit(ia: ImpactAssessment) -> list[dict]:
    i = ia.intake or {}
    errs = []
    for k, msg in (("purpose", "Say what the project is for."), ("tool_or_vendor", "Name the tool or vendor."), ("system_type", "Choose the type of AI."),
                   ("sourcing", "Say whether it is bought or built."), ("decision_impact", "Choose what it decides about people.")):
        if not i.get(k):
            errs.append({"field": k, "message": msg})
    if i.get("data_categories") is None:
        errs.append({"field": "data_categories", "message": "Choose the data it will use, or none of these."})
    if not i.get("jurisdiction_ids"):
        errs.append({"field": "jurisdiction_ids", "message": "Say where its users are."})
    return errs


def _intake_for_assess(db: Session, ia_or_body) -> dict:
    if isinstance(ia_or_body, ImpactAssessment):
        dept = db.get(Department, ia_or_body.department_id) if ia_or_body.department_id else None
        return dict(ia_or_body.intake or {}) | {"project_name": ia_or_body.project_name, "department_name": dept.name if dept else ""}
    return ia_or_body


def recompute(db: Session, ia: ImpactAssessment) -> None:
    a = assess(db, _intake_for_assess(db, ia))
    ia.proposed_tier, ia.tier_reason, ia.assessment_depth, ia.depth_sections, ia.matched_regulations = a["tier"], a["tier_reason"][:300], a["depth"], a["depth_sections"], a["laws"]


def next_reference(db: Session, org_id: str) -> str:
    refs = db.scalars(select(ImpactAssessment.reference).where(ImpactAssessment.organization_id == org_id))
    n = max((int(r[3:]) for r in refs if r and r[3:].isdigit()), default=0)
    return f"IA-{n + 1:03d}"


def create(db: Session, actor: User, org: Organization, data: dict) -> ImpactAssessment:
    v = clean_intake(db, org, data)
    ia = ImpactAssessment(organization_id=org.id, reference=next_reference(db, org.id), project_name=v["project_name"], department_id=v["department_id"],
                          intake=v["intake"], status="draft", created_by=actor.id, updated_by=actor.id, depth_sections=[], matched_regulations=[])
    db.add(ia)
    db.flush()
    recompute(db, ia)
    audit.record(db, actor_id=actor.id, action="impact.create", obj=ia, organization_id=org.id, summary=f"Started impact assessment {ia.reference} {ia.project_name}")
    return ia


def update(db: Session, actor: User, ia: ImpactAssessment, data: dict) -> ImpactAssessment:
    if ia.status != "draft":
        raise Conflict("Only a draft can be edited. Ask the Chief AI Compliance Officer to return it if it needs to change.")
    org = db.get(Organization, ia.organization_id)
    v = clean_intake(db, org, data, current=ia)
    for k in ("project_name", "department_id"):
        if k in v:
            setattr(ia, k, v[k])
    ia.intake, ia.updated_by = v["intake"], actor.id
    recompute(db, ia)
    audit.record(db, actor_id=actor.id, action="impact.edit", obj=ia, organization_id=ia.organization_id, summary=f"Edited {ia.reference} {ia.project_name}")
    return ia


def preparers(db: Session, ia: ImpactAssessment) -> set[str]:
    """Everyone who started, edited or submitted the project. None of them may review or decide it (spec §6 rule 2)."""
    from app.audit_log.models import AuditLog

    ids = {ia.created_by, ia.submitted_by}
    ids |= set(db.scalars(select(AuditLog.actor_id).where(AuditLog.object_id == ia.id, AuditLog.action.in_(("impact.create", "impact.edit", "impact.submit")))))
    return {i for i in ids if i}


def submit(db: Session, actor: User, ia: ImpactAssessment) -> ImpactAssessment:
    from app.notifications.service import notify

    if ia.status != "draft":
        raise Conflict("This project has already been submitted.")
    errs = missing_for_submit(ia)
    if errs:
        raise Invalid("Complete the required answers first.", errs)
    recompute(db, ia)
    ia.status, ia.submitted_by, ia.submitted_at, ia.updated_by = "in_review", actor.id, utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="impact.submit", obj=ia, organization_id=ia.organization_id,
                 after={"tier": ia.proposed_tier, "depth": ia.assessment_depth, "laws": [x["name"] for x in ia.matched_regulations if x.get("matched")]},
                 summary=f"Submitted {ia.reference} {ia.project_name} for review (Tier {ia.proposed_tier})")
    notify(db, [u for u in reviewers(db, ia) if u.id != actor.id], "impact_review", f"Review new AI project: {ia.project_name}",
           f"Tier {ia.proposed_tier}. Submitted by {actor.name}.", f"/projects/{ia.id}")
    return ia


# ---- people
def _with_role(db: Session, org_id: str, role: str, department_id: str | None = None) -> list[User]:
    from app.tenancy.models import RoleAssignment

    stmt = select(RoleAssignment.user_id).where(RoleAssignment.organization_id == org_id, RoleAssignment.role == role, RoleAssignment.deleted_at.is_(None))
    if department_id is not None:
        stmt = stmt.where(RoleAssignment.scope_type == "department", RoleAssignment.scope_id == department_id)
    users = [db.get(User, i) for i in set(db.scalars(stmt))]
    return sorted([u for u in users if u is not None and u.deleted_at is None and u.status != "disabled"], key=lambda u: u.name)


def dpo_required(db: Session, ia: ImpactAssessment) -> bool:
    return bool(_with_role(db, ia.organization_id, "dpo"))


def reviewers(db: Session, ia: ImpactAssessment) -> list[User]:
    return _with_role(db, ia.organization_id, "dept_compliance_lead", ia.department_id) + _with_role(db, ia.organization_id, "dpo") + _with_role(db, ia.organization_id, "caico")


def reviews(db: Session, ia: ImpactAssessment) -> dict[str, ImpactReview]:
    rows = db.scalars(select(ImpactReview).where(ImpactReview.impact_assessment_id == ia.id, ImpactReview.deleted_at.is_(None)).order_by(ImpactReview.reviewed_at))
    return {r.step: r for r in rows}


def review(db: Session, actor: User, ia: ImpactAssessment, step: str, recommendation: str, comment: str | None) -> ImpactReview:
    if ia.status != "in_review":
        raise Conflict("This project is not waiting for review.")
    if step not in REVIEW_STEPS:
        raise Invalid(errors=[{"field": "step", "message": "Choose the department or DPO review."}])
    if recommendation not in RECOMMENDATIONS:
        raise Invalid(errors=[{"field": "recommendation", "message": "Choose approve, approve with conditions or reject."}])
    if actor.id in preparers(db, ia):
        raise Forbidden("You prepared this project, so another reviewer must review it.")
    comment = " ".join(str(comment or "").split()) or None
    if recommendation != "approve" and not comment:
        raise Invalid(errors=[{"field": "comment", "message": "Say what the conditions are, or why it should be rejected."}])
    r = reviews(db, ia).get(step)
    if r is None:
        r = ImpactReview(organization_id=ia.organization_id, impact_assessment_id=ia.id, step=step, reviewer_id=actor.id, recommendation=recommendation, created_by=actor.id)
        db.add(r)
    r.reviewer_id, r.recommendation, r.comment, r.reviewed_at, r.updated_by = actor.id, recommendation, (comment or "")[:4000] or None, utcnow(), actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="impact.review", obj=ia, organization_id=ia.organization_id, after={"step": step, "recommendation": recommendation, "comment": comment},
                 summary=f"{STEP_LABELS[step]} review of {ia.reference}: {RECOMMENDATION_LABELS[recommendation]}")
    return r


# ---- decision
def decide(db: Session, actor: User, ia: ImpactAssessment, decision: str, note: str | None, conditions: list[dict] | None, link_register_system_id: str | None) -> ImpactAssessment:
    from app.notifications.service import notify
    from app.policy.sod import assert_not_self_approval

    if ia.status != "in_review":
        raise Conflict("This project is not waiting for a decision.")
    done = reviews(db, ia)
    if "department" not in done:
        raise Conflict("The Department Compliance Lead's review is needed before the decision.")
    if dpo_required(db, ia) and "dpo" not in done:
        raise Conflict("The Data Protection Officer's review is needed before the decision.")
    assert_not_self_approval(actor.id, *preparers(db, ia))
    errs = []
    if decision not in DECISIONS:
        errs.append({"field": "decision", "message": "Choose approved, approved with conditions or rejected."})
    note = (note or "").strip() or None
    if decision == "rejected" and not note:
        errs.append({"field": "note", "message": "Say why the project is rejected."})
    conds = [c for c in (conditions or []) if isinstance(c, dict)]
    if decision == "approved_with_conditions" and not conds:
        errs.append({"field": "conditions", "message": "Add at least one condition."})
    clean_conds = []
    for i, c in enumerate(conds if decision == "approved_with_conditions" else []):
        text = " ".join(str(c.get("text") or "").split())
        if not text:
            errs.append({"field": f"conditions.{i}.text", "message": "Describe the condition."})
        owner = c.get("owner_user_id") or None
        if owner:
            u = db.get(User, owner)
            if u is None or u.organization_id != ia.organization_id or u.deleted_at is not None:
                errs.append({"field": f"conditions.{i}.owner_user_id", "message": "Choose a person from the company's users."})
        due = c.get("due_on") or None
        if due:
            try:
                due = date.fromisoformat(str(due))
            except ValueError:
                errs.append({"field": f"conditions.{i}.due_on", "message": "Enter a date."})
        clean_conds.append({"text": text[:600], "owner_user_id": owner, "due_on": due})
    link = None
    if link_register_system_id and decision != "rejected":
        from app.register.models import RegisterSystem

        link = db.get(RegisterSystem, link_register_system_id)
        if link is None or link.organization_id != ia.organization_id or link.deleted_at is not None or link.stage == "retired":
            errs.append({"field": "link_register_system_id", "message": "Choose a system from the company's register."})
    if errs:
        raise Invalid(errors=errs)
    now = utcnow()
    ia.status, ia.decision, ia.decision_note, ia.decided_by, ia.decided_at, ia.updated_by = "decided", decision, note, actor.id, now, actor.id
    for c in clean_conds:
        db.add(ImpactCondition(organization_id=ia.organization_id, impact_assessment_id=ia.id, status="open", created_by=actor.id, **c))
    db.flush()
    if decision != "rejected":
        s = link or _create_register_system(db, actor, ia)
        ia.register_system_id = s.id
        _history(db, actor, ia, s)
    audit.record(db, actor_id=actor.id, action="impact.decide", obj=ia, organization_id=ia.organization_id,
                 after={"decision": decision, "note": note, "conditions": [c["text"] for c in clean_conds], "register_system_id": ia.register_system_id},
                 summary=f"{DECISION_LABELS[decision]}: {ia.reference} {ia.project_name}")
    people = [u for u in (db.get(User, ia.submitted_by) if ia.submitted_by else None,) if u is not None]
    people += [db.get(User, c.owner_user_id) for c in conditions_of(db, ia) if c.owner_user_id]
    notify(db, people, "impact_decided", f"{DECISION_LABELS[decision]}: {ia.project_name}", note, f"/projects/{ia.id}")
    return ia


def _create_register_system(db: Session, actor: User, ia: ImpactAssessment):
    from app.register.service import create_system

    i = ia.intake or {}
    org = db.get(Organization, ia.organization_id)
    owner = db.get(User, ia.submitted_by) if ia.submitted_by else None
    data = {"name": ia.project_name, "type": i.get("system_type") or "vendor_app", "sourcing": i.get("sourcing") or "vendor", "stage": "proposed",
            "department_id": ia.department_id, "purpose": i.get("purpose"), "decision_impact": i.get("decision_impact"), "user_count": i.get("user_count"),
            "owner_user_id": owner.id if owner is not None and owner.organization_id == ia.organization_id else None,
            "data": {"data_categories": i.get("data_categories") or [], "data_subjects": i.get("data_subjects") or []}}
    if i.get("system_type") == "agent" and i.get("autonomy"):
        data["autonomy"] = i["autonomy"]
    if i.get("tool_or_vendor") and (i.get("sourcing") or "vendor") == "vendor":
        data["vendor_name"] = i["tool_or_vendor"]
    return create_system(db, actor, org, data, reason=f"Approved new AI project {ia.reference}")


def _history(db: Session, actor: User, ia: ImpactAssessment, s) -> None:
    from app.register.history import add_entry

    laws = ", ".join(x["name"] for x in ia.matched_regulations or [] if x.get("matched"))[:2000]
    add_entry(db, actor, s, {"type": "impact_assessment", "occurred_on": utcnow().date().isoformat(),
                             "summary": f"Pre-deployment impact assessment {ia.reference}: {DECISION_LABELS[ia.decision].lower()} (Tier {ia.proposed_tier}, {ia.assessment_depth} assessment).",
                             "details": {"law": laws or None, "outcome": DECISION_LABELS[ia.decision], "next_due": (utcnow().date() + timedelta(days=365)).isoformat()}})


# ---- conditions
def conditions_of(db: Session, ia: ImpactAssessment) -> list[ImpactCondition]:
    return list(db.scalars(select(ImpactCondition).where(ImpactCondition.impact_assessment_id == ia.id, ImpactCondition.deleted_at.is_(None)).order_by(ImpactCondition.created_at, ImpactCondition.id)))


def get_condition(db: Session, ia: ImpactAssessment, cid: str) -> ImpactCondition:
    c = db.get(ImpactCondition, cid)
    if c is None or c.impact_assessment_id != ia.id or c.deleted_at is not None:
        raise NotFound()
    return c


def mark_met(db: Session, actor: User, ia: ImpactAssessment, c: ImpactCondition, note: str | None) -> ImpactCondition:
    note = (note or "").strip()
    if c.status == "closed":
        raise Conflict("This condition is already closed.")
    if not note:
        raise Invalid(errors=[{"field": "note", "message": "Say how the condition was met."}])
    c.status, c.met_note, c.met_by, c.met_at, c.updated_by = "met", note[:4000], actor.id, utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="impact.condition_met", obj=c, organization_id=c.organization_id, after={"note": c.met_note}, summary=f"Condition met on {ia.reference}: {c.text[:120]}")
    return c


def close_condition(db: Session, actor: User, ia: ImpactAssessment, c: ImpactCondition, reopen: bool = False, note: str | None = None) -> ImpactCondition:
    if c.status != "met":
        raise Conflict("Only a condition marked met can be closed or sent back.")
    if reopen:
        if not (note or "").strip():
            raise Invalid(errors=[{"field": "note", "message": "Say what is still missing."}])
        c.status, c.met_note = "open", f"{c.met_note}\n\nSent back: {note.strip()}"[:4000]
    else:
        c.status, c.closed_by, c.closed_at = "closed", actor.id, utcnow()
    c.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="impact.condition_closed" if not reopen else "impact.condition_reopened", obj=c, organization_id=c.organization_id,
                 summary=f"Condition {'closed' if not reopen else 'sent back'} on {ia.reference}: {c.text[:120]}")
    return c


# ---- independent opinion (Tier 3, billable)
def request_opinion(db: Session, actor: User, ia: ImpactAssessment):
    from app.sales.service import open_from_trigger

    if ia.proposed_tier != 3:
        raise Conflict("An independent opinion is offered for Tier 3 (high-risk) projects only.")
    if ia.opinion_opportunity_id:
        return ia
    o = open_from_trigger(db, ia.organization_id, "impact_assessment", ia.id, service=f"Independent opinion: {ia.project_name}", service_kind="advisory",
                          why_now=f"Tier 3 project {ia.reference} planned for go-live {(ia.intake or {}).get('planned_go_live') or 'soon'}",
                          system_ids=[ia.register_system_id] if ia.register_system_id else [], created_by=actor.id)
    ia.opinion_opportunity_id, ia.opinion_requested_by, ia.opinion_requested_at = o.id, actor.id, utcnow()
    audit.record(db, actor_id=actor.id, action="impact.opinion_requested", obj=ia, organization_id=ia.organization_id, summary=f"Asked Futran for an independent opinion on {ia.reference}")
    return ia
