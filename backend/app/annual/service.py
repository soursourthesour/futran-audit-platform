"""Annual review engagements and control reuse (spec §21 F16).

"Start annual review" on a completed engagement creates a draft engagement of type annual_review with
prior_engagement_id, for the next twelve months, copying the scope, laws, contacts, team, systems, answers and evidence
links. The draft then goes through the usual wizard review, submission and Chief Auditor approval.

Only what the client itself answered last year, on questions the client answers, is carried: the client's own values
(the client_* columns) become the new answer and the client's pre-fill (Response.source = carried_forward, nothing
verified). Auditor-only questions, the auditor's corrections and the auditor's verification are not carried; the auditor
answers and verifies again. Once the engagement is live the client confirms each carried answer unchanged or updates it;
an answer whose client value differs from the prior answer shows as changed for the auditor. Checklist evidence links are
carried but unconfirmed, so the auditor re-tests.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.annual.models import CarriedAnswer
from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, NotFound
from app.engagements.models import ClientContact, ClientRequirement, Engagement, EngagementTeam
from app.engagements.team import LEAD_ROLE, check_lead_independence
from app.engagements.service import create_engagement
from app.questionnaire.models import ChecklistResult, Question, Response
from app.scoring import scale
from app.systems.models import AISystem
from app.tenancy.models import Organization, User

SCOPE_FIELDS = ("frameworks", "business_processes", "data_environments", "geographic_scope", "exclusions", "systems_excluded", "planned_systems", "retention_years", "methodology_version")
SYSTEM_FIELDS = ("name", "reference_id", "version", "owner_user_id", "technical_owner_user_id", "department_id", "built_by", "vendor_id", "tool_ids", "assessment_depth", "register_system_id")


def _year_later(d):
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def start_annual_review(db: Session, actor: User, prior: Engagement) -> Engagement:
    if prior.status not in ("completed", "archived"):
        raise Conflict("An annual review starts from a completed engagement.")
    if db.scalar(select(Engagement.id).where(Engagement.prior_engagement_id == prior.id, Engagement.deleted_at.is_(None))):
        raise Conflict("An annual review has already been started from this engagement.")
    org = db.get(Organization, prior.client_id)
    start = prior.period_end + timedelta(days=1) if prior.period_end else None
    e = create_engagement(db, actor, org, name=f"{org.name} annual AI governance review", type="annual_review", prior_engagement_id=prior.id,
                          period_start=start, period_end=_year_later(prior.period_end) if prior.period_end else None, **{k: getattr(prior, k) for k in SCOPE_FIELDS})
    e.wizard_state = {"auto_name": False, "carried_from": prior.audit_ref}
    for r in db.scalars(select(ClientRequirement).where(ClientRequirement.engagement_id == prior.id, ClientRequirement.deleted_at.is_(None))):
        db.add(ClientRequirement(organization_id=r.organization_id, engagement_id=e.id, regulation_id=r.regulation_id, source=r.source, reason_text=r.reason_text, in_scope=r.in_scope,
                                 notes=r.notes, free_text=r.free_text, created_by=actor.id))
    for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == prior.id, ClientContact.deleted_at.is_(None))):
        db.add(ClientContact(organization_id=c.organization_id, engagement_id=e.id, contact_role=c.contact_role, name=c.name, title=c.title, email=c.email, phone=c.phone,
                             not_appointed=c.not_appointed, user_id=c.user_id, created_by=actor.id))
    notices = []
    for t in db.scalars(select(EngagementTeam).where(EngagementTeam.engagement_id == prior.id, EngagementTeam.deleted_at.is_(None))):
        if t.role == LEAD_ROLE:  # independence rule (spec §21 F7): a policy author cannot lead this year's audit
            try:
                check_lead_independence(db, prior.client_id, t.user_id)
            except Conflict as exc:
                notices.append(f"{exc.detail} They were not copied in as Lead Auditor.")
                continue
        db.add(EngagementTeam(organization_id=t.organization_id, engagement_id=e.id, user_id=t.user_id, role=t.role, created_by=actor.id))  # conflicts are confirmed again
    e.wizard_state = e.wizard_state | {"notices": notices}
    sys_map: dict[str | None, str | None] = {None: None}
    for s in db.scalars(select(AISystem).where(AISystem.engagement_id == prior.id, AISystem.deleted_at.is_(None)).order_by(AISystem.reference_id)):
        n = AISystem(organization_id=s.organization_id, engagement_id=e.id, status="client_prefill", source="carried", use_case_ids=[], created_by=actor.id,
                     **{k: getattr(s, k) for k in SYSTEM_FIELDS})
        db.add(n)
        db.flush()
        sys_map[s.id] = n.id
    now = utcnow()
    carried = 0
    client_qs = set(db.scalars(select(Question.id).where(Question.default_respondent == "client")))
    for r in db.scalars(select(Response).where(Response.engagement_id == prior.id, Response.deleted_at.is_(None), Response.client_status.is_not(None), Response.client_status != "unanswered")):
        if r.ai_system_id not in sys_map or r.question_id not in client_qs:
            continue  # the client's own answers to the client's own questions only
        ev = list(r.client_evidence_ids or [])
        n = Response(organization_id=r.organization_id, engagement_id=e.id, ai_system_id=sys_map[r.ai_system_id], question_id=r.question_id, value=r.client_value, detail=r.client_detail,
                     status=r.client_status, na_reason=r.client_na_reason, evidence_ids=ev, answered_side="client", answered_at=now, source="carried_forward",
                     client_value=r.client_value, client_detail=r.client_detail, client_status=r.client_status, client_na_reason=r.client_na_reason, client_evidence_ids=list(ev), created_by=actor.id)
        db.add(n)
        db.flush()
        db.add(CarriedAnswer(organization_id=r.organization_id, engagement_id=e.id, response_id=n.id, prior_response_id=r.id, prior_value=r.client_value, prior_status=r.client_status,
                             prior_detail=r.client_detail, prior_evidence_ids=list(ev), created_by=actor.id))
        carried += 1
    links = 0
    for c in db.scalars(select(ChecklistResult).where(ChecklistResult.engagement_id == prior.id, ChecklistResult.deleted_at.is_(None))):
        if c.ai_system_id not in sys_map or not c.evidence_ids:
            continue
        db.add(ChecklistResult(organization_id=c.organization_id, engagement_id=e.id, ai_system_id=sys_map[c.ai_system_id], checklist_item_id=c.checklist_item_id, confirmed=False,
                               evidence_ids=list(c.evidence_ids), auditor_note=f"Evidence carried forward from {prior.audit_ref}. Confirm it still holds.", created_by=actor.id))
        links += 1
    db.flush()
    audit.record(db, actor_id=actor.id, action="engagement.annual_review", obj=e, after={"prior": prior.audit_ref, "systems": len(sys_map) - 1, "answers": carried, "evidence_links": links},
                 summary=f"Started annual review {e.audit_ref} from {prior.audit_ref}: {len(sys_map) - 1} systems, {carried} answers and {links} evidence links carried forward")
    return e


def _status(ca: CarriedAnswer, r: Response) -> str:
    if (r.client_value, r.client_status) != (ca.prior_value, ca.prior_status):
        return "changed"
    return "confirmed" if ca.status == "confirmed" else "pending"


def _label(q: Question, value, status: str) -> str:
    if status == "na":
        return "Not applicable"
    if status == "not_yet_in_place":
        return "Not yet in place"
    if value in (None, "", []):
        return "Not answered"
    labels = {str(o["value"]): o["label"] for o in q.options or []}
    if isinstance(value, dict):  # a person (name and title) or another structured answer
        return ", ".join(str(v) for v in value.values() if v not in (None, "")) or "Not answered"
    if isinstance(value, list):
        return ", ".join(labels.get(str(v), str(v)) for v in value)
    return labels.get(str(value), str(value))


def carried_items(db: Session, e: Engagement, *, system_ids: set[str] | None = None, changed_only: bool = False, client: bool = False) -> dict:
    rows = db.execute(select(CarriedAnswer, Response, Question).join(Response, Response.id == CarriedAnswer.response_id).join(Question, Question.id == Response.question_id)
                      .where(CarriedAnswer.engagement_id == e.id, CarriedAnswer.deleted_at.is_(None)).order_by(Response.ai_system_id, Question.order)).all()
    systems = {s.id: s for s in db.scalars(select(AISystem).where(AISystem.engagement_id == e.id))}
    names = {k: f"{s.reference_id} {s.name}" for k, s in systems.items()}
    rows = sorted(rows, key=lambda x: (systems[x[1].ai_system_id].reference_id if x[1].ai_system_id in systems else "", x[2].order))  # organization-wide first, then by system
    items, counts = [], {"total": 0, "pending": 0, "confirmed": 0, "changed": 0}
    for ca, r, q in rows:
        if system_ids is not None and r.ai_system_id is not None and r.ai_system_id not in system_ids:
            continue
        if client and q.default_respondent != "client":
            continue  # the client never sees auditor questions
        st = _status(ca, r)
        counts["total"] += 1
        counts[st] += 1
        if changed_only and st != "changed":
            continue
        items.append({"response_id": r.id, "system_id": r.ai_system_id, "system": names.get(r.ai_system_id) if r.ai_system_id else "Organization-wide", "code": q.code, "label": q.label,
                      "status": st, "prior_value": ca.prior_value, "prior": {"value": ca.prior_value, "status": ca.prior_status, "text": _label(q, ca.prior_value, ca.prior_status)},
                      "current": {"value": r.client_value, "status": r.client_status, "text": _label(q, r.client_value, r.client_status or "unanswered")},
                      "decided_at": ca.decided_at.isoformat() if ca.decided_at else None})
    prior = db.get(Engagement, e.prior_engagement_id) if e.prior_engagement_id else None
    return {"engagement": {"id": e.id, "audit_ref": e.audit_ref, "status": e.status}, "prior_ref": prior.audit_ref if prior else None, "counts": counts, "items": items}


def _carried(db: Session, r: Response) -> CarriedAnswer:
    ca = db.scalar(select(CarriedAnswer).where(CarriedAnswer.response_id == r.id, CarriedAnswer.deleted_at.is_(None)))
    q = db.get(Question, r.question_id)
    if ca is None or q is None or q.default_respondent != "client":
        raise NotFound("This answer was not carried forward.")
    return ca


def confirm(db: Session, actor: User, r: Response) -> dict:
    ca = _carried(db, r)
    if _status(ca, r) == "changed":
        raise Conflict("This answer has been changed since last year, so there is nothing to confirm.")
    now = utcnow()
    ca.status, ca.decided_by, ca.decided_at = "confirmed", actor.id, now
    r.client_answered_by, r.client_answered_at = actor.id, now
    audit.record(db, actor_id=actor.id, action="carried_answer.confirm", obj=r, summary="Confirmed a carried-forward answer is unchanged")
    return {"response_id": r.id, "status": "confirmed"}


def confirm_unchanged(db: Session, actor: User, e: Engagement, system_ids: set[str] | None) -> int:
    n = 0
    now = utcnow()
    for ca, r in db.execute(select(CarriedAnswer, Response).join(Response, Response.id == CarriedAnswer.response_id).join(Question, Question.id == Response.question_id)
                            .where(CarriedAnswer.engagement_id == e.id, CarriedAnswer.deleted_at.is_(None), Question.default_respondent == "client")).all():
        if system_ids is not None and r.ai_system_id is not None and r.ai_system_id not in system_ids:
            continue
        if _status(ca, r) == "pending":
            ca.status, ca.decided_by, ca.decided_at = "confirmed", actor.id, now
            r.client_answered_by, r.client_answered_at = actor.id, now
            n += 1
    if n:
        audit.record(db, actor_id=actor.id, action="carried_answer.confirm_all", obj=e, after={"confirmed": n}, summary=f"Confirmed {n} carried-forward answers unchanged")
    return n


def year_over_year(db: Session, e: Engagement) -> dict | None:
    """Maturity, residual risk and rating per system against the prior engagement, matched by system reference."""
    from app.scoring.models import EngagementScorecard
    from app.scoring.service import latest

    prior = db.get(Engagement, e.prior_engagement_id) if e.prior_engagement_id else None
    if prior is None:
        return None
    cur = {s.reference_id: s for s in db.scalars(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.deleted_at.is_(None)))}
    old = {s.reference_id: s for s in db.scalars(select(AISystem).where(AISystem.engagement_id == prior.id, AISystem.deleted_at.is_(None)))}
    rows = []

    def fig(row, attr):
        v = getattr(row, attr) if row else None
        return v if v is not None else "Not scored yet"

    for ref in sorted(set(cur) | set(old)):
        a, b = old.get(ref), cur.get(ref)
        ra, rb = (latest(db, a) if a else None), (latest(db, b) if b else None)
        rows.append({"system": f"{ref} {(b or a).name}", "prior_maturity": fig(ra, "maturity"), "maturity": fig(rb, "maturity"), "prior_residual": fig(ra, "residual"), "residual": fig(rb, "residual"),
                     "prior_rating": scale.labelled(ra.final_rating) if ra and ra.final_rating else ("Not in scope" if a is None else "Not rated"),
                     "rating": scale.labelled(rb.final_rating) if rb and rb.final_rating else ("Not in scope" if b is None else "Not rated yet")})
    sa = db.scalar(select(EngagementScorecard).where(EngagementScorecard.engagement_id == prior.id))
    sb = db.scalar(select(EngagementScorecard).where(EngagementScorecard.engagement_id == e.id))
    year = lambda x: str(x.period_end.year) if x.period_end else (x.audit_ref or "")  # noqa: E731
    return {"prior_ref": prior.audit_ref, "prior_label": year(prior), "current_label": year(e) if year(e) != year(prior) else "this review", "systems": rows,
            "prior_overall_maturity": sa.overall_maturity if sa and sa.overall_maturity is not None else "Not scored", "overall_maturity": sb.overall_maturity if sb and sb.overall_maturity is not None else "Not scored yet",
            "prior_overall_rating": scale.labelled(sa.overall_rating) if sa and sa.overall_rating else "Not rated", "overall_rating": scale.labelled(sb.overall_rating) if sb and sb.overall_rating else "Not rated yet"}
