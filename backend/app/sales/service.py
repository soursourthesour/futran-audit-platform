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
