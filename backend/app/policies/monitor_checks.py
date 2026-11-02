"""Monitoring check "Policy past review date" (spec §21 F7 and F3): one outcome per published policy built in the
policy builder. Past its review date: failed; within 30 days of it: attention. Reads only."""
from datetime import timedelta

from sqlalchemy import select

from app.core.clock import today
from app.monitoring.registry import CheckOutcome, register_check
from app.policies.models import PolicyDocument

SOON_DAYS = 30


def policy_past_review_date(db, org) -> list[CheckOutcome]:
    out = []
    rows = db.scalars(select(PolicyDocument).where(PolicyDocument.organization_id == org.id, PolicyDocument.deleted_at.is_(None), PolicyDocument.status == "published")
                      .order_by(PolicyDocument.review_due))
    for p in rows:
        if p.review_due is None:
            continue
        if p.review_due < today():
            status, detail = "failed", f"Review was due {p.review_due:%d %b %Y}"
        elif p.review_due <= today() + timedelta(days=SOON_DAYS):
            status, detail = "attention", f"Review due {p.review_due:%d %b %Y}"
        else:
            status, detail = "healthy", f"Next review {p.review_due:%d %b %Y}"
        out.append(CheckOutcome(p.id, p.title, status, detail, f"/policies/{p.id}", action="open" if status != "healthy" else None))
    return out


register_check("policy_past_review_date", "Published policy past its review date", "medium", "monthly", "policy", policy_past_review_date)
