"""G-03: time and hours (spec B3) — weekly timesheets, hours banks, retainers, standard cost and margin."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.commercial import catalog as cat
from app.commercial.models import HoursBank, OrderLine, TimeEntry


def bank_used(db: Session, bank: HoursBank, *, upto: date | None = None) -> float:
    q = select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(TimeEntry.hours_bank_id == bank.id, TimeEntry.deleted_at.is_(None), TimeEntry.status != "returned")
    if upto is not None:
        q = q.where(TimeEntry.on_date <= upto)
    return float(db.scalar(q) or 0)


def overage_rate(db: Session, bank: HoursBank) -> float:
    """Hours beyond the bank are priced from the catalog (the bank's own code), else at the price the bank was sold at."""
    item = cat.get_item(db, bank.code)
    if item is not None and item.list_price is not None:
        return float(item.list_price)
    ln = db.get(OrderLine, bank.order_line_id) if bank.order_line_id else None
    return float(ln.unit_price) if ln else 0.0


# ---------------------------------------------------------------- weekly timesheet
from datetime import datetime, timedelta  # noqa: E402

from app.audit_log import service as audit  # noqa: E402
from app.commercial.common import futran_org, money, users_with_roles  # noqa: E402
from app.commercial.models import ACTIVITIES, EngagementCommercial, Retainer, StandardCost  # noqa: E402
from app.core.clock import today, utcnow  # noqa: E402
from app.core.errors import Conflict, Forbidden, Invalid  # noqa: E402
from app.engagements.models import Engagement, EngagementTeam  # noqa: E402
from app.notifications.service import notify  # noqa: E402
from app.tenancy.models import Organization, RoleAssignment, User  # noqa: E402

ACTIVITY_LABELS = {"fieldwork": "Fieldwork", "report": "Report", "remediation_retest": "Remediation re-test", "policy_drafting": "Policy drafting",
                   "advisory": "Advisory", "incident_response": "Incident response", "litigation_support": "Litigation support", "training": "Training",
                   "other": "Other"}
CLOSED = ("completed", "archived")


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _targets(db: Session, user: User) -> dict[str, dict]:
    out: dict[str, dict] = {}
    rows = db.scalars(select(Engagement).join(EngagementTeam, EngagementTeam.engagement_id == Engagement.id).where(
        EngagementTeam.user_id == user.id, EngagementTeam.deleted_at.is_(None), Engagement.deleted_at.is_(None), Engagement.status.not_in(CLOSED)))
    for e in {e.id: e for e in rows}.values():
        org = db.get(Organization, e.client_id)
        out[f"engagement:{e.id}"] = {"key": f"engagement:{e.id}", "label": f"{org.name if org else ''} · {e.name}", "kind": "engagement", "billable_default": True}
    for b in db.scalars(select(HoursBank).where(HoursBank.deleted_at.is_(None))):
        if b.expires_on and b.expires_on < today():
            continue
        org = db.get(Organization, b.organization_id)
        out[f"bank:{b.id}"] = {"key": f"bank:{b.id}", "label": f"{org.name if org else ''} · {b.label}", "kind": "bank", "billable_default": True}
    for r in db.scalars(select(Retainer).where(Retainer.deleted_at.is_(None), Retainer.status != "ended")):
        org = db.get(Organization, r.organization_id)
        label = {"incident_response": "Incident retainer", "fractional_officer": "Fractional AI officer", "compliance": "Compliance retainer"}.get(r.type, r.type)
        out[f"retainer:{r.id}"] = {"key": f"retainer:{r.id}", "label": f"{org.name if org else ''} · {label}" + (" (activated)" if r.status == "activated" else ""),
                                   "kind": "retainer", "billable_default": True, "status": r.status}
    out["internal"] = {"key": "internal", "label": "Internal", "kind": "internal", "billable_default": False}
    return out


def _entries(db: Session, user_id: str, start: date) -> list[TimeEntry]:
    return list(db.scalars(select(TimeEntry).where(TimeEntry.user_id == user_id, TimeEntry.deleted_at.is_(None), TimeEntry.on_date >= start,
                                                   TimeEntry.on_date < start + timedelta(days=7)).order_by(TimeEntry.created_at)))


def _target_of(t: TimeEntry) -> str:
    if t.retainer_id:
        return f"retainer:{t.retainer_id}"
    if t.hours_bank_id:
        return f"bank:{t.hours_bank_id}"
    if t.engagement_id:
        return f"engagement:{t.engagement_id}"
    return "internal"


def _week_status(entries: list[TimeEntry]) -> str:
    st = {t.status for t in entries}
    for s in ("returned", "draft", "submitted", "approved"):
        if s in st:
            return s
    return "draft"


def week_view(db: Session, user: User, start: date) -> dict:
    start = week_start(start)
    entries = _entries(db, user.id, start)
    targets = _targets(db, user)
    rows: dict[tuple, dict] = {}
    for t in entries:
        key = (_target_of(t), t.activity, t.billable, t.note or "")
        r = rows.setdefault(key, {"target": key[0], "label": (targets.get(key[0]) or {}).get("label") or _label_for(db, key[0]), "activity": t.activity,
                                  "activity_label": ACTIVITY_LABELS.get(t.activity, t.activity), "billable": t.billable, "note": t.note, "hours": {}, "total": 0.0,
                                  "billable_label": _billable_label(db, key[0], t.billable)})
        r["hours"][t.on_date.isoformat()] = r["hours"].get(t.on_date.isoformat(), 0) + t.hours
        r["total"] += t.hours
    total = sum(t.hours for t in entries)
    return {"week_start": start.isoformat(), "days": [(start + timedelta(days=i)).isoformat() for i in range(7)], "rows": list(rows.values()),
            "total": total, "billable_total": sum(t.hours for t in entries if t.billable), "status": _week_status(entries) if entries else "draft",
            "targets": list(targets.values()), "activities": [{"code": a, "label": ACTIVITY_LABELS[a]} for a in ACTIVITIES]}


def _label_for(db: Session, key: str) -> str:
    kind, _, oid = key.partition(":")
    if kind == "engagement":
        e = db.get(Engagement, oid)
        return e.name if e else "Engagement"
    if kind == "bank":
        b = db.get(HoursBank, oid)
        return b.label if b else "Hours bank"
    if kind == "retainer":
        return "Retainer"
    return "Internal"


def _billable_label(db: Session, key: str, billable: bool) -> str:
    if not billable:
        return "No"
    kind, _, oid = key.partition(":")
    if kind == "bank":
        return "Yes (bank)"
    if kind == "retainer":
        r = db.get(Retainer, oid)
        return f"Yes (${r.hourly_rate:,.0f}/h)" if r and r.hourly_rate and r.status == "activated" else "Yes (retainer)"
    return "Yes"


def save_week(db: Session, user: User, start: date, rows: list[dict]) -> dict:
    start = week_start(start)
    existing = _entries(db, user.id, start)
    if any(t.status in ("submitted", "approved") for t in existing):
        raise Conflict("This week has been submitted. Ask your approver to return it to make changes.")
    targets = _targets(db, user)
    errors: list[dict] = []
    new: list[TimeEntry] = []
    per_day: dict[date, float] = {}
    for i, row in enumerate(rows):
        key = str(row.get("target") or "")
        activity = row.get("activity")
        billable = bool(row.get("billable"))
        note = " ".join(str(row.get("note") or "").split())[:500] or None
        if key not in targets:
            errors.append({"field": f"rows.{i}.target", "message": "Choose an engagement you are on, an hours bank, a retainer or internal work."})
            continue
        if activity not in ACTIVITIES:
            errors.append({"field": f"rows.{i}.activity", "message": "Choose an activity from the list."})
            continue
        kind, _, oid = key.partition(":")
        if kind == "internal" and billable:
            errors.append({"field": f"rows.{i}.billable", "message": "Internal time is not billable."})
            continue
        ret = db.get(Retainer, oid) if kind == "retainer" else None
        if ret is not None and ret.type == "incident_response" and ret.status != "activated":
            errors.append({"field": f"rows.{i}.target", "message": "Activate the incident retainer before logging incident hours."})
            continue
        for day, hours in (row.get("hours") or {}).items():
            try:
                d = date.fromisoformat(day)
                h = float(hours or 0)
            except (TypeError, ValueError):
                errors.append({"field": f"rows.{i}.hours", "message": "Enter hours as a number for a day of this week."})
                continue
            if not start <= d < start + timedelta(days=7) or not 0 <= h <= 24:
                errors.append({"field": f"rows.{i}.hours", "message": "Enter between 0 and 24 hours for a day of this week."})
                continue
            if h == 0:
                continue
            per_day[d] = per_day.get(d, 0) + h
            org_id = (db.get(Engagement, oid).client_id if kind == "engagement" else db.get(HoursBank, oid).organization_id if kind == "bank"
                      else ret.organization_id if ret else (futran_org(db).id if futran_org(db) else user.organization_id))
            new.append(TimeEntry(organization_id=org_id, user_id=user.id, engagement_id=oid if kind == "engagement" else (ret.incident_engagement_id if ret else None),
                                 hours_bank_id=oid if kind == "bank" else None, retainer_id=oid if kind == "retainer" else None, on_date=d, hours=h,
                                 activity=activity, billable=billable, note=note, status="draft", created_by=user.id))
    for d, h in per_day.items():
        if h > 24:
            errors.append({"field": "rows", "message": f"More than 24 hours on {d:%a %d %b}."})
    if errors:
        raise Invalid(errors=errors)
    for t in existing:
        t.deleted_at = utcnow()
    for t in new:
        db.add(t)
    db.flush()
    for bid in {t.hours_bank_id for t in new if t.hours_bank_id}:
        check_bank(db, db.get(HoursBank, bid))
    return week_view(db, user, start)


def _approvers_for(db: Session, t: TimeEntry) -> list[User]:
    if t.engagement_id and not t.retainer_id:
        from app.systems.service import engagement_managers

        e = db.get(Engagement, t.engagement_id)
        ems = engagement_managers(db, e) if e else []
        if ems:
            return ems
    return users_with_roles(db, ["chief_auditor"])


def submit_week(db: Session, user: User, start: date) -> dict:
    start = week_start(start)
    entries = [t for t in _entries(db, user.id, start) if t.status in ("draft", "returned")]
    if not entries:
        raise Conflict("There is no time to submit for this week.")
    approvers: dict[str, User] = {}
    for t in entries:
        t.status = "submitted"
        for u in _approvers_for(db, t):
            if u.id != user.id:
                approvers[u.id] = u
    db.flush()
    notify(db, approvers.values(), "timesheet_submitted", f"{user.name}: timesheet for the week of {start:%d %b} to approve", None, "/staff/time?tab=approvals")
    return week_view(db, user, start)


def _can_approve(db: Session, approver: User, t: TimeEntry, roles: set[str]) -> bool:
    if t.user_id == approver.id:
        return False
    if "chief_auditor" in roles:
        return True
    if t.engagement_id and not t.retainer_id:
        return db.scalar(select(EngagementTeam.id).where(EngagementTeam.engagement_id == t.engagement_id, EngagementTeam.user_id == approver.id,
                                                         EngagementTeam.role == "engagement_manager", EngagementTeam.deleted_at.is_(None))) is not None
    return False


def _roles(db: Session, user: User) -> set[str]:
    return set(db.scalars(select(RoleAssignment.role).where(RoleAssignment.user_id == user.id, RoleAssignment.deleted_at.is_(None))))


def approvals(db: Session, approver: User) -> list[dict]:
    roles = _roles(db, approver)
    weeks: dict[tuple[str, date], dict] = {}
    for t in db.scalars(select(TimeEntry).where(TimeEntry.status == "submitted", TimeEntry.deleted_at.is_(None)).order_by(TimeEntry.on_date)):
        if not _can_approve(db, approver, t, roles):
            continue
        k = (t.user_id, week_start(t.on_date))
        w = weeks.setdefault(k, {"user_id": t.user_id, "user_name": db.get(User, t.user_id).name, "week_start": k[1].isoformat(), "hours": 0.0, "billable": 0.0})
        w["hours"] += t.hours
        w["billable"] += t.hours if t.billable else 0
    return list(weeks.values())


def decide_week(db: Session, approver: User, user_id: str, start: date, approve: bool, note: str | None) -> int:
    start = week_start(start)
    roles = _roles(db, approver)
    if user_id == approver.id:
        raise Forbidden("Someone else approves your timesheet.")
    entries = [t for t in _entries(db, user_id, start) if t.status == "submitted" and _can_approve(db, approver, t, roles)]
    if not entries:
        raise Forbidden("There is nothing in this week for you to approve.")
    note = " ".join((note or "").split()) or None
    if not approve and not note:
        raise Invalid(errors=[{"field": "note", "message": "Say what needs changing."}])
    for t in entries:
        t.status = "approved" if approve else "returned"
        t.approved_by, t.approved_at = (approver.id, utcnow()) if approve else (None, None)
    db.flush()
    who = db.get(User, user_id)
    audit.record(db, actor_id=approver.id, action="timesheet.decided", organization_id=approver.organization_id, object_type="TimeEntry", object_id=entries[0].id,
                 summary=f"{'Approved' if approve else 'Returned'} {sum(t.hours for t in entries):g} h of {who.name}'s week of {start:%d %b %Y}" + (f": {note}" if note else ""))
    if not approve:
        notify(db, [who], "timesheet_returned", f"Your timesheet for the week of {start:%d %b} was returned", note, f"/staff/time?week={start.isoformat()}")
    return len(entries)


# ---------------------------------------------------------------- hours banks and retainers
def check_bank(db: Session, bank: HoursBank) -> bool:
    """Tell the account owner and the client's CAICO once when 80% of the bank is used."""
    if bank is None or bank.alerted_80_at is not None or not bank.hours_purchased:
        return False
    used = bank_used(db, bank)
    if used < 0.8 * bank.hours_purchased:
        return False
    from app.commercial.plans import _client_caicos, account_owner

    bank.alerted_80_at = utcnow()
    org = db.get(Organization, bank.organization_id)
    notify(db, [account_owner(db, org.id), *_client_caicos(db, org.id)], "hours_bank_80",
           f"{org.name}: {round(100 * used / bank.hours_purchased)}% of the {bank.hours_purchased:g} h {bank.label.lower()} used",
           "Hours beyond the bank are billed at the price list rate.", "/staff/time?tab=banks")
    return True


def run_bank_alerts(db: Session, settings, now) -> int:
    return sum(check_bank(db, b) for b in db.scalars(select(HoursBank).where(HoursBank.deleted_at.is_(None), HoursBank.alerted_80_at.is_(None))))


def banks_view(db: Session) -> dict:
    banks = []
    for b in db.scalars(select(HoursBank).where(HoursBank.deleted_at.is_(None)).order_by(HoursBank.created_at)):
        used = bank_used(db, b)
        org = db.get(Organization, b.organization_id)
        banks.append({"id": b.id, "client_id": org.id, "client_name": org.name, "code": b.code, "label": b.label, "purchased": b.hours_purchased, "used": used,
                      "remaining": max(0.0, b.hours_purchased - used), "pct": round(100 * used / b.hours_purchased) if b.hours_purchased else None,
                      "over": max(0.0, used - b.hours_purchased), "expires_on": b.expires_on.isoformat() if b.expires_on else None})
    month_start = today().replace(day=1)
    retainers = []
    for r in db.scalars(select(Retainer).where(Retainer.deleted_at.is_(None)).order_by(Retainer.created_at)):
        org = db.get(Organization, r.organization_id)
        month = float(db.scalar(select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(TimeEntry.retainer_id == r.id, TimeEntry.deleted_at.is_(None),
                                                                                         TimeEntry.on_date >= month_start)) or 0)
        billed = float(db.scalar(select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(TimeEntry.retainer_id == r.id, TimeEntry.deleted_at.is_(None),
                                                                                          TimeEntry.billable.is_(True))) or 0)
        retainers.append({"id": r.id, "client_id": org.id, "client_name": org.name, "code": r.code, "type": r.type, "status": r.status, "monthly_fee": r.monthly_fee,
                          "hourly_rate": r.hourly_rate, "monthly_hours": r.monthly_hours, "hours_this_month": month, "hours_billed": billed,
                          "activated_at": r.activated_at.isoformat() if r.activated_at else None, "incident_engagement_id": r.incident_engagement_id})
    return {"banks": banks, "retainers": retainers}


def activate_retainer(db: Session, actor: User, r: Retainer, reason: str) -> Retainer:
    """M-12b: open an incident engagement for the client and start billable time at the hourly rate. The engagement is
    dated before the client's other engagements, so the client's current audit stays the one every screen shows."""
    if r.type != "incident_response":
        raise Conflict("Only the incident response retainer is activated.")
    if r.status == "activated":
        raise Conflict("This retainer is already activated.")
    reason = " ".join((reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say what the incident is."}])
    from app.engagements.service import next_audit_ref

    org = db.get(Organization, r.organization_id)
    first = db.scalar(select(func.min(Engagement.created_at)).where(Engagement.client_id == org.id))
    now = utcnow()
    e = Engagement(organization_id=org.id, client_id=org.id, name=f"Incident response {now:%d %b %Y}", type="incident_response", audit_ref=next_audit_ref(db),
                   status="in_progress", stage=1, business_processes=reason[:2000], created_by=actor.id, updated_by=actor.id)
    db.add(e)
    db.flush()
    if first is not None:
        e.created_at = first - timedelta(seconds=1)
    db.add(EngagementTeam(organization_id=org.id, engagement_id=e.id, user_id=actor.id, role="engagement_manager", created_by=actor.id))
    rate = r.hourly_rate
    if rate is None:
        from app.commercial import catalog as cat

        item = cat.get_item(db, "M-12b")
        rate = item.list_price if item else None
    db.add(EngagementCommercial(organization_id=org.id, engagement_id=e.id, fee_total=0, milestones=[], created_by=actor.id))
    r.status, r.activated_at, r.activated_by, r.incident_engagement_id, r.hourly_rate = "activated", now, actor.id, e.id, rate
    db.flush()
    audit.record(db, actor_id=actor.id, action="retainer.activated", obj=r, summary=f"{org.name}: incident retainer activated ({reason}); engagement {e.audit_ref} opened")
    from app.commercial.plans import account_owner

    notify(db, [account_owner(db, org.id), *users_with_roles(db, ["admin"])], "retainer_activated", f"{org.name}: incident retainer activated",
           f"Billable at ${rate:,.0f} an hour." if rate else None, "/staff/time?tab=banks")
    return r


# ---------------------------------------------------------------- standard cost and margin
def standard_costs(db: Session) -> list[StandardCost]:
    return list(db.scalars(select(StandardCost).order_by(StandardCost.role, StandardCost.effective_from.desc())))


def set_standard_cost(db: Session, actor: User, role: str, cost: float, effective_from: date) -> StandardCost:
    from app.policy.roles import FUTRAN_ROLES

    if role not in {str(r) for r in FUTRAN_ROLES}:
        raise Invalid(errors=[{"field": "role", "message": "Choose a Futran role."}])
    if cost is None or cost < 0:
        raise Invalid(errors=[{"field": "cost_per_hour", "message": "Enter a cost per hour in dollars."}])
    row = StandardCost(role=role, cost_per_hour=money(cost), effective_from=effective_from, set_by=actor.id, set_at=utcnow())
    db.add(row)
    db.flush()
    audit.record(db, actor_id=actor.id, action="standard_cost.set", obj=row, organization_id=actor.organization_id,
                 summary=f"Standard cost for {role} set to ${row.cost_per_hour:,.2f}/h from {effective_from.isoformat()}")
    return row


def _cost_for(db: Session, role: str | None, on: date) -> float | None:
    if role is None:
        return None
    return db.scalar(select(StandardCost.cost_per_hour).where(StandardCost.role == role, StandardCost.effective_from <= on)
                     .order_by(StandardCost.effective_from.desc(), StandardCost.set_at.desc()).limit(1))


def _role_on(db: Session, t: TimeEntry) -> str | None:
    if t.engagement_id:
        role = db.scalar(select(EngagementTeam.role).where(EngagementTeam.engagement_id == t.engagement_id, EngagementTeam.user_id == t.user_id,
                                                          EngagementTeam.deleted_at.is_(None)).limit(1))
        if role:
            return role
    roles = sorted(_roles(db, db.get(User, t.user_id)))
    return roles[0] if roles else None


def margins(db: Session) -> dict:
    engs: dict[str, dict] = {}
    missing: set[str] = set()
    for t in db.scalars(select(TimeEntry).where(TimeEntry.deleted_at.is_(None), TimeEntry.engagement_id.is_not(None), TimeEntry.status != "returned")):
        row = engs.setdefault(t.engagement_id, {"hours": 0.0, "cost": 0.0, "costed": True, "billable_value": 0.0})
        row["hours"] += t.hours
        role = _role_on(db, t)
        c = _cost_for(db, role, t.on_date)
        if c is None:
            row["costed"] = False
            missing.add(role or "unknown")
        else:
            row["cost"] += c * t.hours
        if t.retainer_id and t.billable:
            r = db.get(Retainer, t.retainer_id)
            row["billable_value"] += t.hours * (r.hourly_rate or 0)
    for com in db.scalars(select(EngagementCommercial).where(EngagementCommercial.deleted_at.is_(None))):
        engs.setdefault(com.engagement_id, {"hours": 0.0, "cost": 0.0, "costed": True, "billable_value": 0.0})
    out = []
    for eid, row in engs.items():
        e = db.get(Engagement, eid)
        if e is None or e.deleted_at is not None:
            continue
        com = db.scalar(select(EngagementCommercial).where(EngagementCommercial.engagement_id == eid, EngagementCommercial.deleted_at.is_(None)))
        fee = (com.fee_total if com else 0) or row["billable_value"]
        org = db.get(Organization, e.client_id)
        cost = money(row["cost"]) if row["costed"] else None
        out.append({"engagement_id": eid, "label": f"{org.name if org else ''} · {e.name}", "fee": fee, "hours": row["hours"], "cost": cost,
                    "margin": money(fee - cost) if cost is not None and fee else None,
                    "margin_pct": round(100 * (fee - cost) / fee) if cost is not None and fee else None})
    return {"engagements": sorted(out, key=lambda r: r["label"]), "missing_costs": sorted(missing),
            "costs": [{"role": c.role, "cost_per_hour": c.cost_per_hour, "effective_from": c.effective_from.isoformat()} for c in standard_costs(db)]}
