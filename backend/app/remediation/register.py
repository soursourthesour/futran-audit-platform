"""Wires management responses into sign-off 6, the final report and the weekly overdue digest."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.notifications import jobs
from app.remediation import service
from app.remediation.models import RemediationItem
from app.reports import service as reports
from app.signoffs import service as so_svc

so_svc.PRECONDITIONS[6] = [service.signoff6_unmet]
so_svc.STATEMENTS[6] = service.plan_statement
if service.management_responses_context not in reports.CONTEXT_HOOKS:
    reports.CONTEXT_HOOKS.append(service.management_responses_context)


def _overdue_remediation(db: Session, today: date) -> list:
    """Items from management responses (commitments are reported by their own source)."""
    out = []
    for item in db.scalars(select(RemediationItem).where(RemediationItem.deleted_at.is_(None), RemediationItem.commitment_id.is_(None), RemediationItem.status.in_(service.OPEN), RemediationItem.due_date < today)):
        owner = service.item_out(db, item)["owner"] or "Unassigned"
        out.append(jobs.OverdueItem(item.organization_id, item.engagement_id, owner, item.action[:300], item.due_date, "remediation"))
    return out


if not any(getattr(f, "__name__", "") == "_overdue_remediation" for f in jobs.DIGEST_SOURCES):
    jobs.DIGEST_SOURCES.append(_overdue_remediation)
