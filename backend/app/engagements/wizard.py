"""New-client wizard (screens NewClient1–4, spec §18.3).

Each step autosaves straight into the models with lenient checks: a value that cannot be read is reported and
skipped, everything else in the same save is kept. Required fields are checked only at submit (`validate`).
"""
import re
from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.engagements.models import ClientContact, ClientLocation, ClientRequirement, Engagement, EngagementTeam
from app.engagements.service import TYPES, add_location
from app.laws.models import Regulation
from app.policy.roles import FUTRAN_ROLES
from app.reference.jurisdictions import resolve_jurisdictions
from app.reference.models import Jurisdiction
from app.tenancy.models import Organization, User
from app.tenancy.service import roles_of

STEPS = ("company", "locations", "requirements", "scope", "contacts")
INDUSTRIES = {
    "staffing": "Staffing and recruitment",
    "bfsi": "Banking and financial services (BFSI)",
    "healthcare": "Healthcare",
    "insurance": "Insurance",
    "pharma": "Pharma and life sciences",
    "public_sector": "Public sector",
    "property": "Property management",
    "other": "Other",
}
EMPLOYEE_BANDS = ["1-49", "50-249", "250-999", "1000+"]
FRAMEWORKS = {
    "nist_ai_rmf": "NIST AI RMF 1.0",
    "eu_ai_act": "EU AI Act",
    "iso_42001": "ISO/IEC 42001",
    "gdpr": "GDPR",
    "hipaa": "HIPAA",
    "dpdp": "India DPDP Act",
    "soc2": "SOC 2",
    "iso_27001": "ISO/IEC 27001",
    "rbi_free_ai": "RBI FREE-AI",
    "other": "Other",
}
DATA_ENVIRONMENTS = {"production": "Production", "uat": "UAT / staging", "dev": "Development"}
TEAM_ROLES = {
    "chief_auditor": "Chief Auditor",
    "engagement_manager": "Engagement Manager",
    "auditor": "Auditor",
    "qa_reviewer": "QA Reviewer",
    "legal_reviewer": "Legal / compliance reviewer",
}
CONTACT_ROLES = ("caico", "client_admin", "exec_sponsor", "dpo", "project_lead", "technical_lead", "compliance_lead")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Bad(ValueError):
    pass


# ---- value readers: return the cleaned value or raise Bad(message)
def text(max_len: int = 200) -> Callable[[Any], str | None]:
    def read(v):
        if v is None:
            return None
        if not isinstance(v, (str, int, float)):
            raise Bad("Enter text.")
        s = str(v).strip()
        if len(s) > max_len:
            raise Bad(f"Keep this under {max_len} characters.")
        return s or None

    return read


def choice(options) -> Callable[[Any], str | None]:
    def read(v):
        if v in (None, ""):
            return None
        if v not in options:
            raise Bad("Choose one of the options.")
        return v

    return read


def a_date(v):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        raise Bad("Enter a date as YYYY-MM-DD.") from None


def an_int(v):
    if v in (None, ""):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise Bad("Enter a whole number.") from None
    if n < 0:
        raise Bad("Enter zero or more.")
    return n


def text_list(max_items: int = 50, options=None) -> Callable[[Any], list | None]:
    def read(v):
        if v is None:
            return None
        if not isinstance(v, list):
            raise Bad("Expected a list.")
        out = [str(x).strip() for x in v if str(x).strip()][:max_items]
        if options is not None and any(x not in options for x in out):
            raise Bad("Choose from the options.")
        return list(dict.fromkeys(out))

    return read


def email(v):
    s = text(254)(v)
    if s and not EMAIL.match(s):
        raise Bad("Enter a valid email address.")
    return s.lower() if s else None


def a_bool(v):
    return bool(v)


E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def phone(v):
    """A phone number in E.164 form (+12125550100). Spaces, dots, dashes and brackets are dropped."""
    s = text(40)(v)
    if not s:
        return None
    compact = re.sub(r"[\s().\-]", "", s)
    if not E164.match(compact):
        raise Bad("Enter the number with its country code, for example +1 212 555 0100.")
    return compact


COMPANY_FIELDS = {
    "legal_name": text(200), "trading_name": text(200), "industry": choice(INDUSTRIES), "employee_band": choice(EMPLOYEE_BANDS),
    "employee_count": an_int, "annual_revenue_band": text(40), "website": text(200), "hq_street": text(200), "hq_city": text(120),
    "hq_state": text(120), "hq_postal_code": text(20), "hq_country": text(2), "primary_jurisdictions": text_list(30),
    "ai_systems_in_scope_count": an_int, "engagement_reason": text(2000),
}
SCOPE_FIELDS = {
    "type": choice(TYPES), "period_start": a_date, "period_end": a_date, "letter_due": a_date, "report_due": a_date,
    "draft_report_target": a_date, "final_report_target": a_date, "fieldwork_start": a_date, "methodology_version": text(80),
    "frameworks": text_list(20, FRAMEWORKS), "business_processes": text(4000), "data_environments": text_list(3, DATA_ENVIRONMENTS),
    "geographic_scope": text(2000), "exclusions": text(4000), "systems_excluded": text(4000), "planned_systems": text_list(100),
}
CONTACT_FIELDS = {"name": text(120), "title": text(120), "email": email, "phone": phone}


def _read(fields: dict, payload: dict, prefix: str, errors: list) -> dict:
    out = {}
    for key, reader in fields.items():
        if key not in payload:
            continue
        try:
            out[key] = reader(payload[key])
        except Bad as exc:
            errors.append({"field": f"{prefix}.{key}", "message": str(exc)})
    return out


def _state(e: Engagement) -> dict:
    return dict(e.wizard_state or {})


# ---- saving each step
def save_company(db: Session, actor: User, org: Organization, e: Engagement, payload: dict) -> list[dict]:
    errors: list[dict] = []
    values = _read(COMPANY_FIELDS, payload, "company", errors)
    if values.get("hq_country"):
        values["hq_country"] = values["hq_country"].upper()
    for k, v in values.items():
        setattr(org, k, v)
    if "legal_name" in values or "trading_name" in values:
        org.name = org.trading_name or org.legal_name or org.name
        st = _state(e)
        if st.get("auto_name", True):
            e.name = f"{org.name} AI governance audit"
            e.wizard_state = st | {"auto_name": True}
    org.updated_by = actor.id
    _sync_hq_site(db, actor, org, e)
    return errors


LOCATION_FIELDS = {"site_name": text(120), "street": text(200), "city": text(120), "subdivision_code": text(12), "country_code": text(2), "employees_at_site": an_int}


def save_locations(db: Session, actor: User, org: Organization, e: Engagement, payload: dict) -> list[dict]:
    """Replace the site list. Rows are reused (by id, then in order) so repeated autosaves never pile up rows;
    a value that cannot be read is reported and the stored value is kept."""
    errors: list[dict] = []
    items = payload.get("locations")
    if not isinstance(items, list):
        return [{"field": "locations.locations", "message": "Expected a list of sites."}]
    same = _state(e).get("hq_same_as_company", False)
    if "hq_same_as_company" in payload:
        same = bool(payload["hq_same_as_company"])
        e.wizard_state = _state(e) | {"hq_same_as_company": same}
    if same:  # the first site is the headquarters, at the company address
        items = list(items) or [{"site_name": "Headquarters", "in_scope": True}]
        first = items[0] if isinstance(items[0], dict) else {}
        items[0] = first | _hq_site_values(db, org) | {"site_name": first.get("site_name") or "Headquarters"}
    existing = list(db.scalars(select(ClientLocation).where(ClientLocation.organization_id == org.id, ClientLocation.deleted_at.is_(None)).order_by(ClientLocation.created_at)))
    by_id = {loc.id: loc for loc in existing}
    claimed = {item.get("id") for item in items if isinstance(item, dict) and item.get("id") in by_id}
    spare = [loc for loc in existing if loc.id not in claimed]
    keep: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        p = f"locations.locations.{i}"
        vals = _read(LOCATION_FIELDS, item, p, errors)
        loc = by_id.get(item.get("id")) or (spare.pop(0) if spare else None)
        if loc is not None:
            keep.add(loc.id)
        country = (vals.get("country_code") or (loc.country_code if loc else "") or "").upper()
        if "country_code" in vals and vals["country_code"] and not resolve_jurisdictions(db, vals["country_code"].upper(), None, None):
            errors.append({"field": f"{p}.country_code", "message": "Unknown country."})
            country = loc.country_code if loc else ""
        if not country:
            if loc is None:
                errors.append({"field": f"{p}.country_code", "message": "Choose a country."})
            continue
        if loc is None:
            loc = add_location(db, org, site_name=vals.get("site_name") or vals.get("city") or "Site", country_code=country, subdivision_code=vals.get("subdivision_code"), city=vals.get("city"), street=vals.get("street"), employees_at_site=vals.get("employees_at_site"), in_scope=bool(item.get("in_scope", True)), actor_id=actor.id)
            keep.add(loc.id)
            if i == 0 and same:
                e.wizard_state = _state(e) | {"hq_location_id": loc.id}
            continue
        if i == 0 and same:
            e.wizard_state = _state(e) | {"hq_location_id": loc.id}
        for k in ("site_name", "street", "city", "subdivision_code", "employees_at_site"):
            if k in vals:
                setattr(loc, k, vals[k])
        loc.site_name = loc.site_name or loc.city or "Site"
        loc.country_code = country
        if "in_scope" in item:
            loc.in_scope = bool(item["in_scope"])
        js = resolve_jurisdictions(db, country, loc.subdivision_code, loc.city)
        state = next((j for j in js if j.level == "state"), None)
        loc.subdivision_code = state.code if state else loc.subdivision_code
        loc.jurisdiction_ids, loc.updated_by = [j.id for j in js], actor.id
    for loc in existing:
        if loc.id not in keep:
            loc.deleted_at = utcnow()
    return errors


def _hq_site_values(db: Session, org: Organization) -> dict:
    """The company's head office address as site values: the state or region as its ISO code when it can be resolved."""
    js = resolve_jurisdictions(db, org.hq_country or "", org.hq_state, org.hq_city) if org.hq_country else []
    state = next((j for j in js if j.level == "state"), None)
    return {"street": org.hq_street, "city": org.hq_city, "subdivision_code": state.code if state else None, "country_code": org.hq_country or "US"}


def _sync_hq_site(db: Session, actor: User, org: Organization, e: Engagement) -> None:
    """While "Same as company address" is ticked, the headquarters site follows the company address."""
    st = _state(e)
    if not st.get("hq_same_as_company") or not st.get("hq_location_id"):
        return
    loc = db.get(ClientLocation, st["hq_location_id"])
    if loc is None or loc.deleted_at or loc.organization_id != org.id or not org.hq_country:
        return
    js = resolve_jurisdictions(db, org.hq_country, org.hq_state, org.hq_city)
    if not js:
        return
    state = next((j for j in js if j.level == "state"), None)
    loc.street, loc.city, loc.country_code = org.hq_street, org.hq_city, org.hq_country.upper()
    loc.subdivision_code = state.code if state else None
    loc.jurisdiction_ids, loc.updated_by = [j.id for j in js], actor.id


def save_requirements(db: Session, actor: User, org: Organization, e: Engagement, payload: dict) -> list[dict]:
    """Replace the laws in scope. Old law versions are mapped to the current one; retired laws are refused."""
    from app.laws.publish import current_version_of

    errors: list[dict] = []
    items = payload.get("requirements")
    if not isinstance(items, list):
        return [{"field": "requirements", "message": "Expected a list of laws."}]
    existing = {(r.regulation_id or f"text:{r.free_text}"): r for r in db.scalars(select(ClientRequirement).where(ClientRequirement.engagement_id == e.id, ClientRequirement.deleted_at.is_(None)))}
    keep: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        vals = _read({"label": text(300), "reason_text": text(1000), "notes": text(2000)}, item, f"requirements.{i}", errors)
        reg_id = item.get("regulation_id")
        if reg_id:
            reg = current_version_of(db, reg_id) if isinstance(reg_id, str) else None
            if reg is None or reg.retired_in_version_id:
                errors.append({"field": f"requirements.{i}", "message": "This law is no longer in the matrix."})
                continue
            key = reg.id
        elif vals.get("label"):
            key = f"text:{vals['label']}"
        else:
            if "label" in vals or "label" not in item:
                errors.append({"field": f"requirements.{i}", "message": "Name the requirement."})
            continue
        if key in keep:
            continue
        keep.add(key)
        r = existing.get(key)
        if r is None:
            r = ClientRequirement(organization_id=org.id, engagement_id=e.id, regulation_id=None if key.startswith("text:") else key, free_text=key[5:] if key.startswith("text:") else None, created_by=actor.id)
            db.add(r)
        r.source = item.get("source") if item.get("source") in ("auto", "manual", "futran_default") else (r.source or "manual")
        if "reason_text" in vals:
            r.reason_text = vals["reason_text"]
        if "notes" in vals:
            r.notes = vals["notes"]
        r.in_scope, r.updated_by = bool(item.get("in_scope", True)), actor.id
    for key, r in existing.items():
        if key not in keep:
            r.deleted_at = utcnow()
    db.flush()
    return errors


def _futran_roles(db: Session, user: User) -> set[str]:
    return {r.role for r in roles_of(db, user.id)} & {r.value for r in FUTRAN_ROLES}


def save_scope(db: Session, actor: User, org: Organization, e: Engagement, payload: dict) -> list[dict]:
    errors: list[dict] = []
    values = _read(SCOPE_FIELDS, payload, "scope", errors)
    for k, v in values.items():
        if k == "methodology_version" and not v:
            continue
        setattr(e, k, v)
    if "departments" in payload:
        try:
            e.wizard_state = _state(e) | {"departments": text_list(60)(payload["departments"]) or []}
        except Bad as exc:
            errors.append({"field": "scope.departments", "message": str(exc)})
    if "team" in payload:
        errors += _save_team(db, actor, e, payload["team"])
    e.updated_by = actor.id
    return errors


def _save_team(db: Session, actor: User, e: Engagement, team: Any) -> list[dict]:
    if not isinstance(team, list):
        return [{"field": "scope.team", "message": "Expected a list of team members."}]
    errors: list[dict] = []
    current = {(t.user_id, t.role): t for t in db.scalars(select(EngagementTeam).where(EngagementTeam.engagement_id == e.id, EngagementTeam.deleted_at.is_(None)))}
    keep: set[tuple[str, str]] = set()
    for i, m in enumerate(team):
        p = f"scope.team.{i}"
        role = m.get("role") if isinstance(m, dict) else None
        user = db.get(User, m.get("user_id")) if isinstance(m, dict) and isinstance(m.get("user_id"), str) else None
        if role not in TEAM_ROLES:
            errors.append({"field": f"{p}.role", "message": "Choose a team role."})
            continue
        org = db.get(Organization, user.organization_id) if user else None
        if user is None or org is None or org.type != "futran" or user.status == "disabled" or user.deleted_at:
            errors.append({"field": f"{p}.user_id", "message": "Choose a Futran team member."})
            continue
        if _futran_roles(db, user) <= {"admin"}:
            errors.append({"field": f"{p}.user_id", "message": f"{user.name} is an administrator and cannot be on an audit team."})
            continue
        row = current.get((user.id, role))
        if row is None:
            row = EngagementTeam(organization_id=e.client_id, engagement_id=e.id, user_id=user.id, role=role, created_by=actor.id)
            db.add(row)
        if m.get("conflict_confirmed"):
            row.conflict_confirmed_at = row.conflict_confirmed_at or utcnow()
        else:
            row.conflict_confirmed_at = None
        keep.add((user.id, role))
    for key, row in current.items():
        if key in keep:
            continue
        if key[0] == e.created_by and not any(k[0] == e.created_by for k in keep):
            continue  # the author stays on the team so they can keep working on the draft
        row.deleted_at = utcnow()
    db.flush()
    _record_conflict_confirmations(db, actor, e)
    return errors


def _record_conflict_confirmations(db: Session, actor: User, e: Engagement) -> None:
    """Store, on each confirmed row, every role the person confirmed for, and log each new confirmation once."""
    from app.audit_log import service as audit
    from app.engagements.team import order_roles, roles_label, team_rows

    by_user: dict[str, list[EngagementTeam]] = {}
    names: dict[str, str] = {}
    for t, u in team_rows(db, e):
        by_user.setdefault(u.id, []).append(t)
        names[u.id] = u.name
    for user_id, rows in by_user.items():
        roles = order_roles(t.role for t in rows if t.conflict_confirmed_at is not None)
        changed = False
        for t in rows:
            want = roles if t.conflict_confirmed_at is not None else None
            if t.conflict_confirmed_roles != want:
                t.conflict_confirmed_roles, changed = want, True
        if changed and roles:
            audit.record(db, actor_id=actor.id, action="team.conflict_confirmed", obj=e, object_type="EngagementTeam", object_id=rows[0].id,
                         after={"user_id": user_id, "roles": roles},
                         summary=f"{names[user_id]} confirmed no conflict of interest as {roles_label(roles)} on {e.audit_ref}")
    db.flush()


def save_contacts(db: Session, actor: User, org: Organization, e: Engagement, payload: dict) -> list[dict]:
    errors: list[dict] = []
    current = {c.contact_role: c for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.deleted_at.is_(None)))}
    caico_payload = payload.get("caico") if isinstance(payload.get("caico"), dict) else None
    for role in CONTACT_ROLES:
        if role not in payload:
            continue
        data = payload[role] if isinstance(payload[role], dict) else {}
        c = current.get(role)
        if c is not None and c.phone and data.get("phone") == c.phone:
            data = {k: v for k, v in data.items() if k != "phone"}  # a number stored before country codes were required, unchanged
        vals = _read(CONTACT_FIELDS, data, f"contacts.{role}", errors)
        if c is None:
            c = ClientContact(organization_id=org.id, engagement_id=e.id, contact_role=role, created_by=actor.id)
            db.add(c)
            current[role] = c
        if role in ("client_admin", "project_lead") and data.get("same_as_caico"):
            src = current.get("caico")
            base = {k: getattr(src, k) for k in CONTACT_FIELDS} if src else {}
            if caico_payload is not None:
                base |= _read(CONTACT_FIELDS, caico_payload, "contacts.caico", [])
            vals = base
            e.wizard_state = _state(e) | {f"{role}_same_as_caico": True}
        elif role in ("client_admin", "project_lead"):
            e.wizard_state = _state(e) | {f"{role}_same_as_caico": False}
        for k in CONTACT_FIELDS:
            if k in vals or (role in ("client_admin", "project_lead") and data.get("same_as_caico")):
                setattr(c, k, vals.get(k))
        if role in ("exec_sponsor", "dpo"):
            c.not_appointed = bool(data.get("not_appointed"))
        c.updated_by = actor.id
    db.flush()
    return errors


def snapshot(db: Session, org: Organization, e: Engagement, step: str) -> dict:
    """The step's current values, for the audit log (spec §6 rule 10)."""
    w = wizard_out(db, org, e)
    if step == "company":
        return {k: w["company"][k] for k in COMPANY_FIELDS}
    if step == "locations":
        return {"locations": [{k: loc[k] for k in ("site_name", "street", "city", "subdivision_code", "country_code", "employees_at_site", "in_scope")} for loc in w["locations"]["locations"]]}
    if step == "requirements":
        return {"requirements": [r["label"] for r in w["locations"]["requirements"]]}
    if step == "scope":
        return w["scope"]
    return w["contacts"]


SAVERS = {"company": save_company, "locations": save_locations, "requirements": save_requirements, "scope": save_scope, "contacts": save_contacts}


# ---- reading back
def _contacts(db: Session, e: Engagement) -> dict:
    out = {}
    st = _state(e)
    for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.deleted_at.is_(None))):
        out[c.contact_role] = {"name": c.name, "title": c.title, "email": c.email, "phone": c.phone, "not_appointed": c.not_appointed, "user_id": c.user_id}
        if c.contact_role in ("client_admin", "project_lead"):
            out[c.contact_role]["same_as_caico"] = bool(st.get(f"{c.contact_role}_same_as_caico"))
    return out


def _people(db: Session, e: Engagement) -> list[dict]:
    from app.engagements.team import team_by_person

    return [{k: p[k] for k in ("user_id", "name", "roles", "role_label", "conflict_confirmed")} for p in team_by_person(db, e)]


def wizard_out(db: Session, org: Organization, e: Engagement) -> dict:
    jnames = dict(db.execute(select(Jurisdiction.id, Jurisdiction.name)).all())
    locs = db.scalars(select(ClientLocation).where(ClientLocation.organization_id == org.id, ClientLocation.deleted_at.is_(None)).order_by(ClientLocation.created_at))
    reqs = []
    from app.laws.publish import current_version_of

    for r in db.scalars(select(ClientRequirement).where(ClientRequirement.engagement_id == e.id, ClientRequirement.deleted_at.is_(None)).order_by(ClientRequirement.created_at)):
        reg = current_version_of(db, r.regulation_id) if r.regulation_id else None  # always show the current text of the law
        reqs.append({"id": r.id, "regulation_id": reg.id if reg else None, "label": reg.short_name if reg else r.free_text, "jurisdiction": jnames.get(reg.jurisdiction_id) if reg else None, "feature": reg.feature if reg else None, "source": r.source, "reason_text": r.reason_text, "in_scope": r.in_scope, "retired": bool(reg and reg.retired_in_version_id)})
    team = [
        {"user_id": t.user_id, "name": u.name, "role": t.role, "conflict_confirmed": t.conflict_confirmed_at is not None}
        for t, u in db.execute(select(EngagementTeam, User).join(User, User.id == EngagementTeam.user_id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.deleted_at.is_(None)).order_by(EngagementTeam.created_at))
    ]
    d = lambda v: v.isoformat() if v else None  # noqa: E731
    return {
        "client_id": org.id,
        "engagement": {"id": e.id, "audit_ref": e.audit_ref, "name": e.name, "status": e.status, "stage": e.stage, "returned_comment": e.returned_comment},
        "company": {k: getattr(org, k) for k in COMPANY_FIELDS} | {"client_ref": org.client_ref},
        "locations": {
            "locations": [{"id": loc.id, "site_name": loc.site_name, "street": loc.street, "city": loc.city, "subdivision_code": loc.subdivision_code, "country_code": loc.country_code, "employees_at_site": loc.employees_at_site, "in_scope": loc.in_scope, "jurisdictions": [jnames.get(j) for j in loc.jurisdiction_ids or []]} for loc in locs],
            "requirements": reqs,
            "hq_same_as_company": bool(_state(e).get("hq_same_as_company")),
        },
        "scope": {k: (d(getattr(e, k)) if SCOPE_FIELDS[k] is a_date else getattr(e, k)) for k in SCOPE_FIELDS} | {"departments": _state(e).get("departments", []), "team": team, "people": _people(db, e)},
        "contacts": _contacts(db, e),
    }


# ---- submit checks
REQUIRED_COMPANY = {
    "legal_name": "Enter the legal name.", "industry": "Choose the industry.", "employee_band": "Choose the number of employees.",
    "hq_street": "Enter the street.", "hq_city": "Enter the city.", "hq_state": "Enter the state or region.", "hq_postal_code": "Enter the postal code.",
    "hq_country": "Choose the country.", "primary_jurisdictions": "Choose at least one country of operation.", "ai_systems_in_scope_count": "Enter the number of AI systems in scope.",
}
REQUIRED_SCOPE = {
    "type": "Choose the engagement type.", "period_start": "Enter the audit period start.", "period_end": "Enter the audit period end.",
    "fieldwork_start": "Enter the engagement start date.", "draft_report_target": "Enter the target date for the draft report.",
    "final_report_target": "Enter the target date for the final report.", "frameworks": "Choose at least one framework.",
    "business_processes": "Describe the business processes in scope.", "data_environments": "Choose the data environments in scope.",
    "geographic_scope": "Describe the geographic scope.", "planned_systems": "List the AI systems in scope.",
}


def validate(db: Session, org: Organization, e: Engagement) -> list[dict]:
    errs: list[dict] = []
    for k, msg in REQUIRED_COMPANY.items():
        if getattr(org, k) in (None, "", []):
            errs.append({"field": f"company.{k}", "message": msg})
    locs = list(db.scalars(select(ClientLocation).where(ClientLocation.organization_id == org.id, ClientLocation.deleted_at.is_(None), ClientLocation.in_scope.is_(True))))
    if not locs:
        errs.append({"field": "locations.locations", "message": "Add at least one site in scope."})
    if not db.scalar(select(func.count()).select_from(ClientRequirement).where(ClientRequirement.engagement_id == e.id, ClientRequirement.deleted_at.is_(None), ClientRequirement.in_scope.is_(True))):
        errs.append({"field": "locations.requirements", "message": "Choose at least one law or framework in scope."})
    for k, msg in REQUIRED_SCOPE.items():
        if getattr(e, k) in (None, "", []):
            errs.append({"field": f"scope.{k}", "message": msg})
    if e.period_start and e.period_end and e.period_end < e.period_start:
        errs.append({"field": "scope.period_end", "message": "The audit period must end after it starts."})
    if e.draft_report_target and e.final_report_target and e.final_report_target < e.draft_report_target:
        errs.append({"field": "scope.final_report_target", "message": "The final report cannot be due before the draft."})
    if not _state(e).get("departments"):
        errs.append({"field": "scope.departments", "message": "Choose at least one department or function."})
    errs += _validate_team(db, e)
    errs += _validate_contacts(db, org, e)
    return errs


def _validate_team(db: Session, e: Engagement) -> list[dict]:
    errs = []
    rows = list(db.execute(select(EngagementTeam, User).join(User, User.id == EngagementTeam.user_id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.deleted_at.is_(None))))
    by_role: dict[str, list[User]] = {}
    from app.engagements.team import roles_label, team_by_person

    for p in team_by_person(db, e):
        if not p["conflict_confirmed"]:
            errs.append({"field": "scope.team", "message": f"{p['name']} has not confirmed there is no conflict of interest as {roles_label(p['roles'])}."})
    for t, u in rows:
        by_role.setdefault(t.role, []).append(u)
        needed = {"chief_auditor": {"chief_auditor"}, "qa_reviewer": {"qa_reviewer", "chief_auditor"}}.get(t.role)
        if needed and not (_futran_roles(db, u) & needed):
            errs.append({"field": "scope.team", "message": f"{u.name} is not a {TEAM_ROLES[t.role]}."})
    if len(by_role.get("chief_auditor", [])) != 1:
        errs.append({"field": "scope.team", "message": "Choose one Chief Auditor (Lead Auditor)."})
    if not by_role.get("engagement_manager"):
        errs.append({"field": "scope.team", "message": "Choose an Engagement Manager."})
    if not by_role.get("auditor"):
        errs.append({"field": "scope.team", "message": "Choose at least one auditor."})
    return list({(x["field"], x["message"]): x for x in errs}.values())


def _validate_contacts(db: Session, org: Organization, e: Engagement) -> list[dict]:
    from app.tenancy.service import find_user_by_email

    errs = []
    c = _contacts(db, e)
    caico = c.get("caico") or {}
    for k, msg in (("name", "Enter the CAICO's full name."), ("title", "Enter the CAICO's job title."), ("email", "Enter the CAICO's work email.")):
        if not caico.get(k):
            errs.append({"field": f"contacts.caico.{k}", "message": msg})
    admin = c.get("client_admin") or {}
    if not admin.get("same_as_caico"):
        for k, msg in (("name", "Enter the Client Admin's full name."), ("email", "Enter the Client Admin's work email.")):
            if not admin.get(k):
                errs.append({"field": f"contacts.client_admin.{k}", "message": msg})
    for role, data in c.items():
        em = data.get("email")
        if not em:
            continue
        u = find_user_by_email(db, em)
        if u is not None and u.organization_id != org.id:
            errs.append({"field": f"contacts.{role}.email", "message": "This email belongs to a user in another organization. Use the person's work email at this client."})
    return errs
