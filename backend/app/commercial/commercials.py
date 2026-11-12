"""G-02: engagement commercials and change orders (spec B2).

Change orders: the auditor or Engagement Manager raises one from scope; it is priced from the price list (never a
price typed by someone who cannot see fees); a price off the list, a Proposed list price, or one outside Low–High goes
to a sales approver who is not the raiser; the client's CAICO approves in the platform; only then does the scope
change (an added system is created) and the order gets a line. An auditor's change order first waits for the
Engagement Manager. Adding a system after initiation (template §1.3) on an engagement that came from an order goes
through a change order; engagements without an order keep today's rule.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.commercial import catalog as cat
from app.commercial.common import money, users_with_roles
from app.commercial.handoff import code_base, default_milestones
from app.commercial.models import ChangeOrder, EngagementCommercial, Order, OrderLine
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid
from app.engagements.models import Engagement, EngagementTeam
from app.notifications.service import notify
from app.tenancy.models import Organization, RoleAssignment, User

KINDS = {"A-03": "add_system", "A-04": "add_jurisdiction", "L-08": "add_jurisdiction", "A-07": "extra_documents", "A-13": "extra_readout", "A-08": "extra_vendors"}
KIND_LABELS = {"add_system": "Add AI systems", "add_jurisdiction": "Add jurisdictions", "extra_documents": "Extra documents", "extra_readout": "Extra readout",
               "extra_vendors": "Extra vendors"}
STATUS_LABELS = {"draft": "Waiting for the Engagement Manager", "awaiting_futran_approval": "Waiting for sales approval", "awaiting_client": "Awaiting client approval",
                 "approved": "Approved", "rejected": "Rejected"}
TRIGGERS = {"sign_off_1": "Sign-off 1 approved", "sign_off_7": "Sign-off 7 approved", "manual": "Marked by hand"}


def commercial_of(db: Session, e: Engagement) -> EngagementCommercial | None:
    return db.scalar(select(EngagementCommercial).where(EngagementCommercial.engagement_id == e.id, EngagementCommercial.deleted_at.is_(None)))


def is_managed(db: Session, e: Engagement, user: User) -> bool:
    return db.scalar(select(EngagementTeam.id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.user_id == user.id, EngagementTeam.role == "engagement_manager",
                                                     EngagementTeam.deleted_at.is_(None))) is not None


def _roles(db: Session, user: User) -> set[str]:
    return set(db.scalars(select(RoleAssignment.role).where(RoleAssignment.user_id == user.id, RoleAssignment.deleted_at.is_(None))))


# ---------------------------------------------------------------- the commercial tab
def milestones_out(db: Session, e: Engagement, com: EngagementCommercial | None) -> list[dict]:
    from app.commercial.plans import _milestone_reached_on

    out = []
    for m in (com.milestones if com else None) or []:
        reached = _milestone_reached_on(db, e.id, m)
        out.append({"label": m.get("label"), "trigger": m.get("trigger"), "trigger_label": TRIGGERS.get(m.get("trigger"), m.get("trigger")), "pct": m.get("pct"),
                    "amount": m.get("amount"), "reached_on": reached.isoformat() if reached else None,
                    "status": f"On {reached:%B %Y} export" if reached else "Not reached"})
    return out


def commercial_view(db: Session, e: Engagement) -> dict:
    com = commercial_of(db, e)
    order = db.get(Order, com.order_id) if com and com.order_id else None
    lines = list(db.scalars(select(OrderLine).where(OrderLine.engagement_id == e.id, OrderLine.deleted_at.is_(None)).order_by(OrderLine.created_at)))
    org = db.get(Organization, e.client_id)
    return {
        "engagement": {"id": e.id, "name": e.name, "audit_ref": e.audit_ref, "client_id": e.client_id, "client_name": org.name if org else "", "status": e.status},
        "order": {"id": order.id, "ref": order.ref, "po_number": order.po_number} if order else None,
        "fee_total": com.fee_total if com else None, "has_commercials": com is not None,
        "order_lines": [{"id": ln.id, "code": ln.catalog_code, "description": ln.description, "qty": ln.qty, "unit_price": ln.unit_price, "value": ln.line_value,
                         "change_order_id": ln.change_order_id} for ln in lines],
        "milestones": milestones_out(db, e, com),
        "deliverables": [{"code": ln.catalog_code, "text": ln.deliverables_text} for ln in lines if ln.deliverables_text],
        "change_orders": [change_order_out(db, co, with_prices=True) for co in change_orders_for(db, e)],
        "kinds": [{"code": c, "label": f"{c} {KIND_LABELS[k]}"} for c, k in KINDS.items()],
    }


def update_commercial(db: Session, actor: User, e: Engagement, data: dict) -> EngagementCommercial:
    com = commercial_of(db, e)
    if com is None:
        com = EngagementCommercial(organization_id=e.client_id, engagement_id=e.id, fee_total=0, milestones=[], created_by=actor.id)
        db.add(com)
    errors = []
    fee = data.get("fee_total", com.fee_total)
    try:
        fee = money(fee)
        if fee < 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append({"field": "fee_total", "message": "Enter the fee in dollars."})
        fee = com.fee_total
    ms = data.get("milestones")
    if ms is not None:
        clean = []
        for i, m in enumerate(ms):
            label = " ".join(str(m.get("label") or "").split())[:120]
            trig = m.get("trigger") or "manual"
            try:
                pct = float(m.get("pct"))
            except (TypeError, ValueError):
                pct = -1
            if not label:
                errors.append({"field": f"milestones.{i}.label", "message": "Name the milestone."})
            if trig not in TRIGGERS:
                errors.append({"field": f"milestones.{i}.trigger", "message": "Choose what triggers it."})
            if not 0 < pct <= 100:
                errors.append({"field": f"milestones.{i}.pct", "message": "Enter a percentage between 1 and 100."})
            clean.append({"label": label, "trigger": trig, "pct": pct, "status": "not_reached", "reached_on": m.get("reached_on") if trig == "manual" else None})
        if clean and abs(sum(c["pct"] for c in clean) - 100) > 0.01:
            errors.append({"field": "milestones", "message": "The milestones must add up to 100%."})
    if errors:
        raise Invalid(errors=errors)
    before = {"fee_total": com.fee_total, "milestones": com.milestones}
    com.fee_total = fee
    if ms is not None:
        running = 0.0
        for i, c in enumerate(clean):
            c["amount"] = money(fee - running) if i == len(clean) - 1 else money(fee * c["pct"] / 100)
            running += c["amount"]
        com.milestones = clean
    elif com.milestones:
        pcts = [m.get("pct") or 0 for m in com.milestones]
        com.milestones = [m | {"amount": a["amount"]} for m, a in zip(com.milestones, _amounts(fee, pcts))]
    else:
        com.milestones = default_milestones(fee)
    com.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="engagement.commercial_updated", obj=com, engagement_id=e.id, before=before,
                 after={"fee_total": com.fee_total, "milestones": com.milestones}, summary=f"Fee and billing milestones updated for {e.audit_ref}")
    return com


def _amounts(fee: float, pcts: list[float]) -> list[dict]:
    out, running = [], 0.0
    for i, p in enumerate(pcts):
        a = money(fee - running) if i == len(pcts) - 1 else money(fee * p / 100)
        running += a
        out.append({"amount": a})
    return out


# ---------------------------------------------------------------- change orders
def change_orders_for(db: Session, e: Engagement) -> list[ChangeOrder]:
    return list(db.scalars(select(ChangeOrder).where(ChangeOrder.engagement_id == e.id, ChangeOrder.deleted_at.is_(None)).order_by(ChangeOrder.created_at)))


def change_order_out(db: Session, co: ChangeOrder, *, with_prices: bool) -> dict:
    name = lambda uid: (db.get(User, uid).name if uid and db.get(User, uid) else None)  # noqa: E731
    lines = [{k: v for k, v in ln.items() if with_prices or k in ("code", "description", "qty")} for ln in co.lines or []]
    out = {"id": co.id, "ref": co.ref, "engagement_id": co.engagement_id, "kind": co.kind, "kind_label": KIND_LABELS.get(co.kind or "", co.kind), "reason": co.reason,
           "lines": lines, "status": co.status, "status_label": STATUS_LABELS.get(co.status, co.status), "raised_by": name(co.raised_by),
           "raised_at": co.created_at.isoformat(), "em_approved_by": name(co.em_approved_by), "needs_price_approval": co.needs_price_approval,
           "futran_approved_by": name(co.futran_approved_by), "client_approved_by": name(co.client_approved_by),
           "approved_at": co.approved_at.isoformat() if co.approved_at else None, "decided_note": co.decided_note, "scope_change_ref": co.scope_change_ref,
           "applied": co.applied_at is not None}
    if with_prices:
        out["value"] = money(sum(ln.get("value") or 0 for ln in co.lines or []))
    return out


def _next_ref(db: Session, e: Engagement) -> str:
    n = len(list(db.scalars(select(ChangeOrder.id).where(ChangeOrder.engagement_id == e.id))))
    return f"CO-{n + 1:03d}"


def price_line(db: Session, code: str, qty: float, unit_price: float | None) -> tuple[dict, bool]:
    """Price a change-order line from the price list. Returns the line and whether a sales approver must agree."""
    base = code_base(code)
    if base not in KINDS:
        raise Invalid(errors=[{"field": "code", "message": "Change orders cover extra AI systems, jurisdictions, documents, readouts and vendors."}])
    item = cat.get_item(db, code)
    if item is None:
        raise Invalid(errors=[{"field": "code", "message": f"{code} is not in the price list."}])
    if item.sellable_status == "roadmap":
        raise Invalid(errors=[{"field": "code", "message": f"{code} is on the roadmap and cannot be sold yet."}])
    if not qty or qty <= 0:
        raise Invalid(errors=[{"field": "qty", "message": "Enter a quantity above zero."}])
    lst = item.list_price or 0
    unit = money(unit_price) if unit_price is not None else money(lst)
    needs = (unit != money(lst) or item.price_status == "proposed" or (item.low is not None and unit < item.low) or (item.high is not None and unit > item.high))
    return {"code": code, "description": item.name, "qty": qty, "unit_price": unit, "list_price": lst, "value": money(unit * qty)}, needs


def raise_change_order(db: Session, actor: User, e: Engagement, *, code: str, qty: float, reason: str, unit_price: float | None = None, can_price: bool = False,
                       scope_change_ref: str | None = None, raised_by: str | None = None, em_approved: bool | None = None) -> ChangeOrder:
    reason = " ".join((reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why the scope is growing."}])
    line, needs = price_line(db, code, qty, unit_price if can_price else None)
    if em_approved is None:
        em_approved = is_managed(db, e, actor) or bool(_roles(db, actor) & {"chief_auditor", "sales_manager", "sales_team", "pricing_approver"})
    co = ChangeOrder(organization_id=e.client_id, engagement_id=e.id, ref=_next_ref(db, e), reason=reason[:2000], lines=[line], raised_by=raised_by or actor.id,
                     kind=KINDS[code_base(code)], status="draft", needs_price_approval=needs, scope_change_ref=scope_change_ref, created_by=actor.id)
    db.add(co)
    db.flush()
    audit.record(db, actor_id=actor.id, action="change_order.raised", obj=co, engagement_id=e.id, after={"lines": co.lines, "reason": co.reason},
                 summary=f"{co.ref} raised on {e.audit_ref}: {line['qty']:g} × {code}")
    if em_approved:
        _after_manager(db, actor, e, co)
    else:
        from app.systems.service import engagement_managers

        notify(db, engagement_managers(db, e), "change_order_manager", f"{e.audit_ref}: approve change order {co.ref}", co.reason, f"/e/{e.id}/commercial", engagement=e)
    return co


def _after_manager(db: Session, actor: User, e: Engagement, co: ChangeOrder) -> None:
    co.em_approved_by, co.em_approved_at = actor.id, utcnow()
    if co.needs_price_approval:
        co.status = "awaiting_futran_approval"
        notify(db, users_with_roles(db, ["sales_manager", "pricing_approver"]), "change_order_price", f"{e.audit_ref}: price on change order {co.ref} needs approval",
               co.reason, f"/e/{e.id}/commercial")
    else:
        _send_to_client(db, e, co)
    db.flush()


def _client_caicos(db: Session, client_id: str) -> list[User]:
    return list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(
        User.organization_id == client_id, RoleAssignment.role == "caico", RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None))))


def _send_to_client(db: Session, e: Engagement, co: ChangeOrder) -> None:
    co.status = "awaiting_client"
    notify(db, _client_caicos(db, e.client_id), "change_order_client", f"Change order {co.ref} needs your approval", co.reason, "/change-orders", engagement=e)


def manager_approve(db: Session, actor: User, co: ChangeOrder) -> ChangeOrder:
    e = db.get(Engagement, co.engagement_id)
    if co.status != "draft":
        raise Conflict("This change order is no longer waiting for the Engagement Manager.")
    if not (is_managed(db, e, actor) or "chief_auditor" in _roles(db, actor)):
        raise Forbidden("The Engagement Manager approves change orders raised by the audit team.")
    if actor.id == co.raised_by:
        raise Forbidden("Someone other than the person who raised it approves the change order.")
    _after_manager(db, actor, e, co)
    audit.record(db, actor_id=actor.id, action="change_order.manager_approved", obj=co, engagement_id=e.id, summary=f"{co.ref} approved by the Engagement Manager")
    return co


def price_decision(db: Session, actor: User, co: ChangeOrder, approve: bool, note: str | None) -> ChangeOrder:
    e = db.get(Engagement, co.engagement_id)
    if co.status != "awaiting_futran_approval":
        raise Conflict("This change order is not waiting for a price approval.")
    if actor.id in (co.raised_by, co.created_by):
        raise Forbidden("Nobody approves the price on their own change order.")
    note = " ".join((note or "").split()) or None
    if not approve and not note:
        raise Invalid(errors=[{"field": "note", "message": "Say why the price is returned."}])
    co.futran_approved_by, co.futran_approved_at, co.decided_note = actor.id, utcnow(), note
    if approve:
        _send_to_client(db, e, co)
    else:
        co.status = "rejected"
        _release_scope(db, co, approved=False, note=note)
    db.flush()
    audit.record(db, actor_id=actor.id, action="change_order.price_decided", obj=co, engagement_id=e.id, summary=f"{co.ref} price {'approved' if approve else 'returned'}")
    return co


def client_decision(db: Session, settings, actor: User, co: ChangeOrder, approve: bool, note: str | None) -> ChangeOrder:
    e = db.get(Engagement, co.engagement_id)
    if co.status != "awaiting_client":
        raise Conflict("This change order is not waiting for your approval.")
    note = " ".join((note or "").split()) or None
    if not approve and not note:
        raise Invalid(errors=[{"field": "note", "message": "Say why you are not approving it."}])
    co.client_approved_by, co.approved_at, co.decided_note = actor.id, utcnow(), note
    co.status = "approved" if approve else "rejected"
    if approve:
        _apply(db, settings, actor, e, co)
    else:
        _release_scope(db, co, approved=False, note=note)
    db.flush()
    audit.record(db, actor_id=actor.id, action="change_order.client_decided", obj=co, engagement_id=e.id,
                 summary=f"{co.ref} {'approved' if approve else 'rejected'} by the client" + (f": {note}" if note else ""))
    from app.systems.service import engagement_managers

    who = {u.id: u for u in [*engagement_managers(db, e), db.get(User, co.raised_by)] if u}
    notify(db, who.values(), "change_order_decided", f"{e.audit_ref}: change order {co.ref} {'approved' if approve else 'rejected'} by the client", note,
           f"/e/{e.id}/commercial", engagement=e)
    return co


def _apply(db: Session, settings, actor: User, e: Engagement, co: ChangeOrder) -> None:
    """The scope changes only now: the order gets the line, the fee grows, and an added system is created."""
    com = commercial_of(db, e)
    for ln in co.lines or []:
        db.add(OrderLine(organization_id=e.client_id, order_id=com.order_id if com and com.order_id else _order_for(db, e).id, catalog_code=ln["code"],
                         description=f"{co.ref}: {ln.get('description') or ln['code']}"[:300], qty=ln["qty"], unit_price=ln["unit_price"], line_value=ln["value"],
                         recurring=False, start_on=utcnow().date(), engagement_id=e.id, change_order_id=co.id, created_by=actor.id))
    if com is not None:
        com.fee_total = money(com.fee_total + sum(ln["value"] for ln in co.lines or []))
    _release_scope(db, co, approved=True, note=None, actor=actor)
    co.applied_at = utcnow()


def _order_for(db: Session, e: Engagement) -> Order:
    from app.commercial.handoff import next_order_ref

    o = Order(organization_id=e.client_id, ref=next_order_ref(db), status="active")
    db.add(o)
    db.flush()
    return o


def _release_scope(db: Session, co: ChangeOrder, *, approved: bool, note: str | None, actor: User | None = None) -> None:
    ref = co.scope_change_ref or ""
    if not ref.startswith("system_addition:"):
        if approved:
            e = db.get(Engagement, co.engagement_id)
            from app.systems.service import engagement_managers

            notify(db, engagement_managers(db, e), "change_order_apply", f"{e.audit_ref}: {co.ref} approved — apply the scope change", co.reason, f"/e/{e.id}/commercial",
                   engagement=e)
        return
    from app.systems.models import SystemAdditionRequest
    from app.systems.service import create_system

    req = db.get(SystemAdditionRequest, ref.split(":", 1)[1])
    if req is None or req.status != "co_pending":
        return
    e = db.get(Engagement, req.engagement_id)
    if approved:
        s = create_system(db, db.get(User, co.em_approved_by) or actor, e, dict(req.payload), created_by=req.requested_by)
        req.system_id, req.status = s.id, "approved"
    else:
        req.status, req.decision_comment = "rejected", note
    req.decided_at = utcnow()


def intercept_addition(db: Session, actor: User, req, e: Engagement) -> bool:
    """Hook for the add-system-after-initiation rule: on an engagement that came from an order, the Engagement Manager's
    approval raises an A-03 change order instead of adding the system. Returns False to keep today's rule (no order on
    this engagement, or A-03 not in the price list)."""
    if commercial_of(db, e) is None or cat.get_item(db, "A-03") is None:
        return False
    co = raise_change_order(db, actor, e, code="A-03", qty=1, reason=req.reason or "System added after initiation", scope_change_ref=f"system_addition:{req.id}",
                            raised_by=req.requested_by, em_approved=True)
    req.status, req.decided_by, req.decided_at = "co_pending", actor.id, utcnow()
    req.decision_comment = f"Sent to the client as change order {co.ref}"
    return True
