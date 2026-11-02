"""Regulatory updates published to a client, for `GET /updates` and the `regulatory_update.published` webhook.

The updates themselves belong to WS-H (`app.regupdates`). This reads them only when that package is installed and offers
`published_for_client(db, org_id)`; otherwise there is nothing to serve and the list is empty.
"""
import importlib
from datetime import datetime

from sqlalchemy.orm import Session


def published_updates(db: Session, org_id: str) -> list[dict]:
    """[{id, title, change_type, summary, effective_on, published_at, published_at_dt}] for this client, newest first."""
    try:
        mod = importlib.import_module("app.regupdates.service")
    except ModuleNotFoundError:
        return []
    fn = getattr(mod, "published_for_client", None)
    if fn is None:
        return []
    out = []
    for u in fn(db, org_id):
        get = (lambda k, u=u: u.get(k)) if isinstance(u, dict) else (lambda k, u=u: getattr(u, k, None))
        at = get("published_at")
        out.append({"id": get("id"), "title": get("title"), "change_type": get("change_type"), "summary": get("summary"),
                    "effective_on": (get("effective_on") or get("effective_date") or None) and str(get("effective_on") or get("effective_date")),
                    "published_at": at.isoformat() + "Z" if isinstance(at, datetime) else at, "published_at_dt": at if isinstance(at, datetime) else None})
    return out
