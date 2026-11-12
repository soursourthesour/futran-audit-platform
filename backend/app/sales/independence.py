"""The independence flag on an opportunity (spec §4.3 rule 3, §4.7; plan "Shared names").

`flag_for(db, org_id)` is set when the company is a current audit client, had an engagement completed in the last 24
months, or has an open remediation item. It is computed whenever an opportunity is saved, shown on the record and drives
the Chief Auditor's approval. It builds on the v0.6 check in `app.sales.service` (current engagements), which still
refuses remediation work while a current engagement has findings."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.engagements.models import Engagement
from app.sales.service import current_engagements

RECENT_DAYS = 730  # 24 months


def flag_for(db: Session, org_id: str) -> tuple[bool, str]:
    """(flag, reason). A prospect has no engagements, so it is never flagged."""
    if current_engagements(db, org_id):
        return True, "A current audit client: an engagement is under way."
    since = utcnow() - timedelta(days=RECENT_DAYS)
    recent = db.scalar(select(Engagement.id).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None), Engagement.status.in_(("completed", "archived")),
                                                   Engagement.completed_at.is_not(None), Engagement.completed_at >= since).limit(1))
    if recent:
        return True, "A recent audit client: an engagement was completed in the last 24 months."
    from app.remediation.models import RemediationItem
    from app.remediation.service import OPEN

    if db.scalar(select(RemediationItem.id).where(RemediationItem.organization_id == org_id, RemediationItem.deleted_at.is_(None), RemediationItem.status.in_(OPEN)).limit(1)):
        return True, "The client has an open remediation item from a Futran audit."
    return False, ""


def refresh(db: Session, opp) -> None:
    """Recompute and store the flag on an opportunity (on every save)."""
    flag, why = flag_for(db, opp.organization_id)
    opp.independence_flag, opp.independence_reason = flag, (why or None)
