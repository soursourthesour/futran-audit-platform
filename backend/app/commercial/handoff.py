"""Won → hand off to delivery (spec §4.8, SM-13).

`create_from_acceptance` is called by the proposals workstream (R4) when a client accepts a proposal version. In one
transaction (a savepoint: any failure leaves nothing behind) it creates:

1. the client: the prospect becomes a `draft` client, the opportunity's contacts are copied to `ClientContact`;
2. the order, its lines copied from the accepted version with prices frozen;
3. one engagement draft per delivery family (audit lines → `initial_assessment`, LL144 → `ll144_bias_audit`, other
   types from the catalog's `engagement_type` when the platform accepts them), with fee and milestones;
4. the subscription (monitoring F3, extended) and entitlements for recurring lines;
5. hours banks (M-13, X-06) and retainers (M-12, X-01);
6. the partner commission through `partners.service.commission_for_win` when the opportunity has a partner;
7. notifications to the Chief Auditor, the Futran Admin and finance (the Futran Admin, until a finance role exists).

Nothing is sent to the client. Engagement drafts still go through Chief Auditor approval and the initiation package.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.commercial import catalog as cat
from app.commercial.common import add_months, engagement_types, money, type_label, users_with_roles
from app.commercial.models import HARD_KEYS, EngagementCommercial, Entitlement, Handoff, HoursBank, Order, OrderLine, Retainer
from app.core.clock import today, utcnow
from app.engagements.models import ClientContact, Engagement
from app.monitoring.models import Subscription
from app.notifications.service import notify
from app.sales.models import Opportunity
from app.tenancy.models import Organization, User

# Codes that never become an engagement: they are held as hours banks or retainers (spec §4.8 item 5).
BANK_CODES = {"M-13": "Advisor hours bank", "X-06": "Litigation support hours"}
RETAINER_CODES = {"M-12": "incident_response", "X-01": "fractional_officer"}
SEPARATE_TEAM_FAMILIES = ("M-07", "AW", "AA", "X-01")  # rules I-2 and I-3
# Used only when the catalog row has no engagement type (spec §2.2 and B6).
FALLBACK_TYPES = {"A-01": None, "A-08": "vendor_due_diligence", "A-14": "annual_review", "L-03": "ll144_applicability", "L-10": "vendor_sponsored_audit",
                  "X-02": "iso42001_readiness", "X-03": "eu_ai_act_readiness", "X-04": "copilot_readiness", "X-05": "ma_due_diligence", "M-08": "training_workshop"}
CONTACT_ORDER = ("caico", "client_admin", "exec_sponsor", "dpo", "project_lead", "technical_lead", "compliance_lead")
CONTACT_ALIASES = {"technical": "technical_lead", "compliance": "compliance_lead", "sponsor": "exec_sponsor", "executive": "exec_sponsor", "privacy": "dpo"}


def code_base(code: str) -> str:
    m = re.match(r"([A-Z]+-\d+)", code or "")
    return m.group(1) if m else (code or "")


def family(code: str) -> str:
    return (code or "").split("-")[0]


def is_recurring(code: str, periods: int | None, item: cat.Item | None) -> bool:
    if code_base(code) in BANK_CODES:
        return False
    if item is not None and item.billing:
        return not cat.is_one_time(item.billing)
    return (periods or 0) in (4, 12) or (family(code) in ("M", "AW") and bool(periods))


def delivery_type(code: str, item: cat.Item | None) -> str | None:
    base = code_base(code)
    if base in BANK_CODES or base in RETAINER_CODES:
        return None
    if item is not None and item.engagement_type:
        return item.engagement_type
    if base in FALLBACK_TYPES:
        return FALLBACK_TYPES[base]
    fam = family(code)
    return {"A": "initial_assessment", "L": "ll144_bias_audit", "AA": "agent_assurance"}.get(fam)


def needs_separate_team(code: str) -> bool:
    return code_base(code) in SEPARATE_TEAM_FAMILIES or family(code) in SEPARATE_TEAM_FAMILIES


def _proposal_lines(db: Session, proposal) -> list:
    lines = getattr(proposal, "lines", None)
    if lines is None:
        try:
            from app.proposals.models import ProposalLine  # R4
        except ImportError:
            return []
        lines = list(db.scalars(select(ProposalLine).where(ProposalLine.proposal_id == proposal.id)))
    # removed lines and roadmap lines (shown only as "optional, when available" with no price, rule P-7) are not ordered
    return [ln for ln in lines if not getattr(ln, "removed_reason", None) and getattr(ln, "sellable_status", None) != "roadmap"]


def next_order_ref(db: Session) -> str:
    refs = db.scalars(select(Order.ref)).all()
    return f"ORD-{max((int(r.split('-')[1]) for r in refs if r), default=0) + 1:04d}"


def _item(kind: str, label: str, details: str, status: str, next_owner: str | None, link: str | None = None, ref_id: str | None = None) -> dict:
    return {"kind": kind, "label": label, "details": details, "status": status, "next_owner": next_owner, "link": link, "ref_id": ref_id}


def create_from_acceptance(db: Session, proposal, acceptance, actor: User | None) -> Handoff:
    """Build the SM-13 records for an accepted proposal version. Runs once per proposal: a second call returns the first
    handoff. Any failure rolls back everything this call wrote and re-raises."""
    existing = db.scalar(select(Handoff).where(Handoff.proposal_id == proposal.id))
    if existing is not None:
        return existing
    with db.begin_nested():
        return _build(db, proposal, acceptance, actor)


def _start_and_end(proposal, acceptance) -> tuple[date, date]:
    terms = getattr(proposal, "terms", None) or {}
    start = terms.get("start_on")
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if not isinstance(start, date):
        at = getattr(acceptance, "accepted_at", None)
        start = at.date() if at else today()
    months = terms.get("term_months") or (int(terms.get("term_years") or 0) * 12) or 12
    return start, add_months(start, int(months)) - timedelta(days=1)


def _build(db: Session, proposal, acceptance, actor: User | None) -> Handoff:
    opp = db.get(Opportunity, proposal.opportunity_id)
    org = db.get(Organization, opp.organization_id)
    owner = db.get(User, opp.owner_id) if opp.owner_id else None
    creator = actor or owner or next(iter(users_with_roles(db, ["chief_auditor"])), None)
    actor_id = actor.id if actor else None
    terms = getattr(proposal, "terms", None) or {}
    lines = _proposal_lines(db, proposal)
    items_by_code = cat.items_by_codes(db, [ln.catalog_code for ln in lines])
    start, end = _start_and_end(proposal, acceptance)
    checklist: list[dict] = []

    # 1. client
    was_prospect = org.status == "prospect"
    if was_prospect:
        org.status = "draft"
    checklist.append(_item("client", "Client organization", "Prospect converted to draft client · contacts copied" if was_prospect else "Existing client · contacts copied",
                           "Created" if was_prospect else "Updated", "Futran Admin", f"/clients/{org.id}", org.id))

    # 2. order and lines, prices frozen
    order = Order(organization_id=org.id, ref=next_order_ref(db), proposal_id=proposal.id, opportunity_id=opp.id, status="open", start_on=start, end_on=end,
                  billing_contact=getattr(acceptance, "email", None), po_number=getattr(acceptance, "po_number", None),
                  catalog_version=getattr(proposal, "catalog_version", None), discount_recurring_pct=getattr(proposal, "discount_recurring_pct", None), created_by=actor_id)
    db.add(order)
    db.flush()
    olines: list[tuple[OrderLine, cat.Item | None]] = []
    for ln in lines:
        item = items_by_code.get(ln.catalog_code)
        if item is None and getattr(ln, "billing", None):  # R4 freezes the catalog fields on the proposal line
            item = cat.Item(code=ln.catalog_code, name=getattr(ln, "name", None) or "", billing=ln.billing, periods_per_year=getattr(ln, "periods_per_year", None),
                            included_quantities=cat.parse_included(getattr(ln, "included_quantities", None)))
        periods = getattr(ln, "periods_per_year", None) or (item.periods_per_year if item else None)
        rec = is_recurring(ln.catalog_code, periods, item)
        unit = money(getattr(ln, "unit_price_used", None) or 0)
        qty = float(getattr(ln, "qty", 1) or 1)
        value = getattr(ln, "line_value", None)
        value = money(value if value is not None else unit * qty * ((periods or 1) if rec else 1))
        ol = OrderLine(organization_id=org.id, order_id=order.id, catalog_code=ln.catalog_code, description=(getattr(ln, "name", None) or (item.name if item else None) or getattr(ln, "description", None) or "")[:300],
                       deliverables_text=getattr(ln, "deliverables_text", None) or (item.deliverables if item else None), qty=qty, unit_price=unit, periods_per_year=periods,
                       recurring=rec, line_value=value, start_on=start, end_on=end if rec else None, entitlement_key=item.entitlement_key if item else None,
                       included_quantities=(item.included_quantities or None) if item else None, created_by=actor_id)
        db.add(ol)
        olines.append((ol, item))
    db.flush()
    y1 = money(sum(ol.line_value for ol, _ in olines))
    checklist.append(_item("order", f"Order {order.ref}", f"{len(olines)} line{'s' if len(olines) != 1 else ''}, prices frozen from v{getattr(proposal, 'version', 1)}",
                           "Created", "Finance (billing export)", f"/staff/clients/{org.id}/plan", order.id))

    # 3. engagement drafts, one per delivery family; the primary one is created last so the wizard opens it
    families: dict[str, list[tuple[OrderLine, cat.Item | None]]] = {}
    for ol, item in olines:
        if ol.recurring:
            continue
        t = delivery_type(ol.catalog_code, item)
        if t:
            families.setdefault(t, []).append((ol, item))
    available = engagement_types()
    primary = "initial_assessment" if "initial_assessment" in families else next(iter(families), None)
    ordered = [t for t in families if t != primary] + ([primary] if primary else [])
    created_at = utcnow()
    primary_engagement = None
    for i, t in enumerate(ordered):
        fam_lines = families[t]
        codes = ", ".join(ol.catalog_code for ol, _ in fam_lines)
        if t not in available or creator is None:
            checklist.append(_item("engagement", f"Engagement draft · {type_label(t)}", f"{codes} · this engagement type is not set up in the platform yet; create it by hand",
                                   "Not created", "Chief Auditor"))
            continue
        from app.engagements.service import create_engagement

        e = create_engagement(db, creator, org, name=f"{type_label(t)} {start.year}", type=t)
        e.wizard_state = {"auto_name": False, "prefill": {"source": "handoff", "proposal_id": proposal.id}}
        e.created_at = created_at + timedelta(seconds=i)
        fee = money(sum(ol.line_value for ol, _ in fam_lines))
        db.add(EngagementCommercial(organization_id=org.id, engagement_id=e.id, order_id=order.id, fee_total=fee, milestones=default_milestones(fee), created_by=actor_id))
        for ol, _ in fam_lines:
            ol.engagement_id = e.id
        checklist.append(_item("engagement", f"Engagement draft · {type_label(t)}", f"{codes} · New Client wizard pre-filled", "Awaiting Chief Auditor", "Chief Auditor",
                               f"/clients/{org.id}/setup/company", e.id))
        if t == primary:
            primary_engagement = e
    if primary_engagement is not None:
        _copy_contacts(db, opp, acceptance, org, primary_engagement, actor_id)
        _scoping_prefill(db, proposal, org, primary_engagement)

    # 4. subscription and entitlements for recurring lines
    recurring = [(ol, item) for ol, item in olines if ol.recurring]
    if recurring:
        sub = _subscription(db, org, order, recurring, terms, start, end, actor_id)
        checklist.append(_item("subscription", f"Subscription · {_plan_label(sub)}", f"{', '.join(ol.catalog_code for ol, _ in recurring)} · "
                               f"{(end.year - start.year) * 12 + end.month - start.month + 1} months · renewal alert at 90 days", "Created", None,
                               f"/staff/clients/{org.id}/plan", sub.id))

    # 5. hours banks and retainers
    for ol, item in olines:
        base = code_base(ol.catalog_code)
        if base in BANK_CODES:
            inc = (item.included_quantities if item else None) or {}
            hours = ol.qty * inc.get("advisor_hours", 1) if inc else ol.qty
            b = HoursBank(organization_id=org.id, order_line_id=ol.id, code=ol.catalog_code, label=BANK_CODES[base], hours_purchased=hours, expires_on=end, created_by=actor_id)
            db.add(b)
            db.flush()
            checklist.append(_item("hours_bank", f"Hours bank · {ol.catalog_code}", f"{hours:g} h · expires {end.isoformat()}", "Created", None, "/staff/time", b.id))
    _retainers(db, org, olines, lines, checklist, actor_id)

    # 6. partner commission
    checklist.append(_commission(db, opp, order, y1))

    # 7. hand-off record, opportunity won, notifications
    separate = sorted({ol.catalog_code for ol, _ in olines if needs_separate_team(ol.catalog_code)})
    h = Handoff(organization_id=org.id, opportunity_id=opp.id, proposal_id=proposal.id, acceptance_id=getattr(acceptance, "id", None), order_id=order.id, items=checklist,
                accepted_by={"name": getattr(acceptance, "name", None), "title": getattr(acceptance, "title", None), "po_number": getattr(acceptance, "po_number", None),
                             "at": (getattr(acceptance, "accepted_at", None) or utcnow()).isoformat(), "version": getattr(proposal, "version", 1)},
                year1_value=y1, needs_separate_team=separate, team={"account_owner_id": opp.owner_id}, status="awaiting", created_by=actor_id)
    db.add(h)
    if opp.stage != "won":
        opp.stage, opp.closed_at = "won", utcnow()
    db.flush()
    audit.record(db, actor_id=actor_id, action="handoff.created", obj=h, organization_id=org.id,
                 summary=f"{org.name}: proposal v{getattr(proposal, 'version', 1)} accepted; order {order.ref} and hand-off records created")
    link = f"/sales/opportunities/{opp.id}/handoff"
    notify(db, users_with_roles(db, ["chief_auditor"]), "handoff_engagements", f"{org.name}: approve the engagement drafts and team", "A proposal was accepted. Nothing has been sent to the client.", link)
    notify(db, users_with_roles(db, ["admin"]), "handoff_client_setup", f"{org.name}: set up the new client", f"Order {order.ref} is open.", link)
    notify(db, users_with_roles(db, ["admin"]), "handoff_billing", f"{org.name}: order {order.ref} for the billing export", f"Year 1 value ${y1:,.0f}.", f"/staff/clients/{org.id}/plan")
    if owner is not None and owner.id != actor_id:
        notify(db, [owner], "handoff_ready", f"{org.name}: hand-off to delivery is ready to confirm", None, link)
    return h


def default_milestones(fee: float) -> list[dict]:
    half = money(fee / 2)
    return [{"label": "50% on start", "trigger": "sign_off_1", "pct": 50, "amount": half, "status": "not_reached"},
            {"label": "50% on report", "trigger": "sign_off_7", "pct": 50, "amount": money(fee - half), "status": "not_reached"}]


def _plan_label(sub: Subscription) -> str:
    from app.monitoring.service import PLAN_LABELS

    return PLAN_LABELS.get(sub.plan, sub.plan) + (f", {sub.tier}" if sub.tier else "")


def _plan_from(recurring) -> tuple[str | None, str | None]:
    for ol, item in recurring:
        if code_base(ol.catalog_code) == "M-01":
            name = (item.name if item else None) or ol.description or ""
            plan = "monitor_plus" if "plus" in name.lower() or ol.catalog_code[-1:] in ("d", "e", "f") else "monitor"
            tier = name.split(",", 1)[1].strip() if "," in name else None
            return plan, tier
    return None, None


def _subscription(db: Session, org: Organization, order: Order, recurring, terms: dict, start: date, end: date, actor_id: str | None) -> Subscription:
    from app.monitoring.service import current_subscription

    plan, tier = _plan_from(recurring)
    prev = current_subscription(db, org.id)
    plan = plan or (prev.plan if prev else None) or org.subscription_plan or "audit_only"
    region = (terms.get("data_region") or org.data_region or "us").lower()[:4]
    if prev is not None:
        prev.end_on = today()
    sub = Subscription(organization_id=org.id, plan=plan, tier=tier, order_id=order.id, start_on=start, term_end_on=end, auto_renew=bool(terms.get("auto_renew", False)),
                       data_region=region, support_level=terms.get("support_level") or "Business hours", onboarding_fee_waived=terms.get("onboarding_fee_waived"),
                       set_by=actor_id, note=f"From order {order.ref}", created_by=actor_id)
    db.add(sub)
    db.flush()
    org.subscription_plan = plan
    if not org.data_region:
        org.data_region = region
    for ol, item in recurring:
        ol.subscription_id = sub.id
        for k, v in entitlement_limits(ol, item).items():
            db.add(Entitlement(organization_id=org.id, subscription_id=sub.id, key=k, limit=v, source_order_line_id=ol.id, created_by=actor_id))
    db.flush()
    return sub


# Words the price list uses for included quantities, and the entitlement each one is (spec B1 keys).
INCLUDED_ALIASES = {"systems": "ai_systems", "ai_systems": "ai_systems", "users": "seats", "user_seats": "seats", "seats": "seats", "states": "alert_packs",
                    "gb": "vault_gb", "storage_gb": "vault_gb", "hours": "advisor_hours", "agents": "agents_protected", "actions": "agent_actions_month",
                    "questionnaires": "questionnaires_year", "holds": "legal_holds", "briefings": "litigation_briefings", "approvers": "approver_seats"}
# The entitlement a subscription line carries when its catalog row names none (spec §2.2).
CODE_KEYS = {"M-01": "ai_systems", "M-02": "seats", "M-03": "alert_packs", "M-04": "litigation_briefings", "M-06": "vault_gb", "M-09": "trust_center",
             "M-10": "questionnaires_year", "M-11": "tracing_systems", "M-14": "api_access"}


def _ceiling(name: str | None) -> float | None:
    """The upper bound a tier name states: "up to 10 systems" → 10, "11–50 systems" → 50, "1–3 states" → 3."""
    m = re.search(r"(?:up to|[0-9][0-9,]*\s*[–-])\s*([0-9][0-9,]*)", name or "")
    return float(m.group(1).replace(",", "")) if m else None


def entitlement_limits(ol: OrderLine, item: cat.Item | None) -> dict[str, float]:
    from app.commercial.models import ENTITLEMENT_KEYS

    out: dict[str, float] = {}
    for k, v in ((item.included_quantities if item else None) or ol.included_quantities or {}).items():
        key = INCLUDED_ALIASES.get(k, k)
        if key in ENTITLEMENT_KEYS:
            out[key] = out.get(key, 0) + float(v) * ol.qty
    key = (item.entitlement_key if item else None) or ol.entitlement_key or CODE_KEYS.get(code_base(ol.catalog_code))
    if key in ENTITLEMENT_KEYS and key not in out:
        if key in HARD_KEYS:
            out[key] = 1
        else:
            ceiling = _ceiling((item.name if item else None) or ol.description)
            out[key] = ceiling * ol.qty if ceiling else ol.qty
    return {k: (1 if k in HARD_KEYS else v) for k, v in out.items()}


def _retainers(db: Session, org: Organization, olines, plines, checklist: list, actor_id: str | None) -> None:
    by_base: dict[str, list] = {}
    for ol, item in olines:
        base = code_base(ol.catalog_code)
        if base in RETAINER_CODES:
            by_base.setdefault(base, []).append((ol, item))
    for base, group in by_base.items():
        rtype = RETAINER_CODES[base]
        standing = next(((ol, it) for ol, it in group if ol.recurring), group[0])
        ol, item = standing
        hourly = None
        if base == "M-12":
            activated = next((o for o, _ in group if not o.recurring), None)
            if activated is not None:
                hourly = activated.unit_price
            else:
                b = cat.get_item(db, "M-12b")
                hourly = b.list_price if b else None
        inc = (item.included_quantities if item else None) or {}
        r = Retainer(organization_id=org.id, order_line_id=ol.id, code=ol.catalog_code, type=rtype, monthly_fee=ol.unit_price if ol.recurring else 0, hourly_rate=hourly,
                     monthly_hours=inc.get("advisor_hours"), status="standing", created_by=actor_id)
        db.add(r)
        db.flush()
        label = {"incident_response": "Incident response retainer", "fractional_officer": "Fractional AI Governance Officer"}[rtype]
        checklist.append(_item("retainer", f"Retainer · {label}", f"{ol.catalog_code} · ${r.monthly_fee:,.0f} a month" + (f" · ${hourly:,.0f}/h when activated" if hourly else ""),
                               "Created", None, "/staff/time", r.id))


def _commission(db: Session, opp: Opportunity, order: Order, y1: float) -> dict:
    partner_id = getattr(opp, "partner_id", None)
    if not partner_id:
        return _item("commission", "Partner commission", "No partner on this deal", "Not needed", None)
    try:
        from app.partners.service import commission_for_win  # R7
    except ImportError:
        return _item("commission", "Partner commission", "Partner records are not in the platform yet; record the commission by hand", "Not created", "Sales Manager")
    c = commission_for_win(db, opp, order, y1)
    if c is None:
        return _item("commission", "Partner commission", "No commission for this partner (law firms never get one)", "Not needed", None)
    return _item("commission", "Partner commission", "Commission recorded for the referring partner", "Created", "Finance (billing export)", "/staff/partners", getattr(c, "id", None))


def _copy_contacts(db: Session, opp: Opportunity, acceptance, org: Organization, e: Engagement, actor_id: str | None) -> None:
    people: list[dict] = []
    try:
        from app.sales.models import OpportunityContact  # R2
    except ImportError:
        OpportunityContact = None
    if OpportunityContact is not None:
        for c in db.scalars(select(OpportunityContact).where(OpportunityContact.opportunity_id == opp.id)):
            people.append({"name": c.name, "title": getattr(c, "title", None), "email": getattr(c, "email", None), "phone": getattr(c, "phone", None),
                           "role": (getattr(c, "contact_role", None) or "").lower()})
    signer = getattr(acceptance, "email", None)
    if signer and signer.lower() not in {(p["email"] or "").lower() for p in people}:
        people.append({"name": getattr(acceptance, "name", None), "title": getattr(acceptance, "title", None), "email": signer, "phone": None, "role": ""})
    taken = {c.contact_role for c in db.scalars(select(ClientContact).where(ClientContact.engagement_id == e.id, ClientContact.deleted_at.is_(None)))}
    for p in people:
        role = p["role"] if p["role"] in CONTACT_ORDER else next((v for k, v in CONTACT_ALIASES.items() if k in p["role"]), None)
        if role is None or role in taken:
            role = next((r for r in ("project_lead", "technical_lead", "compliance_lead") if r not in taken), None)
        if role is None:
            continue  # one contact per role in the wizard; the rest stay on the opportunity
        taken.add(role)
        db.add(ClientContact(organization_id=org.id, engagement_id=e.id, contact_role=role, name=(p["name"] or "")[:120] or None, title=(p["title"] or "")[:120] or None,
                             email=p["email"], phone=p["phone"], created_by=actor_id))
    db.flush()


def _scoping_prefill(db: Session, proposal, org: Organization, e: Engagement) -> None:
    """Locations, laws, departments and system count from the locked questionnaire (R3), when it offers a pre-fill."""
    try:
        from app.scoping import service as scoping  # R3
    except ImportError:
        return
    fill = getattr(scoping, "prefill_engagement", None)
    if fill is not None:
        fill(db, proposal, org, e)


# ---- SM-13 screen: confirm the hand-off, the delivery team and independence
def for_opportunity(db: Session, opportunity_id: str) -> Handoff | None:
    return db.scalar(select(Handoff).where(Handoff.opportunity_id == opportunity_id, Handoff.deleted_at.is_(None)).order_by(Handoff.created_at.desc()).limit(1))


def separate_team_user_ids(db: Session, client_id: str) -> set[str]:
    """People the Chief Auditor recorded as a separate delivery team for this client (rules I-2, I-3). R4's team check
    keeps them off the client's audit team; the X-01 officer on a retainer is included."""
    out: set[str] = set()
    for h in db.scalars(select(Handoff).where(Handoff.organization_id == client_id, Handoff.deleted_at.is_(None))):
        out |= set((h.team or {}).get("separate_team_user_ids") or [])
    out |= {r.officer_user_id for r in db.scalars(select(Retainer).where(Retainer.organization_id == client_id, Retainer.officer_user_id.is_not(None)))}
    return out


def _audit_team_clash(db: Session, client_id: str, user_ids: list[str]) -> list[User]:
    from app.engagements.models import EngagementTeam

    rows = db.scalars(select(EngagementTeam.user_id).join(Engagement, Engagement.id == EngagementTeam.engagement_id)
                      .where(Engagement.client_id == client_id, Engagement.deleted_at.is_(None), EngagementTeam.deleted_at.is_(None), EngagementTeam.user_id.in_(user_ids)))
    return [db.get(User, uid) for uid in dict.fromkeys(rows)]


def confirm_independence(db: Session, actor: User, h: Handoff, user_ids: list[str], note: str | None) -> Handoff:
    from app.core.errors import Conflict, Invalid

    ids = list(dict.fromkeys(u for u in user_ids if u))
    if h.needs_separate_team and not ids:
        raise Invalid(errors=[{"field": "separate_team_user_ids", "message": "Name the people who will deliver these lines."}])
    for uid in ids:
        u = db.get(User, uid)
        org = db.get(Organization, u.organization_id) if u else None
        if org is None or org.type != "futran":
            raise Invalid(errors=[{"field": "separate_team_user_ids", "message": "Choose Futran staff."}])
    clash = _audit_team_clash(db, h.organization_id, ids)
    if clash:
        raise Conflict(f"{', '.join(u.name for u in clash)} {'is' if len(clash) == 1 else 'are'} on this client's audit team. A separate team delivers these lines.")
    h.team = (h.team or {}) | {"separate_team_user_ids": ids, "independence_note": " ".join((note or "").split()) or None}
    h.independence_confirmed_by, h.independence_confirmed_at = actor.id, utcnow()
    officer = ids[0] if ids and "X-01" in (h.needs_separate_team or []) else None
    if officer:
        for r in db.scalars(select(Retainer).where(Retainer.organization_id == h.organization_id, Retainer.type == "fractional_officer", Retainer.officer_user_id.is_(None))):
            r.officer_user_id = officer
    db.flush()
    audit.record(db, actor_id=actor.id, action="handoff.independence_confirmed", obj=h, summary=f"Confirmed a separate delivery team for {', '.join(h.needs_separate_team)}")
    return h


def confirm(db: Session, actor: User, h: Handoff, account_owner_id: str | None) -> Handoff:
    from app.core.errors import Conflict, Invalid

    if h.needs_separate_team and h.independence_confirmed_by is None:
        raise Conflict("The Chief Auditor must confirm a separate delivery team for " + ", ".join(h.needs_separate_team) + " first.")
    if account_owner_id:
        u = db.get(User, account_owner_id)
        org = db.get(Organization, u.organization_id) if u else None
        if org is None or org.type != "futran":
            raise Invalid(errors=[{"field": "account_owner_id", "message": "Choose someone at Futran."}])
        h.team = (h.team or {}) | {"account_owner_id": account_owner_id}
        opp = db.get(Opportunity, h.opportunity_id) if h.opportunity_id else None
        if opp is not None:
            opp.owner_id = account_owner_id
    h.status, h.confirmed_by, h.confirmed_at = "confirmed", actor.id, utcnow()
    db.flush()
    audit.record(db, actor_id=actor.id, action="handoff.confirmed", obj=h, summary="Confirmed the hand-off to delivery")
    return h


def handoff_out(db: Session, h: Handoff) -> dict:
    org = db.get(Organization, h.organization_id)
    name = lambda uid: (db.get(User, uid).name if uid and db.get(User, uid) else None)  # noqa: E731
    team = h.team or {}
    items = []
    for it in h.items or []:
        it = dict(it)
        if it["kind"] == "engagement" and it.get("ref_id"):
            e = db.get(Engagement, it["ref_id"])
            if e is not None and e.status not in ("draft", "pending_approval"):
                it["status"] = "Approved"
            elif e is not None and e.status == "pending_approval":
                it["status"] = "Submitted to Chief Auditor"
        items.append(it)
    return {
        "id": h.id, "opportunity_id": h.opportunity_id, "client_id": h.organization_id, "client_name": org.name if org else "", "client_status": org.status if org else None,
        "order_id": h.order_id, "items": items, "accepted_by": h.accepted_by, "year1_value": h.year1_value, "needs_separate_team": h.needs_separate_team or [],
        "team": {"account_owner_id": team.get("account_owner_id"), "account_owner_name": name(team.get("account_owner_id")),
                 "separate_team": [{"id": u, "name": name(u)} for u in team.get("separate_team_user_ids") or []], "independence_note": team.get("independence_note")},
        "status": h.status, "independence_confirmed_by": name(h.independence_confirmed_by),
        "independence_confirmed_at": h.independence_confirmed_at.isoformat() if h.independence_confirmed_at else None,
        "confirmed_by": name(h.confirmed_by), "confirmed_at": h.confirmed_at.isoformat() if h.confirmed_at else None,
    }
