"""R8: asking for the tracing add-on, the Executive Sponsor's decision, and cancellation (spec §27.3, §27.5).

On a request the sponsor gets an approval task (in the app and by email) and Futran Sales and the Chief Auditor get an
`Opportunity` through app.sales.service.open_from_trigger, which applies WS-D's rules (one per trigger, Chief Auditor
approval for current audit clients, the independence rule). The sponsor's approval activates the subscription and unlocks
the Tracing tab on the systems it covers. Buying the add-on never touches audit records.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.notifications.service import notify
from app.register.models import RegisterSystem
from app.tenancy.models import Department, Organization, RoleAssignment, User
from app.tracing.access import covers, state_for, subscriptions
from app.tracing.models import PLANS, AddonSubscription

PLAN_LABELS = {"per_system": "Per system", "tier_2_3": "All Tier 2 and 3 systems", "enterprise": "Enterprise"}
PLAN_HINTS = {"per_system": "Priced per system per month; only the systems you tick.", "tier_2_3": "Every Tier 2 and Tier 3 system, including ones added later.",
              "enterprise": "Every system, with GuardRail and AgentAssure. Futran agrees the terms with you."}
STATUS_LABELS = {"requested": "Waiting for approval", "approved": "Approved", "active": "Active", "declined": "Declined", "cancelled": "Cancelled"}
TRIAL_DAYS = 30
TIER_LABELS = {1: "Tier 1", 2: "Tier 2", 3: "Tier 3"}


def _users_with_role(db: Session, org_id: str, role: str) -> list[User]:
    return list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(
        User.organization_id == org_id, RoleAssignment.role == role, RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None), User.status != "disabled").order_by(User.name).distinct()))


def sponsors(db: Session, org_id: str) -> list[User]:
    return _users_with_role(db, org_id, "exec_sponsor")


def futran_sales_and_chiefs(db: Session) -> list[User]:
    futran = [o.id for o in db.scalars(select(Organization).where(Organization.type == "futran"))]
    out: dict[str, User] = {}
    for org_id in futran:
        for role in ("sales_team", "chief_auditor"):
            for u in _users_with_role(db, org_id, role):
                out[u.id] = u
    return list(out.values())


def systems(db: Session, org_id: str) -> list[RegisterSystem]:
    return list(db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None), RegisterSystem.stage != "retired").order_by(RegisterSystem.name)))


def system_row(db: Session, s: RegisterSystem, subs: list[AddonSubscription]) -> dict:
    from app.register.history import tracing_reasons
    from app.register.service import STAGE_LABELS, TYPE_LABELS

    reasons = tracing_reasons(db, s)
    state, _ = state_for(db, s, subs)
    dept = db.get(Department, s.department_id) if s.department_id else None
    return {"id": s.id, "reference": s.reference, "name": s.name, "department": dept.name if dept else ("Company-wide" if s.company_wide else None), "tier": s.risk_tier,
            "tier_label": TIER_LABELS.get(s.risk_tier or 0), "type": s.type, "type_label": TYPE_LABELS.get(s.type, s.type), "stage": s.stage, "stage_label": STAGE_LABELS.get(s.stage, s.stage),
            "recommended": bool(reasons), "reasons": reasons, "status": state}


def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def request_out(db: Session, sub: AddonSubscription) -> dict:
    names = [s.name for s in (db.get(RegisterSystem, i) for i in sub.ai_system_ids or []) if s is not None]
    return {"id": sub.id, "addon": sub.addon, "plan": sub.plan, "plan_label": PLAN_LABELS[sub.plan], "systems": names, "system_ids": list(sub.ai_system_ids or []),
            "trial": sub.trial, "trial_ends_on": sub.trial_ends_on.isoformat() if sub.trial_ends_on else None, "status": sub.status, "status_label": STATUS_LABELS[sub.status],
            "note": sub.note, "requested_by": _name(db, sub.requested_by), "requested_by_id": sub.requested_by, "requested_at": sub.requested_at.isoformat(),
            "approver": _name(db, sub.approver_id), "approver_id": sub.approver_id, "approved_by": _name(db, sub.approved_by), "decided_at": sub.decided_at.isoformat() if sub.decided_at else None,
            "decision_comment": sub.decision_comment, "cancelled_at": sub.cancelled_at.isoformat() if sub.cancelled_at else None, "cancel_reason": sub.cancel_reason}


def page(db: Session, org_id: str, *, can_request: bool, can_approve: bool) -> dict:
    subs = subscriptions(db, org_id)
    every = list(db.scalars(select(AddonSubscription).where(AddonSubscription.organization_id == org_id, AddonSubscription.deleted_at.is_(None)).order_by(AddonSubscription.requested_at.desc())))
    rows = [system_row(db, s, subs) for s in systems(db, org_id)]
    return {
        "systems": rows,
        "plans": [{"value": p, "label": PLAN_LABELS[p], "hint": PLAN_HINTS[p], "count": _plan_count(p, rows)} for p in PLANS],
        "sponsors": [{"id": u.id, "name": u.name, "job_title": u.job_title} for u in sponsors(db, org_id)],
        "requests": [request_out(db, x) for x in every],
        "trial_days": TRIAL_DAYS, "can_request": can_request, "can_approve": can_approve,
    }


def _plan_count(plan: str, rows: list[dict]) -> int | None:
    if plan == "tier_2_3":
        return sum(1 for r in rows if r["tier"] in (2, 3))
    if plan == "enterprise":
        return len(rows)
    return None


def request(db: Session, settings, actor, data: dict) -> AddonSubscription:
    org_id = actor.organization.id
    errs: list[dict] = []
    ids = data.get("system_ids") or []
    chosen: list[RegisterSystem] = []
    if not isinstance(ids, list) or not ids:
        errs.append({"field": "system_ids", "message": "Choose at least one AI system."})
    else:
        for i in dict.fromkeys(ids):
            s = db.get(RegisterSystem, i) if isinstance(i, str) else None
            if s is None or s.organization_id != org_id or s.deleted_at is not None:
                errs.append({"field": "system_ids", "message": "One of the chosen systems is not in your register."})
                break
            chosen.append(s)
    plan = data.get("plan")
    if plan not in PLANS:
        errs.append({"field": "plan", "message": "Choose a plan."})
    approver = db.get(User, data.get("approver_id")) if isinstance(data.get("approver_id"), str) else None
    if approver is None or approver.id not in {u.id for u in sponsors(db, org_id)}:
        errs.append({"field": "approver_id", "message": "Choose your Executive Sponsor. If there is none with a login, ask your Client Admin to add one."})
    if errs:
        raise Invalid(errors=errs)
    subs = subscriptions(db, org_id)
    taken = [s.name for s in chosen if state_for(db, s, subs)[0] != "locked"]
    if taken:
        raise Conflict(f"Already active or waiting for approval: {', '.join(taken)}.")
    note = (data.get("note") or "").strip()[:2000] or None
    sub = AddonSubscription(organization_id=org_id, addon="tracing", ai_system_ids=[s.id for s in chosen], plan=plan, trial=bool(data.get("trial")), note=note,
                            requested_by=actor.id, requested_at=utcnow(), approver_id=approver.id, status="requested", created_by=actor.id)
    db.add(sub)
    db.flush()
    audit.record(db, actor_id=actor.id, action="addon.requested", obj=sub, organization_id=org_id,
                 summary=f"Asked for the tracing add-on on {len(chosen)} system{'s' if len(chosen) != 1 else ''} ({PLAN_LABELS[plan]}{', 30-day trial' if sub.trial else ''})")
    n = len(chosen)
    what = f"{n} system{'s' if n != 1 else ''}"
    notify(db, [approver], "addon_approval", f"Approve the tracing add-on for {what}",
           f"{actor.user.name} asks you to approve the tracing and incident module ({PLAN_LABELS[plan]}{', 30-day free trial' if sub.trial else ''}) for: {', '.join(s.name for s in chosen)}."
           + (f" Note: {note}" if note else ""), "/addons", settings=settings, email_template="notification")
    _open_opportunity(db, settings, sub, chosen, actor)
    return sub


def _open_opportunity(db: Session, settings, sub: AddonSubscription, chosen: list[RegisterSystem], actor) -> None:
    from app.sales.service import IndependenceError, open_from_trigger

    org = db.get(Organization, sub.organization_id)
    try:
        opp = open_from_trigger(db, sub.organization_id, "unlock_request", sub.id, service=f"Tracing add-on: {PLAN_LABELS[sub.plan]}", service_kind="addon",
                                why_now=f"{org.name} asked to unlock tracing on {len(chosen)} system{'s' if len(chosen) != 1 else ''}; waiting for their Executive Sponsor"
                                + (" (30-day trial requested)" if sub.trial else ""),
                                system_ids=[s.id for s in chosen], addon_status="requested", created_by=actor.id)
    except IndependenceError:  # the rule is WS-D's; a refused opportunity never blocks the client's own request
        audit.record(db, actor_id=None, actor_name="System", action="addon.opportunity_refused", obj=sub, organization_id=sub.organization_id,
                     summary="No opportunity opened: the independence rule applies to this client")
        return
    sub.opportunity_id = opp.id
    notify(db, futran_sales_and_chiefs(db), "addon_opportunity", f"{org.name} asked to unlock the tracing add-on",
           f"{len(chosen)} system{'s' if len(chosen) != 1 else ''} ({', '.join(sorted({s.type.replace('_', ' ') for s in chosen}))}). Waiting for the client's Executive Sponsor.",
           "/opportunities", settings=settings)


def _load(db: Session, actor, sub_id: str) -> AddonSubscription:
    sub = db.get(AddonSubscription, sub_id)
    if sub is None or sub.deleted_at is not None or sub.organization_id != actor.organization.id:
        raise NotFound()
    return sub


def decide(db: Session, settings, actor, sub_id: str, approve: bool, comment: str | None) -> AddonSubscription:
    sub = _load(db, actor, sub_id)
    if sub.status != "requested":
        raise Conflict("This request has already been decided.")
    if sub.requested_by == actor.id:
        raise Forbidden("You asked for this add-on, so another Executive Sponsor must approve it.")
    comment = (comment or "").strip() or None
    if not approve and not comment:
        raise Invalid(errors=[{"field": "comment", "message": "Say why you are declining. It is sent to the person who asked."}])
    now = utcnow()
    sub.decided_at, sub.decision_comment, sub.updated_by = now, comment, actor.id
    if approve:
        sub.status, sub.approved_by, sub.activated_at = "active", actor.id, now
        if sub.trial:
            sub.trial_ends_on = today() + timedelta(days=TRIAL_DAYS)
    else:
        sub.status = "declined"
    db.flush()
    audit.record(db, actor_id=actor.id, action="addon.approved" if approve else "addon.declined", obj=sub, organization_id=sub.organization_id,
                 summary=f"{'Approved' if approve else 'Declined'} the tracing add-on ({PLAN_LABELS[sub.plan]})" + (f": {comment}" if comment else ""))
    asker = db.get(User, sub.requested_by) if sub.requested_by else None
    title = f"The tracing add-on was {'approved' if approve else 'declined'} by {actor.user.name}"
    body = ("The Tracing tab is now open on the systems it covers." + (f" Free trial until {sub.trial_ends_on.day} {sub.trial_ends_on:%B %Y}." if sub.trial_ends_on else "")) if approve else f"Reason: {comment}"
    notify(db, [asker], "addon_decided", title, body, "/addons", settings=settings, email_template="notification")
    _log_on_opportunity(db, sub, "approved_by_client" if approve else "declined_by_client",
                        f"The client's Executive Sponsor {'approved' if approve else 'declined'} the add-on" + (f": {comment}" if comment else "."), actor.id)
    return sub


def cancel(db: Session, settings, actor, sub_id: str, reason: str | None) -> AddonSubscription:
    sub = _load(db, actor, sub_id)
    if sub.status not in ("requested", "active"):
        raise Conflict("Only a waiting or active add-on can be cancelled.")
    reason = (reason or "").strip()
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why the add-on is being cancelled."}])
    sub.status, sub.cancelled_by, sub.cancelled_at, sub.cancel_reason, sub.updated_by = "cancelled", actor.id, utcnow(), reason, actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="addon.cancelled", obj=sub, organization_id=sub.organization_id, summary=f"Cancelled the tracing add-on: {reason}")
    _log_on_opportunity(db, sub, "cancelled_by_client", f"The client cancelled the add-on: {reason}", actor.id)
    return sub


def _log_on_opportunity(db: Session, sub: AddonSubscription, kind: str, summary: str, by_id: str) -> None:
    if not sub.opportunity_id:
        return
    from app.sales.models import Opportunity
    from app.sales.service import log

    o = db.get(Opportunity, sub.opportunity_id)
    if o is not None:
        log(db, o, kind, summary, by_id)


def covered_ids(db: Session, org_id: str) -> set[str]:
    subs = subscriptions(db, org_id, statuses=("active", "requested"))
    return {s.id for s in systems(db, org_id) if any(covers(x, s) for x in subs)}
