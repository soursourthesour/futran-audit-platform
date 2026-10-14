from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.questionnaire.models import Question
from app.scoring import engine
from app.scoring import service as svc
from app.scoring.models import EngagementScorecard, SystemRiskScore
from app.systems.models import AISystem, Vendor
from app.systems.service import get_system, systems_for
from app.tenancy.models import Organization, User
from app.tenancy.people import current_engagement

router = APIRouter(tags=["scoring"])
CLIENT_STAGE = 7  # D18: the client sees scores from the draft report on


class DomainIn(BaseModel):
    score: int | float | str | None = None
    rationale: str | None = None


class OverrideIn(BaseModel):
    rating: str | None = None
    rationale: str | None = None


def _can_view(db: Session, actor: Actor, e: Engagement) -> None:
    authorize(db, actor, Action.VIEW_SCORES, engagement_id=e.id)
    if not actor.is_futran and e.stage < CLIENT_STAGE:
        raise Forbidden("Risk scores are shared with the draft report.")


def _label(db: Session, code: str, value) -> str | None:
    q = db.scalar(select(Question).where(Question.code == code).limit(1))
    if q is None or value in (None, "", []):
        return None
    labels = {str(o["value"]): o["label"] for o in q.options or []}
    if isinstance(value, list):
        return ", ".join(labels.get(str(v), str(v)) for v in value)
    return labels.get(str(value), str(value))


def score_out(db: Session, s: AISystem, row: SystemRiskScore | None, futran: bool) -> dict:
    m = svc.methodology(db, s.methodology_version)
    answers = svc.scoring_answers(db, s)
    vendor = db.get(Vendor, s.vendor_id) if s.vendor_id else None
    base = {"system": {"id": s.id, "reference_id": s.reference_id, "name": s.name, "built_by": s.built_by, "assessment_depth": s.assessment_depth, "status": s.status, "vendor": vendor.legal_name if vendor else None,
                       "engagement_id": s.engagement_id, "client_id": s.organization_id}, "methodology_version": m.version}
    if row is None:
        return base | {"inherent": None, "factors": [], "domains": [], "maturity": None, "residual": None, "computed_rating": None, "knockouts": [], "final_rating": None, "override": None, "locked": False}
    _, rows = engine.inherent(engine.FactorInputs(row.factor_scores, row.eu_classification), m)
    weights = engine.domain_weights(s.built_by, s.assessment_depth, m)
    triggered = set(row.knockouts_triggered or [])
    who = db.get(User, row.override_by) if row.override_by else None
    label = dict(m.domains)
    if s.built_by == "vendor":
        label["model"] = "Vendor assurance (replaces §6.1, §6.3)"
    out = base | {
        "inherent": row.inherent, "eu_classification": row.eu_classification,
        "factors": [{"key": r.key, "label": r.label, "question": r.question, "answer": _label(db, r.question, answers.get(r.question)) if "," not in r.question else None, "score": r.score, "weight": r.weight, "points": r.points} for r in rows],
        "domains": [{"key": d, "label": label.get(d, d), "weight": round(w, 4), "proposed": row.domain_scores_proposed.get(d), "final": row.domain_scores_final.get(d), "rationale": row.domain_rationales.get(d),
                     "pct_confirmed": (row.domain_inputs.get(d) or {}).get("pct"), "open_findings": (row.domain_inputs.get(d) or {}).get("open_high_or_critical", 0)} for d, w in weights.items()],
        "maturity": row.maturity, "control_effectiveness": round(engine.control_effectiveness(row.maturity), 4) if row.maturity is not None else None, "residual": row.residual,
        "computed_rating": row.computed_rating,
        "knockouts": [{"code": k["code"], "label": k["label"], "force": k["force"], "triggered": k["code"] in triggered} for k in m.knockout_rules],
        "final_rating": row.final_rating, "override": {"rating": row.override_rating, "rationale": row.override_rationale, "by": who.name if who else None} if row.override_rating else None,
        "locked": row.locked_at is not None or s.status == "locked", "bands": m.bands, "max_control_reduction": m.max_control_reduction,
    }
    if not futran:
        out.pop("bands", None)
    return out


@router.get("/systems/{system_id}/score")
def get_score(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    s = get_system(db, system_id)
    e = db.get(Engagement, s.engagement_id)
    _can_view(db, actor, e)
    row = svc.latest(db, s) or (svc.recalculate(db, s) if actor.is_futran else None)
    out = score_out(db, s, row, actor.is_futran)
    if actor.is_futran:
        out["is_lead_auditor"] = svc.is_lead_auditor(db, actor.user, e)
        out["can_score"] = True
        try:
            authorize(db, actor, Action.SCORE_SYSTEM, engagement_id=e.id)
        except (Forbidden, NotFound):
            out["can_score"] = False
    return out


@router.put("/systems/{system_id}/score/domains/{domain}")
def put_domain(system_id: str, domain: str, body: DomainIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    s = get_system(db, system_id)
    authorize(db, actor, Action.SCORE_SYSTEM, engagement_id=s.engagement_id)
    score = body.score if isinstance(body.score, int) else (int(body.score) if isinstance(body.score, str) and body.score.isdigit() else body.score)
    row = svc.set_final_domain_score(db, actor.user, s, domain, score, body.rationale)
    return score_out(db, s, row, True)


@router.put("/systems/{system_id}/score/override")
def put_override(system_id: str, body: OverrideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    s = get_system(db, system_id)
    authorize(db, actor, Action.SCORE_SYSTEM, engagement_id=s.engagement_id)
    row = svc.override_rating(db, actor.user, s, body.rating or None, body.rationale)
    return score_out(db, s, row, True)


@router.get("/clients/{client_id}/scorecard")
def scorecard(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    _can_view(db, actor, e)
    sc = svc.engagement_rollup(db, e) if actor.is_futran else db.scalar(select(EngagementScorecard).where(EngagementScorecard.engagement_id == e.id))
    systems = [{"id": s.id, "reference_id": s.reference_id, "name": s.name, "final_rating": r.final_rating if r else None, "inherent": r.inherent if r else None, "maturity": r.maturity if r else None}
               for s in systems_for(db, e) for r in [svc.latest(db, s)]]
    return {"overall_rating": sc.overall_rating if sc else None, "overall_maturity": sc.overall_maturity if sc else None, "domain_scores": sc.domain_scores if sc else {}, "systems": systems}
