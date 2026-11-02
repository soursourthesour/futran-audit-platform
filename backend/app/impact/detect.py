"""Reassessment triggers detected from register edits (spec §21 F8): system version, new data type, new jurisdiction,
new group of people, vendor change. Called by `register.service.update_system` (every single, bulk or CSV edit) and
`register.service.add_law`.

Only systems whose assessment can go out of date are watched: in development, ready for go-live or live, and a proposed
system once its pre-deployment impact assessment is approved. First answers (a field that was empty) are not changes;
removals (a data type no longer used) do not ask for a reassessment.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.impact.triggers import raise_trigger

IN_USE = ("in_development", "ready_for_go_live", "live")


def watched(db: Session, s) -> bool:
    from app.impact.models import ImpactAssessment

    if s.stage in IN_USE:
        return True
    if s.stage != "proposed":
        return False
    return db.scalar(select(ImpactAssessment.id).where(ImpactAssessment.register_system_id == s.id, ImpactAssessment.status == "decided",
                                                       ImpactAssessment.decision.in_(("approved", "approved_with_conditions")), ImpactAssessment.deleted_at.is_(None)).limit(1)) is not None


def _labels(db: Session, field: str, values) -> str:
    from app.register.service import display

    return display(db, field, values) or "none"


def detect(db: Session, actor_id: str | None, s, changed: dict) -> list:
    """`changed` is {field: (old, new)} from update_system."""
    if not changed or not watched(db, s):
        return []
    found: list[tuple[str, str]] = []
    for f, label in (("model_version", "Model version"), ("model_name", "Model")):
        if f in changed and changed[f][0]:
            old, new = changed[f]
            found.append(("version_change", f"{label}: {old} → {new or 'not recorded'}"))
    if "data_categories" in changed:
        added = [c for c in changed["data_categories"][1] or [] if c not in (changed["data_categories"][0] or [])]
        if added:
            found.append(("new_data_category", f"Data used: added {_labels(db, 'data_categories', added)}"))
    if "data_subjects" in changed:
        added = [c for c in changed["data_subjects"][1] or [] if c not in (changed["data_subjects"][0] or []) and c != "none"]
        if added:
            found.append(("new_population", f"Whose data: added {_labels(db, 'data_subjects', added)}"))
    for f in ("vendor_id", "ai_provider"):
        if f in changed and changed[f][0]:
            old, new = changed[f]
            found.append(("vendor_change", f"{'Vendor' if f == 'vendor_id' else 'AI provider'}: {_labels(db, f, old)} → {_labels(db, f, new)}"))
    if "cross_border" in changed and (changed["cross_border"][1] or "no") != "no":
        found.append(("new_jurisdiction", f"Data leaves the country: {_labels(db, 'cross_border', changed['cross_border'][1])}"))
    out = []
    for kind, detail in found:
        t = raise_trigger(db, s.id, type=kind, source="register_edit", detail=detail, actor_id=actor_id)
        if t is not None and t not in out:
            out.append(t)
    return out


def detect_law_added(db: Session, actor_id: str | None, s, regulation, link_id: str):
    """A law from a jurisdiction none of the system's other laws covers means the system now reaches a new place."""
    from app.reference.models import Jurisdiction
    from app.register.models import RegisterSystemLaw
    from app.laws.models import Regulation

    if not watched(db, s):
        return None
    others = db.scalars(select(Regulation.jurisdiction_id).join(RegisterSystemLaw, RegisterSystemLaw.regulation_id == Regulation.id)
                        .where(RegisterSystemLaw.register_system_id == s.id, RegisterSystemLaw.id != link_id, RegisterSystemLaw.status == "active",
                               RegisterSystemLaw.deleted_at.is_(None)))
    if regulation.jurisdiction_id in set(others):
        return None
    j = db.get(Jurisdiction, regulation.jurisdiction_id)
    return raise_trigger(db, s.id, type="new_jurisdiction", source="register_edit", detail=f"Law added: {regulation.short_name}" + (f" ({j.name})" if j else ""), actor_id=actor_id)
