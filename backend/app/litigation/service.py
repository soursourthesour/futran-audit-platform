"""Case records and matching against client AI system registers (spec §27.4)."""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.clock import today, utcnow
from app.litigation.models import STAGE_LABELS, Case, CaseClientMatch
from app.register.models import RegisterSystem
from app.systems.models import Vendor
from app.tenancy.models import Organization

TYPE_LABELS = {
    "agent": "AI agent", "vendor_app": "Vendor AI app", "embedded_feature": "Embedded AI feature",
    "foundation_model_api": "Foundation model API", "in_house_model": "In-house model", "genai_chat_tool": "Generative AI tool or chatbot",
}
SOURCING_LABELS = {"vendor": "vendor-supplied", "in_house": "built in house", "contractor": "built by a contractor", "shadow": "unapproved"}


def _terms(values) -> list[str]:
    return [str(v).strip().casefold() for v in (values or []) if str(v).strip()]


def system_matches(rule: dict, system: RegisterSystem, vendor_name: str | None) -> list[str] | None:
    """Why `system` is like the AI in the case, or None. Every criterion the rule sets must hold."""
    if not rule or system.stage == "retired" or system.deleted_at is not None:
        return None
    why: list[str] = []
    types = set(rule.get("types") or [])
    if types:
        if system.type not in types:
            return None
        why.append(f"type {TYPE_LABELS.get(system.type, system.type)}")
    sourcing = set(rule.get("sourcing") or [])
    if sourcing:
        if system.sourcing not in sourcing:
            return None
        why.append(SOURCING_LABELS.get(system.sourcing, system.sourcing))
    vendors = _terms(rule.get("vendors"))
    if vendors:
        name = (vendor_name or "").casefold()
        hit = next((v for v in vendors if v in name), None)
        if hit is None:
            return None
        why.append(f"vendor {vendor_name}")
    uses = _terms(rule.get("uses"))
    if uses:
        text = f"{system.name} {system.purpose or ''}".casefold()
        hit = next((u for u in uses if u in text), None)
        if hit is None:
            return None
        why.append(f"use mentions “{hit}”")
    return why or None


def match_case(db: Session, case: Case) -> list[CaseClientMatch]:
    """Recompute the clients with similar AI. Matches are replaced each time; they hold no client-entered data."""
    db.execute(delete(CaseClientMatch).where(CaseClientMatch.case_id == case.id))
    vendors = dict(db.execute(select(Vendor.id, Vendor.legal_name)).all())
    by_org: dict[str, tuple[list[str], list[str]]] = {}
    rows = db.scalars(select(RegisterSystem).where(RegisterSystem.deleted_at.is_(None)).order_by(RegisterSystem.reference))
    for s in rows:
        why = system_matches(case.match_rule or {}, s, vendors.get(s.vendor_id))
        if why is None:
            continue
        ids, reasons = by_org.setdefault(s.organization_id, ([], []))
        ids.append(s.id)
        for w in why:
            if w not in reasons:
                reasons.append(w)
    out = []
    for org_id, (ids, reasons) in by_org.items():
        m = CaseClientMatch(case_id=case.id, organization_id=org_id, ai_system_ids=ids, match_reason=("Matched on " + ", ".join(reasons))[:500])
        db.add(m)
        out.append(m)
    db.flush()
    return out


def matches_out(db: Session, case: Case) -> list[dict]:
    """Client name and system type only: no audit evidence, findings or scores (§27.5)."""
    out = []
    for m in db.scalars(select(CaseClientMatch).where(CaseClientMatch.case_id == case.id)):
        org = db.get(Organization, m.organization_id)
        systems = [db.get(RegisterSystem, sid) for sid in m.ai_system_ids]
        out.append({
            "organization_id": m.organization_id, "organization_name": org.name if org else "", "match_reason": m.match_reason,
            "systems": [{"id": s.id, "name": s.name, "type": s.type, "type_label": TYPE_LABELS.get(s.type, s.type), "stage": s.stage} for s in systems if s is not None],
        })
    return sorted(out, key=lambda x: x["organization_name"].casefold())


def add_timeline(case: Case, stage: str, label: str | None = None, on=None) -> None:
    entry = {"on": (on or today()).isoformat(), "stage": stage, "label": label or STAGE_LABELS.get(stage, stage)}
    case.timeline = [*(case.timeline or []), entry]


def case_out(db: Session, case: Case, *, following: bool = False, detail: bool = False) -> dict:
    matches = matches_out(db, case)
    out = {
        "id": case.id, "name": case.name, "geography": case.geography, "jurisdiction_id": case.jurisdiction_id, "area": case.area,
        "court": case.court, "docket_ref": case.docket_ref, "description": case.description, "stage": case.stage,
        "stage_label": STAGE_LABELS.get(case.stage, case.stage), "stage_note": case.stage_note,
        "last_update_on": case.last_update_on.isoformat() if case.last_update_on else None, "version": case.version,
        "regulation_ids": case.regulation_ids or [], "clients_count": len(matches),
        "systems_count": sum(len(m["systems"]) for m in matches), "following": following, "origin": case.origin,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }
    if detail:
        out |= {
            "why_matters": case.why_matters, "talking_points_futran": case.talking_points_futran, "talking_points_client": case.talking_points_client,
            "sources": case.sources or [], "timeline": case.timeline or [], "match_rule": case.match_rule or {}, "matches": matches,
        }
    else:
        out["match_summary"] = ", ".join(sorted({s["type_label"] for m in matches for s in m["systems"]}))
    return out


def touch(case: Case, actor_id: str | None) -> None:
    case.version = (case.version or 1) + 1
    case.updated_by = actor_id
    case.updated_at = utcnow()
