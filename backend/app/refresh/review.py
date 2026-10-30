"""The M3 review queue (spec §25.3 steps 6–7, §25.7). Only the Chief Auditor approves. Low-confidence and new-law
changes need a second reviewer (QA Reviewer or legal review) who is not the approver. On approval a law change becomes
a new LawVersion (regulatory master's versioning) and a case change updates the case; affected clients get a waiting
client alert (A1) and Sales gets an opportunity (S1)."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Invalid
from app.litigation.models import STAGES, Case, CaseClientMatch
from app.litigation.service import add_timeline, match_case, touch
from app.notifications.service import notify
from app.refresh.models import RefreshProposalMeta
from app.refresh.service import OPEN_STATUSES
from app.regmaster.models import ChangeImpact, ProposedChange
from app.tenancy.models import User

ACTIONS = ("approve", "edit_approve", "hold", "reject", "legal_review")


def meta_for(db: Session, change: ProposedChange) -> RefreshProposalMeta:
    """Bookkeeping row; created on demand for changes proposed outside a refresh (Admin edits, Auditor suggestions)."""
    m = db.get(RefreshProposalMeta, change.id)
    if m is None:
        from app.regmaster.changes import needs_second_review

        m = RefreshProposalMeta(proposed_change_id=change.id, kind="law", run_ids=[change.refresh_run_id] if change.refresh_run_id else [], seen_count=1,
                                needs_second_review=needs_second_review(change), claude_confidence=change.confidence)
        db.add(m)
        db.flush()
    return m


def kind_of(db: Session, change: ProposedChange) -> str:
    m = db.get(RefreshProposalMeta, change.id)
    return m.kind if m else "law"


def _check_open(change: ProposedChange) -> None:
    if change.status not in OPEN_STATUSES:
        raise Conflict("This change has already been decided.")


def _parse_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError as exc:
        raise Invalid(errors=[{"field": "new_value", "message": "Use a date like 2027-01-01."}]) from exc


def apply_case_change(db: Session, change: ProposedChange, meta: RefreshProposalMeta, value, actor: User) -> Case:
    if change.field_path == "new_case":
        v = value if isinstance(value, dict) else {}
        if not v.get("name") or v.get("stage") not in STAGES:
            raise Invalid("A new case needs a name and a stage.")
        case = Case(jurisdiction_id=change.jurisdiction_id, name=v["name"][:300], court=v.get("court"), docket_ref=v.get("docket_ref"), area=v.get("area") or "To classify",
                    stage=v["stage"], description=v.get("description"), last_update_on=_parse_date(v.get("last_update_on")) or today(), origin="claude",
                    sources=[{"title": "Source of the proposal", "url": change.source_url}] if change.source_url else [], timeline=[], match_rule={},
                    created_by=actor.id, updated_by=actor.id)
        add_timeline(case, case.stage)
        db.add(case)
        db.flush()
        meta.case_id = case.id
        return case
    case = db.get(Case, meta.case_id)
    if case is None:
        raise Conflict("The case no longer exists.")
    field = change.field_path.split(".", 1)[1]
    if field == "stage":
        if value not in STAGES:
            raise Invalid(errors=[{"field": "new_value", "message": f"Choose a stage: {', '.join(STAGES)}."}])
        case.stage = value
        add_timeline(case, value, case.stage_note)
        case.last_update_on = today()
    elif field == "last_update_on":
        case.last_update_on = _parse_date(value)
    else:
        setattr(case, field, value)
    touch(case, actor.id)
    db.flush()
    match_case(db, case)
    return case


def apply_law_change(db: Session, change: ProposedChange, actor: User, value, edited: bool, note: str | None) -> None:
    """The regulatory master writes the new LawVersion and versions its requirements and role maps (WS-A)."""
    from app.regmaster.changes import apply_changes

    apply_changes(db, [change], actor.id, edited={change.id: value} if edited else None, note=note)


def _after_approval(db: Session, settings: Settings, change: ProposedChange, meta: RefreshProposalMeta, actor: User, case: Case | None) -> None:
    from app.clientalerts.service import queue_for_case, queue_for_change
    from app.sales.service import IndependenceError, open_from_trigger
    from app.staffalerts.service import resolve_run_alerts

    if not meta.update_letters:
        for imp in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == change.id)):
            imp.letter_update_needed = False
    if meta.kind == "litigation" and case is not None:
        if meta.notify_clients:
            queue_for_case(db, settings, case, actor_id=actor.id)
        for m in db.scalars(select(CaseClientMatch).where(CaseClientMatch.case_id == case.id)):
            try:
                open_from_trigger(db, m.organization_id, "case", f"{case.id}:v{case.version}", service=f"Briefing and review of AI like that in {case.name}"[:200],
                                  service_kind="advisory", why_now=f"{case.name}: {change.summary}", system_ids=list(m.ai_system_ids or []), created_by=actor.id)
            except IndependenceError:
                pass
    elif meta.kind == "law":
        if meta.notify_clients:
            queue_for_change(db, settings, change, actor_id=actor.id)
        trigger = "new_law" if change.change_type == "new_law" else "law_change"
        for imp in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == change.id)):
            try:
                open_from_trigger(db, imp.organization_id, trigger, change.id, service="Readiness review for the change"[:200], service_kind="readiness",
                                  why_now=change.summary, system_ids=list(imp.ai_system_ids or []), created_by=actor.id)
            except IndependenceError:
                pass
    for run_id in meta.run_ids or []:
        resolve_run_alerts(db, run_id)


def decide(db: Session, settings: Settings, change: ProposedChange, actor: User, action: str, *, new_value=None, note: str | None = None,
           notify_clients: bool | None = None, update_letters: bool | None = None) -> ProposedChange:
    if action not in ACTIONS:
        raise Invalid(errors=[{"field": "action", "message": "Unknown decision."}])
    _check_open(change)
    meta = meta_for(db, change)
    now = utcnow()
    if notify_clients is not None:
        meta.notify_clients = notify_clients
    if update_letters is not None:
        meta.update_letters = update_letters
    if action in ("approve", "edit_approve"):
        if meta.needs_second_review and meta.second_review_outcome != "concur":
            if meta.second_review_outcome == "object":
                raise Conflict("The second reviewer objected to this change. Reject it, or ask for another review.")
            raise Conflict("This change needs a second reviewer (QA Reviewer or legal review) before approval.")
        if change.second_reviewer_id and change.second_reviewer_id == actor.id:
            raise Conflict("The second reviewer and the approver must be a different person.")
        value = change.new_value
        if action == "edit_approve":
            if new_value is None:
                raise Invalid(errors=[{"field": "new_value", "message": "Enter the corrected value."}])
            value = new_value
            meta.edited_value = new_value
        case = None
        if meta.kind == "litigation":
            case = apply_case_change(db, change, meta, value, actor)
            change.status = "approved" if action == "approve" else "edited_approved"
            change.reviewer_id, change.reviewed_at, change.review_note = actor.id, now, note
        else:
            apply_law_change(db, change, actor, value, action == "edit_approve", note)
        db.flush()
        _after_approval(db, settings, change, meta, actor, case)
    else:
        from app.regmaster.changes import decide as master_decide

        master_decide(db, change, {"hold": "held", "reject": "rejected", "legal_review": "legal_review"}[action], actor.id, note)
        if action == "legal_review":
            meta.needs_second_review = True
            meta.second_review_outcome = None
            _notify_reviewers(db, change, "Legal review requested", f"{actor.name} asks for a legal review: {change.summary}")
        if action == "reject":
            from app.staffalerts.service import resolve_run_alerts

            for run_id in meta.run_ids or []:
                resolve_run_alerts(db, run_id)
    audit.record(db, actor_id=actor.id, action=f"reg_change.{change.status}", object_type="ProposedChange", object_id=change.id, organization_id=actor.organization_id,
                 summary=f"{change.status.replace('_', ' ').capitalize()}: {change.summary}"[:500], after={"status": change.status, "note": note, "edited": action == "edit_approve"})
    db.flush()
    return change


def _notify_reviewers(db: Session, change: ProposedChange, title: str, body: str) -> None:
    from app.staffalerts.service import futran_users_with

    notify(db, futran_users_with(db, {"qa_reviewer", "legal_reviewer"}), "second_review", title, body, link=f"/reg/refresh?change={change.id}")


def second_review(db: Session, change: ProposedChange, actor: User, outcome: str, note: str) -> ProposedChange:
    if outcome not in ("concur", "object"):
        raise Invalid(errors=[{"field": "outcome", "message": "Concur or object."}])
    _check_open(change)
    meta = meta_for(db, change)
    meta.second_review_outcome, meta.second_review_note = outcome, note
    change.second_reviewer_id, change.second_reviewed_at = actor.id, utcnow()
    if change.status == "legal_review":
        change.status = "pending"
    from app.staffalerts.service import futran_users_with

    notify(db, futran_users_with(db, {"chief_auditor"}), "second_review_done", f"Second review: {'concurs' if outcome == 'concur' else 'objects'}",
           f"{actor.name} on “{change.summary}”: {note}", link=f"/reg/refresh?change={change.id}")
    audit.record(db, actor_id=actor.id, action=f"reg_change.second_review_{outcome}", object_type="ProposedChange", object_id=change.id, organization_id=actor.organization_id,
                 summary=f"Second review ({outcome}): {change.summary}"[:500])
    db.flush()
    return change


def assign_reviewer(db: Session, change: ProposedChange, actor: User, user: User) -> None:
    meta = meta_for(db, change)
    meta.assigned_reviewer_id = user.id
    notify(db, [user], "second_review", "A change needs your second review", f"{actor.name} asks you to review: {change.summary}", link=f"/reg/refresh?change={change.id}")
