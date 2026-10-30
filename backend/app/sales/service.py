"""Opportunities: automatic triggers, Chief Auditor approval and the independence rule (spec §27.5)."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import Conflict
from app.engagements.models import Engagement
from app.findings.models import Finding
from app.register.models import RegisterSystem
from app.sales.models import Opportunity, OpportunityActivity

CURRENT_ENGAGEMENT = ("pending_approval", "initiated", "in_progress")


class IndependenceError(Conflict):
    def __init__(self):
        super().__init__("Futran does not sell the fix for a finding it raised in the same engagement. This client has findings in a current audit.")


def current_engagements(db: Session, org_id: str) -> list[Engagement]:
    return list(db.scalars(select(Engagement).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None), Engagement.status.in_(CURRENT_ENGAGEMENT))))


def is_current_audit_client(db: Session, org_id: str) -> bool:
    return bool(current_engagements(db, org_id))


def check_independence(db: Session, org_id: str, service_kind: str) -> None:
    """Remediation work is refused while a current engagement for the client has findings (open question 9 applies
    to work after the engagement closes)."""
    if service_kind != "remediation":
        return
    ids = [e.id for e in current_engagements(db, org_id)]
    if ids and db.scalar(select(Finding.id).where(Finding.engagement_id.in_(ids), Finding.deleted_at.is_(None)).limit(1)):
        raise IndependenceError()


def system_types(db: Session, system_ids: list[str]) -> list[str]:
    out: list[str] = []
    for sid in system_ids:
        s = db.get(RegisterSystem, sid)
        if s is not None and s.type not in out:
            out.append(s.type)
    return out


def log(db: Session, opp: Opportunity, kind: str, summary: str, by_id: str | None, at: datetime | None = None) -> OpportunityActivity:
    a = OpportunityActivity(opportunity_id=opp.id, kind=kind, summary=summary, by_id=by_id, at=at or utcnow())
    db.add(a)
    db.flush()
    return a


def open_from_trigger(db: Session, org_id: str, trigger: str, trigger_ref: str | None, *, service: str, why_now: str, service_kind: str = "other",
                      system_ids: list[str] | None = None, addon_status: str | None = None, owner_id: str | None = None,
                      value: int | None = None, created_by: str | None = None) -> Opportunity:
    """Create the opportunity a trigger implies, once per client, trigger and reference."""
    if trigger_ref is not None:
        existing = db.scalar(select(Opportunity).where(Opportunity.organization_id == org_id, Opportunity.trigger == trigger, Opportunity.trigger_ref == trigger_ref))
        if existing is not None:
            return existing
    check_independence(db, org_id, service_kind)
    ids = list(system_ids or [])
    o = Opportunity(
        organization_id=org_id, trigger=trigger, trigger_ref=trigger_ref, service=service[:200], service_kind=service_kind, why_now=(why_now or "")[:300],
        system_ids=ids, system_types=system_types(db, ids), addon_status=addon_status, owner_id=owner_id, value=value,
        needs_ca_approval=is_current_audit_client(db, org_id), created_by=created_by, stage="new",
    )
    db.add(o)
    db.flush()
    return o


def can_send_offer(o: Opportunity) -> bool:
    return not o.needs_ca_approval or o.ca_decision == "approved"


def open_effective_date_opportunities(db: Session, on) -> list[Opportunity]:
    """Daily: a law the client is in scope of reaches its compliance (or effective) date within 90 days (§27.5).
    Returns only the opportunities created today; one per client, law and date."""
    from app.laws.models import Regulation
    from app.regmaster.models import ClientLawApplicability, LawVersion

    from app.laws.publish import chain_ids
    from app.regmaster.versioning import deadline_keys

    out = []
    live = (Regulation.current_version_id.is_not(None), Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None))
    for reg in db.scalars(select(Regulation).where(*live)):
        v = db.get(LawVersion, reg.current_version_id)
        d = (v.compliance_on or v.effective_on) if v else None
        if d is None or not 0 <= (d - on).days <= 90:
            continue
        ids = chain_ids(db, reg.id) or [reg.id]
        ref, same = deadline_keys(db, reg, d)  # one per client, law and date (a new version with the same date is not news)
        rows = db.scalars(select(ClientLawApplicability).where(ClientLawApplicability.regulation_id.in_(ids), ClientLawApplicability.in_scope.is_(True), ClientLawApplicability.deleted_at.is_(None)))
        for org_id in dict.fromkeys(r.organization_id for r in rows):
            if db.scalar(select(Opportunity.id).where(Opportunity.organization_id == org_id, Opportunity.trigger == "effective_date", Opportunity.trigger_ref.in_(same)).limit(1)):
                continue
            try:
                out.append(open_from_trigger(db, org_id, "effective_date", ref, service=f"{reg.short_name} readiness review"[:200], service_kind="readiness",
                                             why_now=f"{reg.short_name} applies from {d.day} {d:%B %Y}"))
            except IndependenceError:
                continue
    return out


def tracing_candidates(db: Session) -> dict[str, list[RegisterSystem]]:
    """Live or about-to-go-live systems for which the tracing add-on is recommended (§27.3): Tier 3, an agent
    that acts (not suggest-only), or a past incident in its history log. Systems the add-on already covers, or for which
    it waits for the client's approval, are left out (WS-E)."""
    from app.register.models import HistoryEntry
    from app.tracing.addons import covered_ids

    out: dict[str, list[RegisterSystem]] = {}
    covered: dict[str, set[str]] = {}
    q = select(RegisterSystem).where(RegisterSystem.deleted_at.is_(None), RegisterSystem.stage.in_(("ready_for_go_live", "live")))
    for s in db.scalars(q.order_by(RegisterSystem.reference)):
        if s.organization_id not in covered:
            covered[s.organization_id] = covered_ids(db, s.organization_id)
        if s.id in covered[s.organization_id]:
            continue
        incident = db.scalar(select(HistoryEntry.id).where(HistoryEntry.register_system_id == s.id, HistoryEntry.type == "incident", HistoryEntry.deleted_at.is_(None)).limit(1))
        if s.risk_tier == 3 or (s.type == "agent" and s.autonomy in ("acts_with_approval", "autonomous")) or incident:
            out.setdefault(s.organization_id, []).append(s)
    return out


def open_recommended_addon_opportunities(db: Session) -> list[Opportunity]:
    """Daily: one opportunity per client with systems for which tracing is recommended and not yet requested."""
    made = []
    for org_id, systems in tracing_candidates(db).items():
        ref = f"tracing:{org_id}"
        if db.scalar(select(Opportunity.id).where(Opportunity.organization_id == org_id, Opportunity.trigger.in_(("recommended_addon", "unlock_request")), Opportunity.trigger_ref == ref)):
            continue
        n = len(systems)
        made.append(open_from_trigger(db, org_id, "recommended_addon", ref, service=f"Tracing module · {n} {'system' if n == 1 else 'systems'}", service_kind="addon",
                                      why_now="Tier 3 or acting agent systems without tracing", system_ids=[s.id for s in systems], addon_status="recommended"))
    return made
