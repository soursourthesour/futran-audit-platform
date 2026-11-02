"""AI copilot endpoints (spec §21 F1, screen 25) and the engagement AI switch (rule 4). Futran only: a client never
reaches Futran's copilot (the client Q&A helper lives in app.ai.explain_router)."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai import copilot as cp
from app.ai import service as ai
from app.ai.models import AIInteraction
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.questionnaire import service as qs
from app.systems.service import get_system

router = APIRouter(tags=["ai"])


class SwitchIn(BaseModel):
    enabled: bool | None = None
    consent_note: str | None = None


class PrefillIn(BaseModel):
    sub_section: str
    file_ids: list[str] | None = None


class IdsIn(BaseModel):
    ids: list[str] = []


class ReasonIn(BaseModel):
    reason: str | None = None


def _engagement(db: Session, actor: Actor, engagement_id: str, action: Action) -> Engagement:
    e = authorize(db, actor, action, engagement_id=engagement_id)
    assert e is not None
    return e


def system_target(db: Session, actor: Actor, system_id: str, action: Action = Action.USE_COPILOT) -> qs.Target:
    s = get_system(db, system_id)
    if not actor.is_futran:
        raise NotFound()
    e = _engagement(db, actor, s.engagement_id, action)
    return qs.Target(e, s)


def interaction(db: Session, actor: Actor, interaction_id: str, action: Action = Action.USE_COPILOT) -> AIInteraction:
    i = db.get(AIInteraction, interaction_id)
    if i is None or i.deleted_at is not None or i.engagement_id is None or not actor.is_futran:
        raise NotFound()
    _engagement(db, actor, i.engagement_id, action)
    return i


# ---- rule 4: the switch
@router.get("/engagements/{engagement_id}/ai")
def get_switch(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return ai.switch_out(db, actor, _engagement(db, actor, engagement_id, Action.VIEW_ENGAGEMENT))


@router.put("/engagements/{engagement_id}/ai")
def put_switch(engagement_id: str, body: SwitchIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _engagement(db, actor, engagement_id, Action.MANAGE_AI_FEATURES)
    ai.set_switch(db, actor.user, e, body.enabled, body.consent_note)
    return ai.switch_out(db, actor, e)


# ---- screen 25
def _documents(db: Session, settings, t: qs.Target) -> list[dict]:
    out = []
    for f in ai.engagement_files(db, t.engagement, t.system_id):
        dt = ai.document_text(db, settings, f)
        out.append({"id": f.id, "filename": f.filename, "pages": len(dt.pages), "chars": dt.chars, "error": dt.error, "is_evidence": f.linked_type == "evidence"})
    return out


@router.get("/systems/{system_id}/copilot")
def get_copilot(system_id: str, request: Request, section: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = system_target(db, actor, system_id)
    ai.require_ai(t.engagement)
    settings = request.app.state.settings
    out = {"enabled": True, "documents": _documents(db, settings, t),
           "suggestions": cp.suggestions_out(db, t, cp.latest(db, t, "copilot_prefill", section)) if section else [],
           "interview_list": [ai.interaction_out(db, i) for i in cp.latest(db, t, "copilot_prefill") if i.follow_up == "interview" and i.status in ("suggested", "unsupported")],
           "can_view_log": ai._can(db, actor, Action.VIEW_AI_LOG, t.engagement)}
    return out


@router.post("/systems/{system_id}/copilot/prefill")
def post_prefill(system_id: str, body: PrefillIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = system_target(db, actor, system_id)
    authorize(db, actor, Action.VERIFY_SYSTEM_ANSWERS, engagement_id=t.engagement.id)
    rows = cp.prefill(db, request.app.state, request.app.state.settings, actor.user, t, body.sub_section, body.file_ids)
    return {"suggestions": cp.suggestions_out(db, t, rows)}


@router.post("/systems/{system_id}/copilot/accept-high")
def post_accept_high(system_id: str, body: IdsIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    t = system_target(db, actor, system_id)
    ai.require_ai(t.engagement)
    authorize(db, actor, Action.VERIFY_SYSTEM_ANSWERS, engagement_id=t.engagement.id)
    n, skipped = cp.accept_high(db, actor.user, t, body.ids)
    return {"accepted": n, "skipped": skipped}


@router.post("/ai/interactions/{interaction_id}/accept")
def post_accept(interaction_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    i = interaction(db, actor, interaction_id)
    ai.require_ai(db.get(Engagement, i.engagement_id))
    from app.ai import review

    if i.feature == "copilot_prefill":
        authorize(db, actor, Action.VERIFY_SYSTEM_ANSWERS, engagement_id=i.engagement_id)
        if body.get("create_finding"):
            authorize(db, actor, Action.RECORD_FINDINGS, engagement_id=i.engagement_id)
        cp.accept(db, actor.user, i, body)
    else:
        review.accept(db, actor, i, body)
    return ai.interaction_out(db, i)


@router.post("/ai/interactions/{interaction_id}/reject")
def post_reject(interaction_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    i = interaction(db, actor, interaction_id)
    ai.require_ai(db.get(Engagement, i.engagement_id))
    return ai.interaction_out(db, ai.reject(db, actor.user, i, body.reason))


@router.post("/ai/interactions/{interaction_id}/interview")
def post_interview(interaction_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    i = interaction(db, actor, interaction_id)
    return ai.interaction_out(db, cp.to_interview(db, actor.user, i))


@router.post("/ai/interactions/{interaction_id}/evidence-request")
def post_evidence_request(interaction_id: str, body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    i = interaction(db, actor, interaction_id)
    authorize(db, actor, Action.MANAGE_DOCUMENT_REQUESTS, engagement_id=i.engagement_id)
    return ai.interaction_out(db, cp.to_evidence_request(db, request.app.state.settings, actor.user, i, body))


# ---- evidence check, completeness review, ask, draft finding text, summaries
class EvidenceCheckIn(BaseModel):
    section: str | None = None
    code: str | None = None


class SignoffIn(BaseModel):
    signoff: int = 5


class AskIn(BaseModel):
    question: str | None = None


class SummaryIn(BaseModel):
    kind: str | None = None


@router.post("/systems/{system_id}/copilot/evidence-check")
def post_evidence_check(system_id: str, body: EvidenceCheckIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.ai import review

    t = system_target(db, actor, system_id)
    return {"items": review.evidence_check(db, request.app.state, request.app.state.settings, actor.user, t, body.section, body.code)}


@router.get("/systems/{system_id}/copilot/completeness")
def get_completeness(system_id: str, signoff: int = 5, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.ai import review

    t = system_target(db, actor, system_id)
    ai.require_ai(t.engagement)
    return review.completeness_out(db, t, signoff)


@router.post("/systems/{system_id}/copilot/completeness")
def post_completeness(system_id: str, body: SignoffIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.ai import review

    t = system_target(db, actor, system_id)
    review.completeness_out(db, t, body.signoff)  # validates the sign-off number before the model is called
    review.run_contradictions(db, request.app.state, request.app.state.settings, actor.user, t)
    return review.completeness_out(db, t, body.signoff)


@router.post("/systems/{system_id}/copilot/ask")
def post_ask(system_id: str, body: AskIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.ai import review

    t = system_target(db, actor, system_id)
    return ai.interaction_out(db, review.ask(db, request.app.state, request.app.state.settings, actor.user, t.engagement, t.system, body.question))


@router.post("/engagements/{engagement_id}/copilot/ask")
def post_engagement_ask(engagement_id: str, body: AskIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.ai import review

    if not actor.is_futran:
        raise NotFound()
    e = _engagement(db, actor, engagement_id, Action.USE_COPILOT)
    return ai.interaction_out(db, review.ask(db, request.app.state, request.app.state.settings, actor.user, e, None, body.question))


@router.post("/findings/{finding_id}/copilot/draft-text")
def post_draft_text(finding_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.ai import review
    from app.findings.models import Finding

    f = db.get(Finding, finding_id)
    if f is None or f.deleted_at is not None or not actor.is_futran:
        raise NotFound()
    _engagement(db, actor, f.engagement_id, Action.USE_COPILOT)
    authorize(db, actor, Action.RECORD_FINDINGS, engagement_id=f.engagement_id)
    return ai.interaction_out(db, review.draft_finding_text(db, request.app.state, request.app.state.settings, actor.user, f))


@router.post("/systems/{system_id}/copilot/summary")
def post_system_summary(system_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.ai import review

    t = system_target(db, actor, system_id)
    return ai.interaction_out(db, review.summary(db, request.app.state, request.app.state.settings, actor.user, t.engagement, "system", t.system))


@router.post("/engagements/{engagement_id}/copilot/summary")
def post_engagement_summary(engagement_id: str, body: SummaryIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.ai import review

    if not actor.is_futran:
        raise NotFound()
    e = _engagement(db, actor, engagement_id, Action.USE_COPILOT)
    return ai.interaction_out(db, review.summary(db, request.app.state, request.app.state.settings, actor.user, e, body.kind or "engagement"))


# ---- the engagement's AI interaction log (Chief Auditor, Lead Auditor, QA)
@router.get("/engagements/{engagement_id}/ai-log")
def get_ai_log(engagement_id: str, feature: str | None = None, status: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from sqlalchemy import func, select

    from app.systems.models import AISystem

    if not actor.is_futran:
        raise NotFound()
    e = _engagement(db, actor, engagement_id, Action.VIEW_AI_LOG)
    q = select(AIInteraction).where(AIInteraction.engagement_id == e.id, AIInteraction.deleted_at.is_(None))
    if feature:
        q = q.where(AIInteraction.feature == feature)
    if status:
        q = q.where(AIInteraction.status == status)
    rows = list(db.scalars(q.order_by(AIInteraction.created_at.desc()).limit(1000)))
    counts = dict(db.execute(select(AIInteraction.status, func.count()).where(AIInteraction.engagement_id == e.id, AIInteraction.deleted_at.is_(None)).group_by(AIInteraction.status)).all())
    systems = {s.id: f"{s.reference_id} {s.name}" for s in db.scalars(select(AISystem).where(AISystem.engagement_id == e.id))}
    from app.tenancy.models import Organization

    return {"engagement": {"id": e.id, "audit_ref": e.audit_ref, "client_id": e.client_id, "client": db.get(Organization, e.client_id).name},
            "switch": ai.switch_out(db, actor, e),
            "totals": {"suggestions": sum(counts.values()), "pending": counts.get("suggested", 0), "accepted": counts.get("accepted", 0), "edited": counts.get("edited", 0),
                       "rejected": counts.get("rejected", 0), "unsupported": counts.get("unsupported", 0), "calls": db.scalar(select(func.count(func.distinct(AIInteraction.call_id))).where(AIInteraction.engagement_id == e.id))},
            "rows": [ai.interaction_out(db, i) | {"system": systems.get(i.ai_system_id)} for i in rows]}
