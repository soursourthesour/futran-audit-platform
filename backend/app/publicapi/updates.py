"""Regulatory updates published to a client (WS-H, `app.regupdates`), for `GET /updates` and the
`regulatory_update.published` webhook.

An update reaches a client when it is published (after its second review), not withdrawn, not a watch item, and matched
to that client by a `RegulatoryAlert`. Nothing else of WS-H's data is read here.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session


def published_updates(db: Session, org_id: str) -> list[dict]:
    """[{id, reference, title, change_type, law, summary, todo, effective_on, source_url, published_at, published_at_dt}], newest first."""
    try:
        from app.regupdates.models import RegulatoryAlert, RegulatoryUpdate
    except ModuleNotFoundError:
        return []
    rows = db.execute(select(RegulatoryUpdate, RegulatoryAlert).join(RegulatoryAlert, RegulatoryAlert.update_id == RegulatoryUpdate.id).where(
        RegulatoryAlert.organization_id == org_id, RegulatoryAlert.deleted_at.is_(None), RegulatoryUpdate.status == "published",
        RegulatoryUpdate.withdrawn_at.is_(None), RegulatoryUpdate.watch.is_(False), RegulatoryUpdate.published_at.is_not(None)).order_by(RegulatoryUpdate.published_at.desc()))
    out = []
    for u, a in rows:
        out.append({"id": u.id, "reference": u.reference, "title": u.title, "change_type": u.change_type, "law": u.law_name, "summary": u.summary,
                    "todo": [x.strip() for x in (u.todo_text or "").splitlines() if x.strip()], "effective_on": u.effective_on.isoformat() if u.effective_on else None,
                    "source_url": u.source_url, "why_it_applies": a.match_reason, "published_at": u.published_at.isoformat() + "Z", "published_at_dt": u.published_at})
    return out
