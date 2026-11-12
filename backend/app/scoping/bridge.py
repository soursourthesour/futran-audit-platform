"""Calls into other Release 2 workstreams, each guarded so scoping works before they land:

- R1 catalog: `app.catalog.service.items_by_codes(db, codes)` and `current_version(db)` (plan, Shared names);
- R4 proposals: `app.proposals.service.create_from_questionnaire(db, questionnaire, actor)`;
- R2 opportunities: `app.sales.service.log` for the activity timeline and the `scoping` stage.
"""
import importlib
import logging

log = logging.getLogger(__name__)


def _module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def catalog_service():
    return _module("app.catalog.service")


def catalog_items(db, codes) -> dict | None:
    """{code: CatalogItem} for the codes the catalog has, or None when the catalog is not installed."""
    cat = catalog_service()
    if cat is None or not hasattr(cat, "items_by_codes"):
        return None
    return cat.items_by_codes(db, list(codes))


def catalog_version(db) -> int | None:
    cat = catalog_service()
    return cat.current_version(db) if cat is not None and hasattr(cat, "current_version") else None


def proposal_builder():
    """The R4 function that builds a proposal from a locked questionnaire, or None."""
    mod = _module("app.proposals.service")
    return getattr(mod, "create_from_questionnaire", None) if mod is not None else None


def list_price(item) -> float | None:
    for attr in ("list_price", "list", "price_list"):
        v = getattr(item, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def is_retired(item) -> bool:
    return getattr(item, "status", "active") == "retired"


def opportunity_contacts(db, opportunity_id: str) -> list[dict]:
    """R2's OpportunityContact rows as {id, name, title, email, role}; empty until R2 lands."""
    mod = _module("app.sales.models")
    model = getattr(mod, "OpportunityContact", None) if mod is not None else None
    if model is None:
        return []
    from sqlalchemy import select

    rows = db.scalars(select(model).where(model.opportunity_id == opportunity_id))
    out = []
    for c in rows:
        if getattr(c, "deleted_at", None) is not None or not getattr(c, "email", None):
            continue
        out.append({"id": c.id, "name": c.name, "title": getattr(c, "title", None), "email": c.email, "role": getattr(c, "contact_role", None)})
    return out
