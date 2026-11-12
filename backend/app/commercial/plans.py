"""G-01: plans, entitlements, usage and the billing export (spec B1).

A client's commercial position: active order lines → the current monitoring `Subscription` (F3, extended) →
`Entitlement`s. Usage is measured once a day from platform data. Limits are soft (user's default, R2-Q8): at 90% the
CAICO and the account owner are told and an `entitlement_limit` opportunity opens; at 100% the client keeps working,
Futran sees "over plan" and the overage goes on the billing export. Only `api_access` and `trust_center` are hard
(feature on or off), and only for a client whose plan comes from an order: clients set up before Release 2 keep
today's behaviour. A `renewal_due` opportunity opens 90 days before a recurring order line ends.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.commercial import catalog as cat
from app.commercial.common import add_months, futran_org, money, users_with_roles
from app.commercial.models import (HARD_KEYS, BillingExportRun, EngagementCommercial, Entitlement, Handoff, HoursBank, Order, OrderLine, Retainer, TimeEntry,
                                   UsageRecord)
from app.core.clock import today, utcnow
from app.core.errors import Invalid
from app.documents.csvsafe import to_csv
from app.monitoring.models import Subscription
from app.notifications.service import notify
from app.sales.models import Opportunity
from app.tenancy.models import Organization, User

KEY_LABELS = {
    "ai_systems": "AI systems in register", "seats": "Client user seats", "alert_packs": "Alert packs (states)", "litigation_briefings": "Litigation briefings",
    "vault_gb": "Vault storage", "retention_years": "Retention (years)", "legal_holds": "Legal holds", "tracing_systems": "Tracing systems",
    "agents_protected": "Agents protected", "agent_actions_month": "Agent actions a month", "approver_seats": "Approver seats",
    "questionnaires_year": "Questionnaires a year", "advisor_hours": "Advisor hours", "trust_center": "Trust Center", "api_access": "API access",
}
KEY_UNITS = {"vault_gb": "GB", "advisor_hours": "h"}
REGIONS = ("us", "eu", "in")
COLUMNS = ["period", "client_ref", "client_name", "order_ref", "po_number", "line_type", "code", "description", "qty", "unit_price", "discount_pct", "amount",
           "currency", "service_start", "service_end", "billing_contact"]


def current_subscription(db: Session, org_id: str) -> Subscription | None:
    from app.monitoring.service import current_subscription as cur

    return cur(db, org_id)


# ---------------------------------------------------------------- usage
def _ai_systems(db: Session, org_id: str, on: date) -> float:
    from app.register.models import RegisterSystem

    return db.scalar(select(func.count(RegisterSystem.id)).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None),
                                                                 RegisterSystem.stage != "retired")) or 0


def _seats(db: Session, org_id: str, on: date) -> float:
    from app.auth.models import AuthSession

    signed_in = select(AuthSession.user_id).where(AuthSession.organization_id == org_id)
    return db.scalar(select(func.count(User.id)).where(User.organization_id == org_id, User.deleted_at.is_(None), User.status == "active", User.id.in_(signed_in))) or 0


def _alert_packs(db: Session, org_id: str, on: date) -> float:
    from app.engagements.models import ClientLocation

    codes = db.scalars(select(ClientLocation.subdivision_code).where(ClientLocation.organization_id == org_id, ClientLocation.deleted_at.is_(None),
                                                                      ClientLocation.in_scope.is_(True), ClientLocation.subdivision_code.like("US-%")))
    return len(set(codes))


def _vault_gb(db: Session, org_id: str, on: date) -> float:
    try:
        from app.vault import service as vault  # R7 storage metering

        meter = getattr(vault, "storage_used_gb", None)
        if meter is not None:
            return float(meter(db, org_id))
    except ImportError:
        pass
    from app.files.models import FileObject

    size = db.scalar(select(func.coalesce(func.sum(FileObject.size), 0)).where(FileObject.organization_id == org_id, FileObject.deleted_at.is_(None))) or 0
    return round(size / 1024 ** 3, 2)


def _tracing_systems(db: Session, org_id: str, on: date) -> float:
    from app.tracing.models import AddonSubscription

    ids: set[str] = set()
    for s in db.scalars(select(AddonSubscription).where(AddonSubscription.organization_id == org_id, AddonSubscription.status == "active", AddonSubscription.deleted_at.is_(None))):
        ids |= set(s.ai_system_ids or [])
    return len(ids)


def _questionnaires_year(db: Session, org_id: str, on: date) -> float:
    from app.ai.models import Questionnaire

    since = datetime.combine(on - timedelta(days=365), datetime.min.time())
    return db.scalar(select(func.count(Questionnaire.id)).where(Questionnaire.organization_id == org_id, Questionnaire.deleted_at.is_(None),
                                                                Questionnaire.status == "completed", Questionnaire.completed_at >= since)) or 0


def _advisor_hours(db: Session, org_id: str, on: date) -> float:
    sub = current_subscription(db, org_id)
    start = sub.start_on if sub and sub.start_on else date(on.year, 1, 1)
    return db.scalar(select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
        TimeEntry.organization_id == org_id, TimeEntry.deleted_at.is_(None), TimeEntry.activity == "advisory", TimeEntry.hours_bank_id.is_(None),
        TimeEntry.retainer_id.is_(None), TimeEntry.engagement_id.is_(None), TimeEntry.on_date >= start, TimeEntry.on_date <= on)) or 0


MEASURES = {"ai_systems": _ai_systems, "seats": _seats, "alert_packs": _alert_packs, "vault_gb": _vault_gb, "tracing_systems": _tracing_systems,
            "questionnaires_year": _questionnaires_year, "advisor_hours": _advisor_hours}


def measure(db: Session, org_id: str, on: date) -> dict[str, float]:
    """Today's usage for every key the platform can count. Each measure runs in its own savepoint."""
    out: dict[str, float] = {}
    for key, fn in MEASURES.items():
        try:
            with db.begin_nested():
                out[key] = float(fn(db, org_id, on))
        except Exception:  # a module that cannot be read today leaves that key unmeasured
            continue
    return out


def _record(db: Session, org_id: str, key: str, on: date, value: float) -> None:
    rec = db.scalar(select(UsageRecord).where(UsageRecord.organization_id == org_id, UsageRecord.key == key, UsageRecord.measured_on == on))
    if rec is None:
        db.add(UsageRecord(organization_id=org_id, key=key, measured_on=on, value=value))
    else:
        rec.value = value


def latest_usage(db: Session, org_id: str, *, upto: date | None = None, since: date | None = None) -> dict[str, tuple[float, date]]:
    q = select(UsageRecord).where(UsageRecord.organization_id == org_id).order_by(UsageRecord.measured_on)
    if upto:
        q = q.where(UsageRecord.measured_on <= upto)
    if since:
        q = q.where(UsageRecord.measured_on >= since)
    return {r.key: (r.value, r.measured_on) for r in db.scalars(q)}


def entitlements(db: Session, sub: Subscription | None) -> dict[str, list[Entitlement]]:
    if sub is None:
        return {}
    out: dict[str, list[Entitlement]] = {}
    for e in db.scalars(select(Entitlement).where(Entitlement.subscription_id == sub.id, Entitlement.deleted_at.is_(None)).order_by(Entitlement.created_at)):
        out.setdefault(e.key, []).append(e)
    return out


def feature_allowed(db: Session, org_id: str, key: str) -> bool:
    """Hard limits: `api_access` and `trust_center` are on only when the plan includes them. Clients whose plan did not
    come from an order (everyone before Release 2) keep today's behaviour; every other key is soft and always allowed."""
    if key not in HARD_KEYS:
        return True
    sub = current_subscription(db, org_id)
    if sub is None or sub.order_id is None:
        return True
    return any(e.limit >= 1 for e in entitlements(db, sub).get(key, []))


def account_owner(db: Session, org_id: str) -> User | None:
    h = db.scalar(select(Handoff).where(Handoff.organization_id == org_id, Handoff.deleted_at.is_(None)).order_by(Handoff.created_at.desc()).limit(1))
    uid = (h.team or {}).get("account_owner_id") if h else None
    if uid is None:
        uid = db.scalar(select(Opportunity.owner_id).where(Opportunity.organization_id == org_id, Opportunity.stage == "won", Opportunity.owner_id.is_not(None))
                        .order_by(Opportunity.closed_at.desc()).limit(1))
    return db.get(User, uid) if uid else None


def _client_caicos(db: Session, org_id: str) -> list[User]:
    from app.tenancy.models import RoleAssignment

    return list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(
        User.organization_id == org_id, RoleAssignment.role == "caico", RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None))))


def _check_limits(db: Session, org: Organization, sub: Subscription, used: dict[str, float], now: datetime) -> int:
    from app.sales.service import open_from_trigger

    n = 0
    for key, rows in entitlements(db, sub).items():
        if key in HARD_KEYS or key not in used:
            continue
        limit = sum(r.limit for r in rows)
        if limit <= 0 or used[key] < 0.9 * limit or any(r.alerted_90_at for r in rows):
            continue
        for r in rows:
            r.alerted_90_at = now
        pct = round(100 * used[key] / limit)
        label = KEY_LABELS.get(key, key)
        owner = account_owner(db, org.id)
        why = f"{label} at {pct}% of plan ({used[key]:g} of {limit:g})"
        with db.begin_nested():
            open_from_trigger(db, org.id, "entitlement_limit", f"{sub.id}:{key}", service=f"Plan upgrade: {label.lower()}", why_now=why, service_kind="addon",
                              owner_id=owner.id if owner else None)
        notify(db, [*_client_caicos(db, org.id), owner], "entitlement_limit", f"{org.name}: {why}",
               "The platform keeps working above the limit; usage over the plan is billed as overage.", None)
        n += 1
    return n


def _renewals(db: Session, on: date) -> int:
    from app.sales.service import open_from_trigger

    due = list(db.scalars(select(OrderLine).where(OrderLine.recurring.is_(True), OrderLine.deleted_at.is_(None), OrderLine.end_on.is_not(None),
                                                  OrderLine.renewal_opportunity_id.is_(None), OrderLine.end_on <= on + timedelta(days=90), OrderLine.end_on >= on)))
    groups: dict[tuple[str, date], list[OrderLine]] = {}
    for ln in due:
        groups.setdefault((ln.order_id, ln.end_on), []).append(ln)
    n = 0
    for (order_id, end_on), lines in groups.items():
        order = db.get(Order, order_id)
        if order is None or order.status == "cancelled":
            continue
        org = db.get(Organization, order.organization_id)
        items = cat.items_by_codes(db, [ln.catalog_code for ln in lines])
        value = 0.0
        for ln in lines:  # renewals use current prices (spec §4.9)
            it = items.get(ln.catalog_code)
            value += (it.list_price * ln.qty * (ln.periods_per_year or 1)) if it and it.list_price is not None else ln.line_value
        owner = account_owner(db, org.id)
        with db.begin_nested():
            opp = open_from_trigger(db, org.id, "renewal_due", f"{order.id}:{end_on.isoformat()}", service=f"Renewal of order {order.ref}",
                                    why_now=f"{len(lines)} recurring line{'s' if len(lines) != 1 else ''} end on {end_on.isoformat()}", service_kind="other",
                                    owner_id=owner.id if owner else None, value=int(round(value)))
        for ln in lines:
            ln.renewal_opportunity_id = opp.id
        if owner is not None:
            notify(db, [owner], "renewal_due", f"{org.name}: order {order.ref} renews on {end_on.isoformat()}", None, f"/staff/clients/{org.id}/plan")
        n += 1
    return n


def commercial_clients(db: Session) -> list[Organization]:
    ids = db.scalars(select(Subscription.organization_id).where(Subscription.order_id.is_not(None), Subscription.end_on.is_(None), Subscription.deleted_at.is_(None)))
    return [o for o in (db.get(Organization, i) for i in set(ids)) if o is not None and o.deleted_at is None]


def run_daily_usage(db: Session, settings, now) -> int:
    """Daily job: measure usage for every client on an ordered plan, send 90% notices, open renewal opportunities and,
    on the first of the month, write the all-clients billing export for the month before."""
    now = now if isinstance(now, datetime) else datetime.combine(now, datetime.min.time())
    on = now.date()
    n = 0
    for org in commercial_clients(db):
        sub = current_subscription(db, org.id)
        if sub is None:
            continue
        used = measure(db, org.id, on)
        for key, value in used.items():
            _record(db, org.id, key, on, value)
        db.flush()
        _check_limits(db, org, sub, used, now)
        n += 1
    _renewals(db, on)
    if on.day == 1:
        prev = (on - timedelta(days=1)).strftime("%Y-%m")
        if db.scalar(select(BillingExportRun.id).where(BillingExportRun.period == prev, BillingExportRun.client_id.is_(None)).limit(1)) is None:
            run = run_export(db, None, prev, None)
            notify(db, users_with_roles(db, ["admin"]), "billing_export", f"Billing export for {prev} is ready", f"{run.rows} rows.", "/staff/billing")
    db.flush()
    return n


# ---------------------------------------------------------------- the G-01 screen
def plan_view(db: Session, org: Organization, on: date | None = None) -> dict:
    from app.monitoring.service import PLAN_LABELS, plan_of

    on = on or today()
    sub = current_subscription(db, org.id)
    used = latest_usage(db, org.id)
    ents = []
    for key, rows in entitlements(db, sub).items():
        limit = sum(r.limit for r in rows)
        u = used.get(key, (None, None))[0]
        hard = key in HARD_KEYS
        pct = round(100 * u / limit) if (u is not None and limit and not hard) else None
        ents.append({"key": key, "label": KEY_LABELS.get(key, key), "unit": KEY_UNITS.get(key), "limit": limit, "used": u, "pct": pct, "hard": hard,
                     "enabled": limit >= 1 if hard else None, "over_plan": bool(not hard and u is not None and u > limit),
                     "near_limit": bool(not hard and pct is not None and pct >= 90), "measured_on": used.get(key, (None, None))[1].isoformat() if key in used else None})
    order = db.get(Order, sub.order_id) if sub and sub.order_id else None
    orders = list(db.scalars(select(Order).where(Order.organization_id == org.id, Order.deleted_at.is_(None)).order_by(Order.created_at)))
    lines = []
    for o in orders:
        for ln in db.scalars(select(OrderLine).where(OrderLine.order_id == o.id, OrderLine.deleted_at.is_(None)).order_by(OrderLine.created_at)):
            ent = ", ".join(f"{e.key} {e.limit:g}" for e in db.scalars(select(Entitlement).where(Entitlement.source_order_line_id == ln.id)))
            lines.append({"id": ln.id, "order_ref": o.ref, "code": ln.catalog_code, "description": ln.description, "qty": ln.qty, "unit_price": ln.unit_price,
                          "billing": _billing_label(ln), "start_on": _iso(ln.start_on), "end_on": _iso(ln.end_on), "entitlement": ent or None,
                          "line_value": ln.line_value, "engagement_id": ln.engagement_id, "change_order_id": ln.change_order_id})
    runs = db.scalars(select(BillingExportRun).where((BillingExportRun.client_id == org.id) | BillingExportRun.client_id.is_(None)).order_by(BillingExportRun.run_at.desc()).limit(6))
    term_end = sub.term_end_on if sub else None
    plan = plan_of(org) if sub is None else sub.plan
    return {
        "client": {"id": org.id, "name": org.name, "client_ref": org.client_ref, "status": org.status},
        "plan": {"plan": plan, "plan_label": PLAN_LABELS.get(plan, plan), "tier": sub.tier if sub else None, "start_on": _iso(sub.start_on) if sub else None,
                 "term_end_on": _iso(term_end), "renewal_alert_on": _iso(term_end - timedelta(days=90)) if term_end else None, "auto_renew": sub.auto_renew if sub else None,
                 "data_region": sub.data_region if sub else None, "support_level": sub.support_level if sub else None,
                 "onboarding_fee_waived": sub.onboarding_fee_waived if sub else None, "order_ref": order.ref if order else None, "from_order": bool(order)},
        "entitlements": ents, "over_plan": [e["label"] for e in ents if e["over_plan"]], "order_lines": lines,
        "exports": [{"id": r.id, "period": r.period, "rows": r.rows, "run_at": r.run_at.isoformat(), "all_clients": r.client_id is None} for r in runs],
    }


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def _billing_label(ln: OrderLine) -> str:
    if not ln.recurring:
        return "One-time"
    return {1: "Annual", 4: "Quarterly", 12: "Monthly"}.get(ln.periods_per_year or 1, f"{ln.periods_per_year} a year")


def update_settings(db: Session, actor: User, org: Organization, data: dict) -> Subscription:
    from app.monitoring.service import plan_of

    sub = current_subscription(db, org.id)
    if sub is None:
        sub = Subscription(organization_id=org.id, plan=plan_of(org), start_on=today(), set_by=actor.id, created_by=actor.id)
        db.add(sub)
        db.flush()
    before = {k: getattr(sub, k) for k in ("tier", "term_end_on", "auto_renew", "data_region", "support_level", "onboarding_fee_waived")}
    errors = []
    if "data_region" in data and data["data_region"] is not None:
        region = str(data["data_region"]).lower()
        ticket = " ".join(str(data.get("migration_ticket") or "").split())
        if region not in REGIONS:
            errors.append({"field": "data_region", "message": "Choose US, EU or India."})
        elif sub.data_region and region != sub.data_region and not ticket:
            errors.append({"field": "migration_ticket", "message": "The data region is set when the client is created. Moving it needs a migration ticket reference."})
        else:
            sub.data_region = region
            if ticket:
                org.data_region = region
    for k in ("tier", "support_level"):
        if k in data:
            v = " ".join(str(data[k] or "").split())[: (60 if k == "tier" else 30)]
            setattr(sub, k, v or None)
    for k in ("auto_renew", "onboarding_fee_waived"):
        if k in data and data[k] is not None:
            setattr(sub, k, bool(data[k]))
    if "term_end_on" in data and data["term_end_on"]:
        try:
            sub.term_end_on = data["term_end_on"] if isinstance(data["term_end_on"], date) else date.fromisoformat(data["term_end_on"])
        except ValueError:
            errors.append({"field": "term_end_on", "message": "Enter a date."})
    if errors:
        raise Invalid(errors=errors)
    after = {k: getattr(sub, k) for k in before}
    changed = {k: (str(before[k]), str(after[k])) for k in before if before[k] != after[k]}
    if changed:
        audit.record(db, actor_id=actor.id, action="subscription.settings", obj=sub, organization_id=org.id, before={k: v[0] for k, v in changed.items()},
                     after={k: v[1] for k, v in changed.items()} | ({"migration_ticket": data.get("migration_ticket")} if "data_region" in changed else {}),
                     summary=f"{org.name}: plan settings changed ({', '.join(changed)})")
    db.flush()
    return sub


# ---------------------------------------------------------------- billing export
def _period_bounds(period: str) -> tuple[date, date]:
    try:
        y, m = (int(x) for x in period.split("-"))
        start = date(y, m, 1)
    except (ValueError, TypeError):
        raise Invalid(errors=[{"field": "period", "message": "Enter a month as YYYY-MM."}]) from None
    return start, date(y, m, calendar.monthrange(y, m)[1])


def _billing_dates(ln: OrderLine) -> list[date]:
    if ln.start_on is None:
        return []
    if not ln.recurring:
        return [ln.start_on]
    step = 12 // max(1, ln.periods_per_year or 1)
    out, k, d = [], 0, ln.start_on
    end = ln.end_on or add_months(ln.start_on, 12)
    while d <= end and k < 240:
        out.append(d)
        k += 1
        d = add_months(ln.start_on, step * k)
    return out


def _milestone_reached_on(db: Session, engagement_id: str, m: dict) -> date | None:
    if m.get("reached_on"):
        return date.fromisoformat(m["reached_on"])
    trig = m.get("trigger") or ""
    if trig.startswith("sign_off_"):
        from app.signoffs.models import SignOff

        at = db.scalar(select(func.max(SignOff.approved_at)).where(SignOff.engagement_id == engagement_id, SignOff.number == int(trig.rsplit("_", 1)[1]),
                                                                    SignOff.status == "approved"))
        return at.date() if at else None
    return None


def billing_rows(db: Session, period: str, client_id: str | None = None) -> list[list]:
    start, end = _period_bounds(period)
    q = select(Order).where(Order.deleted_at.is_(None), Order.status != "cancelled")
    if client_id:
        q = q.where(Order.organization_id == client_id)
    rows: list[list] = []
    for order in db.scalars(q.order_by(Order.ref)):
        org = db.get(Organization, order.organization_id)
        base = [period, org.client_ref, org.name, order.ref, order.po_number]

        def row(kind, code, desc, qty, unit, amount, s=None, e=None, disc=None):
            rows.append(base + [kind, code, desc, f"{qty:g}", f"{money(unit):.2f}", "" if disc is None else f"{disc:g}", f"{money(amount):.2f}", "USD",
                                _iso(s), _iso(e), order.billing_contact])

        for ln in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id, OrderLine.deleted_at.is_(None)).order_by(OrderLine.created_at)):
            if ln.engagement_id and not ln.recurring:
                continue  # billed by the engagement's milestones
            if not ln.recurring and ln.catalog_code.startswith("M-12"):
                continue  # activated incident hours are billed as worked
            for d in _billing_dates(ln):
                if start <= d <= end:
                    disc = order.discount_recurring_pct if ln.recurring and order.discount_recurring_pct else None
                    amount = ln.unit_price * ln.qty * (1 - (disc or 0) / 100)
                    row("order_line", ln.catalog_code, ln.description, ln.qty, ln.unit_price, amount, d, add_months(d, 12 // max(1, ln.periods_per_year or 1)) - timedelta(days=1) if ln.recurring else None, disc)
        for com in db.scalars(select(EngagementCommercial).where(EngagementCommercial.order_id == order.id, EngagementCommercial.deleted_at.is_(None))):
            for m in com.milestones or []:
                reached = _milestone_reached_on(db, com.engagement_id, m)
                if reached and start <= reached <= end:
                    row("milestone", "", f"{m.get('label')}", 1, m.get("amount") or 0, m.get("amount") or 0, reached)
    orgs = {client_id} if client_id else {o for o in db.scalars(select(Order.organization_id).where(Order.deleted_at.is_(None)))}
    for oid in sorted(orgs):
        org = db.get(Organization, oid)
        sub = current_subscription(db, oid)
        order = db.get(Order, sub.order_id) if sub and sub.order_id else None
        base = [period, org.client_ref, org.name, order.ref if order else "", order.po_number if order else ""]

        def extra(kind, code, desc, qty, unit, amount, s=None, e=None):
            rows.append(base + [kind, code, desc, f"{qty:g}", f"{money(unit):.2f}", "", f"{money(amount):.2f}", "USD", _iso(s), _iso(e), order.billing_contact if order else None])

        used = latest_usage(db, oid, upto=end, since=start)
        for key, ents in entitlements(db, sub).items():
            if key in HARD_KEYS or key not in used:
                continue
            limit = sum(e.limit for e in ents)
            over = used[key][0] - limit
            if over <= 0:
                continue
            src = db.get(OrderLine, ents[0].source_order_line_id) if ents[0].source_order_line_id else None
            per_unit = (src.included_quantities or {}).get(key) if src else None
            unit = (src.unit_price / per_unit) if src and per_unit else (src.unit_price if src else 0)
            extra("overage", src.catalog_code if src else key, f"Over plan: {KEY_LABELS.get(key, key)} ({used[key][0]:g} used, {limit:g} in plan)", over, unit, over * unit,
                  used[key][1])
        from app.commercial import timesheet

        for bank in db.scalars(select(HoursBank).where(HoursBank.organization_id == oid, HoursBank.deleted_at.is_(None))):
            before = timesheet.bank_used(db, bank, upto=start - timedelta(days=1))
            through = timesheet.bank_used(db, bank, upto=end)
            over = max(0.0, through - bank.hours_purchased) - max(0.0, before - bank.hours_purchased)
            if over > 0:
                unit = timesheet.overage_rate(db, bank)
                extra("hours_overage", bank.code, f"{bank.label}: hours beyond the {bank.hours_purchased:g} h bank", over, unit, over * unit, start, end)
        for r in db.scalars(select(Retainer).where(Retainer.organization_id == oid, Retainer.status == "activated", Retainer.deleted_at.is_(None))):
            hours = db.scalar(select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(TimeEntry.retainer_id == r.id, TimeEntry.billable.is_(True), TimeEntry.deleted_at.is_(None),
                                                                                       TimeEntry.on_date >= start, TimeEntry.on_date <= end)) or 0
            if hours and r.hourly_rate:
                extra("retainer_hours", r.code, "Incident response hours (retainer activated)", hours, r.hourly_rate, hours * r.hourly_rate, start, end)
    rows += _commission_rows(db, period, start, end, client_id)
    return rows


def _commission_rows(db: Session, period: str, start: date, end: date, client_id: str | None) -> list[list]:
    try:
        from app.partners import service as partners  # R7
    except ImportError:
        return []
    due = getattr(partners, "commissions_due", None)
    if due is None:
        return []
    out = []
    for c in due(db, start, end, client_id) or []:
        g = c.get if isinstance(c, dict) else (lambda k, _c=c: getattr(_c, k, None))
        org = db.get(Organization, g("organization_id")) if g("organization_id") else None
        amount = money(g("amount") or 0)
        out.append([period, org.client_ref if org else "", org.name if org else "", g("order_ref") or "", "", "partner_commission", "X-07",
                    f"Partner commission: {g('partner_name') or ''}".strip(), "1", f"{amount:.2f}", "", f"{amount:.2f}", "USD", None, None, None])
    return out


def run_export(db: Session, actor: User | None, period: str, client_id: str | None) -> BillingExportRun:
    rows = billing_rows(db, period, client_id)
    content = to_csv(COLUMNS, rows)
    owner_org = client_id or (futran_org(db).id if futran_org(db) else "futran")
    run = BillingExportRun(organization_id=owner_org, period=period, client_id=client_id, run_by=actor.id if actor else None, run_at=utcnow(), content=content,
                           rows=len(rows), status="completed", created_by=actor.id if actor else None)
    db.add(run)
    db.flush()
    who = db.get(Organization, client_id).name if client_id else "all clients"
    audit.record(db, actor_id=actor.id if actor else None, action="billing.export", obj=run, summary=f"Billing export for {period}, {who}: {len(rows)} rows")
    return run
