"""Scores for each AI system and the engagement roll-up (spec §19.2–19.5)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.engagements.models import Engagement, EngagementTeam
from app.findings.models import Finding
from app.questionnaire.models import Question, Response
from app.reference.models import RiskMethodology
from app.scoring import engine
from app.scoring.models import EngagementScorecard, SystemRiskScore
from app.systems.models import AISystem
from app.tenancy.models import User

# Which maturity domain a finding counts against, by template section (longest prefix wins).
SECTION_DOMAIN = {"3": "governance", "4": "governance", "5": "data", "6": "model", "6.2": "bias", "V": "model", "OS": "model", "7": "oversight", "8": "security", "8.3": "incident", "9": "vendor_risk"}
COMPARED = ("factor_scores", "eu_classification", "inherent", "domain_inputs", "domain_scores_proposed", "domain_scores_final", "domain_rationales", "maturity", "residual",
            "knockouts_triggered", "computed_rating", "override_rating", "override_rationale", "final_rating", "methodology_version")


def methodology(db: Session, version: str | None = None) -> engine.Methodology:
    row = db.scalar(select(RiskMethodology).where(RiskMethodology.version == version)) if version else None
    if row is None:
        rows = list(db.scalars(select(RiskMethodology)))
        if not rows:
            raise Conflict("No risk methodology is loaded. Load the reference data first.")
        row = max(rows, key=lambda r: tuple(int(x) for x in r.version.split(".") if x.isdigit()))
    return engine.Methodology.from_row(row)


def latest(db: Session, s: AISystem) -> SystemRiskScore | None:
    return db.scalar(select(SystemRiskScore).where(SystemRiskScore.ai_system_id == s.id, SystemRiskScore.deleted_at.is_(None)).order_by(SystemRiskScore.seq.desc()).limit(1))


def scoring_answers(db: Session, s: AISystem) -> dict:
    """Answers by question code for this system and its engagement. "Not yet in place" counts as "no" (golden rule 2)."""
    codes = {q.id: q.code for q in db.scalars(select(Question))}
    out: dict = {}
    for target in (None, s.id):
        rows = db.scalars(select(Response).where(Response.engagement_id == s.engagement_id, Response.deleted_at.is_(None), Response.ai_system_id.is_(None) if target is None else Response.ai_system_id == target))
        for r in rows:
            if r.status == "answered":
                out[codes.get(r.question_id, "")] = r.value
            elif r.status == "not_yet_in_place":
                out[codes.get(r.question_id, "")] = "no"
    return out


def _domain_of(section: str | None) -> str | None:
    if not section:
        return None
    for prefix in sorted(SECTION_DOMAIN, key=len, reverse=True):
        if section == prefix or section.startswith(prefix + "."):
            return SECTION_DOMAIN[prefix]
    return None


def domain_inputs(db: Session, s: AISystem) -> dict[str, dict]:
    """Per domain: share of applicable checklist items confirmed with evidence (system items plus the engagement-level ones
    shared by every system), and open High or Critical findings."""
    from app.questionnaire.service import Target, checklist_for, checklist_results

    e = db.get(Engagement, s.engagement_id)
    out: dict[str, dict] = {}
    for t in (Target(e, s), Target(e)):
        results = checklist_results(db, t)
        for item in checklist_for(db, t):
            d = out.setdefault(item.maturity_domain, {"applicable": 0, "confirmed": 0, "open_high_or_critical": 0})
            d["applicable"] += 1
            d["confirmed"] += bool(results.get(item.id) and results[item.id].confirmed)
    findings = db.scalars(select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None), Finding.severity.in_(["high", "critical"]),
                                                (Finding.ai_system_id == s.id) | Finding.ai_system_id.is_(None)))
    for f in findings:
        dom = _domain_of(f.template_section)
        if dom:
            out.setdefault(dom, {"applicable": 0, "confirmed": 0, "open_high_or_critical": 0})["open_high_or_critical"] += 1
    for d in out.values():
        d["pct"] = round(100 * d["confirmed"] / d["applicable"], 1) if d["applicable"] else None
    return out


def recalculate(db: Session, s: AISystem, *, finals: dict | None = None, rationales: dict | None = None, override: tuple | None = None, actor: User | None = None) -> SystemRiskScore | None:
    """Recompute and store the score unless the system is locked. Auditor decisions (final domain scores, rating override)
    carry forward from the previous row unless replaced here."""
    prev = latest(db, s)
    if s.status == "locked":
        return prev
    try:
        m = methodology(db, s.methodology_version)
    except Conflict:
        return prev
    answers = scoring_answers(db, s)
    eu = answers.get("3.3.08")
    inherent, _ = engine.inherent(engine.FactorInputs(engine.factor_scores(answers, m), eu_classification=eu), m)
    inputs = domain_inputs(db, s)
    weights = engine.domain_weights(s.built_by, s.assessment_depth, m)
    proposed = {d: (engine.proposed_domain_score(inputs[d]["pct"], inputs[d]["open_high_or_critical"]) if d in inputs and inputs[d]["pct"] is not None else None) for d in weights}
    final_scores = {k: v for k, v in dict(prev.domain_scores_final if prev else {}, **(finals or {})).items() if k in weights}
    rats = {k: v for k, v in dict(prev.domain_rationales if prev else {}, **(rationales or {})).items() if k in final_scores and v}
    mat = engine.maturity({d: final_scores.get(d) for d in weights}, s.built_by, s.assessment_depth, m)
    res = engine.residual(inherent, mat, m) if inherent is not None and mat is not None else None
    computed = engine.band(res, m) if res is not None else None
    kos = engine.knockouts(answers, m)
    ov_rating, ov_rationale, ov_by = override if override is not None else ((prev.override_rating, prev.override_rationale, prev.override_by) if prev else (None, None, None))
    final = ov_rating or engine.final_rating(computed, kos, eu_prohibited=str(eu or "").casefold() == "prohibited")
    row = SystemRiskScore(
        organization_id=s.organization_id, engagement_id=s.engagement_id, ai_system_id=s.id, seq=(prev.seq + 1) if prev else 1, methodology_version=m.version,
        factor_scores=engine.factor_scores(answers, m), eu_classification=str(eu) if eu else None, inherent=inherent, domain_inputs=inputs, domain_scores_proposed=proposed,
        domain_scores_final=final_scores, domain_rationales=rats, maturity=mat, residual=res, knockouts_triggered=[k.code for k in kos], computed_rating=computed,
        override_rating=ov_rating, override_rationale=ov_rationale, override_by=ov_by, final_rating=final, scored_by=actor.id if actor else (prev.scored_by if prev else None),
        created_by=actor.id if actor else None,
    )
    complete = inherent is not None and mat is not None
    if complete and s.status in ("not_started", "client_prefill", "in_review"):
        s.status = "scored"
    elif not complete and s.status == "scored":
        s.status = "in_review"
    if prev is not None and all(getattr(prev, k) == getattr(row, k) for k in COMPARED):
        return prev
    db.add(row)
    db.flush()
    return row


def _editable(db: Session, s: AISystem) -> tuple[SystemRiskScore, engine.Methodology]:
    if s.status == "locked":
        raise Conflict("Scores are locked for this system.")
    row = latest(db, s) or recalculate(db, s)
    if row is None:
        raise Conflict("This system cannot be scored yet.")
    return row, methodology(db, s.methodology_version)


def set_final_domain_score(db: Session, actor: User, s: AISystem, domain: str, score, rationale: str | None) -> SystemRiskScore:
    row, m = _editable(db, s)
    if domain not in engine.domain_weights(s.built_by, s.assessment_depth, m):
        raise NotFound("That domain is not scored for this system.")
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
        raise Invalid(errors=[{"field": "score", "message": "Choose a score from 1 to 5."}])
    rationale = " ".join(str(rationale or "").split()) or None
    proposed = row.domain_scores_proposed.get(domain)
    if (proposed is None or abs(score - proposed) > m.override_rationale_threshold) and not rationale:
        msg = "Give a rationale: the score differs from the proposed score by more than 1." if proposed is not None else "Give a rationale: there is no evidence-based proposed score for this domain."
        raise Invalid(errors=[{"field": "rationale", "message": msg}])
    new = recalculate(db, s, finals={domain: score}, rationales={domain: rationale}, actor=actor)
    audit.record(db, actor_id=actor.id, action="score.domain", obj=s, before={"final": row.domain_scores_final.get(domain), "proposed": proposed}, after={"domain": domain, "final": score, "rationale": rationale},
                 summary=f"Set {m.domains.get(domain, domain)} to {score} for {s.reference_id}")
    return new


def is_lead_auditor(db: Session, user: User, e: Engagement) -> bool:
    return db.scalar(select(EngagementTeam.id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.user_id == user.id, EngagementTeam.role == "chief_auditor", EngagementTeam.deleted_at.is_(None))) is not None


def override_rating(db: Session, actor: User, s: AISystem, rating: str | None, rationale: str | None) -> SystemRiskScore:
    """The Lead Auditor (the engagement's Chief Auditor) may raise or lower the final rating with a written rationale."""
    row, m = _editable(db, s)
    if not is_lead_auditor(db, actor, db.get(Engagement, s.engagement_id)):
        raise Forbidden("Only the engagement's Lead Auditor can change the final rating.")
    if rating is not None and rating not in engine.RATINGS:
        raise Invalid(errors=[{"field": "rating", "message": "Choose critical, high, medium or low."}])
    rationale = " ".join(str(rationale or "").split()) or None
    if rating is not None and not rationale:
        raise Invalid(errors=[{"field": "rationale", "message": "Explain why the rating differs from the computed one."}])
    new = recalculate(db, s, override=(rating, rationale if rating else None, actor.id if rating else None), actor=actor)
    audit.record(db, actor_id=actor.id, action="score.override", obj=s, before={"final_rating": row.final_rating}, after={"override": rating, "rationale": rationale, "final_rating": new.final_rating},
                 summary=f"{'Set' if rating else 'Cleared'} the final rating override for {s.reference_id}{f' to {rating}' if rating else ''}")
    return new


def lock_scores(db: Session, e: Engagement, actor: User | None = None) -> EngagementScorecard:
    """Called by sign-off 5: freeze every system's latest score and the engagement roll-up."""
    from app.systems.service import systems_for

    now = utcnow()
    for s in systems_for(db, e):
        row = recalculate(db, s, actor=actor)
        if row is not None and row.locked_at is None:
            row.locked_at = now
        s.status = "locked"
    sc = engagement_rollup(db, e)
    audit.record(db, actor_id=actor.id if actor else None, action="score.lock", obj=e, after={"overall_rating": sc.overall_rating}, summary=f"Locked the risk scores for {e.audit_ref}")
    return sc


def engagement_rollup(db: Session, e: Engagement) -> EngagementScorecard:
    """Overall rating = highest final system rating; maturity = inherent-risk-weighted mean of system maturity."""
    from app.systems.service import systems_for

    rows = [r for r in (latest(db, s) for s in systems_for(db, e)) if r is not None]
    rating = engine.worst(*(r.final_rating for r in rows))
    scored = [r for r in rows if r.inherent is not None and r.maturity is not None]
    weight = sum(r.inherent for r in scored)
    mat = engine.r2(sum(r.inherent * r.maturity for r in scored) / weight) if weight else None
    domains: dict[str, float] = {}
    for d in {k for r in scored for k in r.domain_scores_final}:
        have = [r for r in scored if d in r.domain_scores_final]
        w = sum(r.inherent for r in have)
        if w:
            domains[d] = engine.r2(sum(r.inherent * r.domain_scores_final[d] for r in have) / w)
    sc = db.scalar(select(EngagementScorecard).where(EngagementScorecard.engagement_id == e.id))
    if sc is None:
        sc = EngagementScorecard(organization_id=e.client_id, engagement_id=e.id)
        db.add(sc)
    sc.domain_scores, sc.overall_maturity, sc.overall_rating = domains, mat, rating
    e.overall_rating = rating
    db.flush()
    return sc
