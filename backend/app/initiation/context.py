"""Merge values for the initiation package templates (seeds/templates/*.md.j2)."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import today
from app.core.config import Settings
from app.engagements.models import ClientContact, ClientLocation, ClientRequirement, Engagement, EngagementTeam
from app.engagements.wizard import TEAM_ROLES
from app.laws.importer import FEATURE_LABELS
from app.laws.models import Regulation
from app.reference.models import GovernanceCatalogItem, Jurisdiction
from app.tenancy.models import Organization, User

TYPE_LABELS = {"initial_assessment": "Initial AI governance assessment", "ll144_bias_audit": "LL144 bias audit", "annual_review": "Annual review"}
GROUPS = [
    ("document", "Governance documents", None),
    ("security_document", "Data and security documents", "Futran reviews how these cover AI; it does not audit the full security program. SOC 2 or ISO 27001 reports may be uploaded as evidence."),
    ("role", "Committees and named owners", None),
]


def fmt(d: date | None) -> str | None:
    return f"{d:%B} {d.day}, {d.year}" if d else None


def eu_operations(db: Session, org: Organization) -> bool:
    eu = db.scalar(select(Jurisdiction.id).where(Jurisdiction.code == "EU"))
    return any(eu in (loc.jurisdiction_ids or []) for loc in _locations(db, org))


def _locations(db: Session, org: Organization) -> list[ClientLocation]:
    return list(db.scalars(select(ClientLocation).where(ClientLocation.organization_id == org.id, ClientLocation.deleted_at.is_(None), ClientLocation.in_scope.is_(True))))


def governance_groups(db: Session, org: Organization, codes: list[str] | None = None) -> list[dict]:
    """Catalog items grouped for the request. Default selection: every non-optional item that applies to the client."""
    eu = eu_operations(db, org)
    items = list(db.scalars(select(GovernanceCatalogItem).order_by(GovernanceCatalogItem.order)))
    out = []
    for kind, title, note in GROUPS:
        chosen = [
            {"code": i.code, "title": i.title, "description": i.description}
            for i in items
            if i.kind == kind and (i.code in codes if codes is not None else not i.optional and (i.conditional != "eu_operations" or eu))
        ]
        if chosen:
            out.append({"title": title, "note": note, "items": chosen})
    return out


def build_context(db: Session, settings: Settings, e: Engagement) -> dict:
    org = db.get(Organization, e.client_id)
    locs = _locations(db, org)
    codes = {c for loc in locs for c in db.scalars(select(Jurisdiction.code).where(Jurisdiction.id.in_(loc.jurisdiction_ids or [])))}
    contacts: dict[str, dict] = {r: {} for r in ("caico", "client_admin", "exec_sponsor", "dpo", "project_lead", "technical_lead", "compliance_lead")}
    for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.deleted_at.is_(None))):
        contacts[c.contact_role] = {"name": c.name, "title": c.title, "email": c.email, "phone": c.phone, "not_appointed": c.not_appointed}
    laws = []
    for r in db.scalars(select(ClientRequirement).where(ClientRequirement.engagement_id == e.id, ClientRequirement.deleted_at.is_(None), ClientRequirement.in_scope.is_(True)).order_by(ClientRequirement.created_at)):
        reg = db.get(Regulation, r.regulation_id) if r.regulation_id else None
        j = db.get(Jurisdiction, reg.jurisdiction_id) if reg else None
        laws.append({"short_name": reg.short_name if reg else r.free_text, "jurisdiction_name": j.name if j else "", "feature_label": FEATURE_LABELS.get(reg.feature, "") if reg else "Futran addition"})
    team, chief = [], {}
    for t, u in db.execute(select(EngagementTeam, User).join(User, User.id == EngagementTeam.user_id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.deleted_at.is_(None)).order_by(EngagementTeam.created_at)):
        team.append({"name": u.name, "role_label": TEAM_ROLES.get(t.role, t.role), "email": u.email})
        if t.role == "chief_auditor":
            chief = {"name": u.name, "email": u.email}
    order = ["chief_auditor", "engagement_manager", "auditor", "qa_reviewer", "legal_reviewer"]
    team.sort(key=lambda m: order.index(next((k for k, v in TEAM_ROLES.items() if v == m["role_label"]), "auditor")))
    departments = (e.wizard_state or {}).get("departments", [])
    hq = ", ".join(x for x in (org.hq_street, org.hq_city, org.hq_state, org.hq_postal_code, org.hq_country) if x)
    return {
        "today": fmt(today()),
        "client": {"name": org.name, "legal_name": org.legal_name, "hq_address": hq, "industry": org.industry},
        "engagement": {
            "name": e.name, "audit_ref": e.audit_ref, "type_label": TYPE_LABELS.get(e.type, e.type),
            "period_start": fmt(e.period_start), "period_end": fmt(e.period_end), "letter_due": fmt(e.letter_due),
            "report_due": fmt(e.report_due or e.final_report_target), "draft_report_target": fmt(e.draft_report_target),
            "final_report_target": fmt(e.final_report_target), "methodology_version": e.methodology_version,
            "departments": departments, "department_rows": [{"name": d} for d in departments], "systems": e.planned_systems or [],
            "business_processes": e.business_processes, "geographic_scope": e.geographic_scope, "exclusions": e.exclusions,
            "retention_years": e.retention_years or settings.retention_years_default,
        },
        "contacts": contacts,
        "laws": laws,
        "team": team,
        "chief_auditor": chief,
        "sender": {"name": chief.get("name"), "role_label": "Chief Auditor"},
        "has_ny": "US-NY" in codes,
        "has_eu": "EU" in codes,
        "groups": governance_groups(db, org),
        "due_date": None,
    }
