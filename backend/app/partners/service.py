"""G-11 partners and referrals (spec B11).

Functions other workstreams call:
- `commission_for_win(db, opportunity, order, first_year_value) -> Commission | None` — R5's hand-off (SM-13) calls this
  when a proposal is accepted. The partner is `opportunity.partner_id` (R2's column) or, until that is set, the partner of
  an inbound referral recorded against the opportunity. Law-firm partners never get a commission (bar rules), whatever
  their row says. Idempotent: a retried hand-off returns the existing commission.
- `commissions_due(db, start, end, client_id) -> list[dict]` — R5's monthly billing export: commissions due (or paid) in
  the period, each {id, organization_id, amount, order_ref, partner_name, status}.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.partners.models import PARTNER_TYPES, TYPE_LABELS, Commission, Partner, Referral
from app.tenancy.models import Organization, User

PAYMENT_DAYS = 30  # a commission falls due 30 days after the order starts (or the win, without a start date)
LAW_FIRM_NOTE = "None: referrals both ways, no fees (bar rules)"


def _money(v) -> float:
    return round(float(v or 0), 2)


def _futran(db: Session) -> Organization:
    from app.commercial.common import futran_org

    f = futran_org(db)
    if f is None:
        raise Conflict("Futran's organization is not set up.")
    return f


def commission_label(p: Partner) -> str:
    if p.type == "law_firm":
        return LAW_FIRM_NOTE
    rate = (p.commission_rule or {}).get("rate_pct")
    return f"{rate:g}% of first-year contract value" if rate else "No commission"


def _rule(ptype: str, rate_pct) -> dict | None:
    if rate_pct in (None, ""):
        return None
    if ptype == "law_firm":
        raise Invalid(errors=[{"field": "rate_pct", "message": "Law firms cannot be paid referral fees (bar rules). Referrals go both ways without fees."}])
    try:
        r = float(rate_pct)
    except (TypeError, ValueError) as exc:
        raise Invalid(errors=[{"field": "rate_pct", "message": "Enter the commission as a percentage."}]) from exc
    if not 0 < r <= 50:
        raise Invalid(errors=[{"field": "rate_pct", "message": "Enter a percentage between 0 and 50."}])
    return {"rate_pct": r, "basis": "first_year_value"}


# ---------------------------------------------------------------- partners
def create_partner(db: Session, actor: User, data: dict) -> Partner:
    ptype = data.get("type")
    if ptype not in PARTNER_TYPES:
        raise Invalid(errors=[{"field": "type", "message": "Choose the partner type."}])
    name = " ".join(str(data.get("name") or "").split())
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Enter the partner's name."}])
    p = Partner(organization_id=_futran(db).id, name=name[:200], type=ptype, commission_rule=_rule(ptype, data.get("rate_pct")), status="active", created_by=actor.id)
    _apply(p, data)
    db.add(p)
    db.flush()
    audit.record(db, actor_id=actor.id, action="partner.create", obj=p, after={"name": p.name, "type": p.type, "commission": commission_label(p)}, summary=f"Added partner {p.name}")
    return p


def _apply(p: Partner, data: dict) -> None:
    for k in ("agreement_label", "contact_name", "contact_email", "contact_phone", "notes"):
        if k in data:
            v = " ".join(str(data.get(k) or "").split()) if k != "notes" else str(data.get(k) or "").strip()
            setattr(p, k, v or None)
    if "status" in data and data["status"] in ("active", "inactive"):
        p.status = data["status"]


def update_partner(db: Session, actor: User, p: Partner, data: dict) -> Partner:
    before = {"name": p.name, "type": p.type, "commission": commission_label(p), "status": p.status}
    if "type" in data:
        if data["type"] not in PARTNER_TYPES:
            raise Invalid(errors=[{"field": "type", "message": "Choose the partner type."}])
        p.type = data["type"]
    if "name" in data:
        name = " ".join(str(data.get("name") or "").split())
        if not name:
            raise Invalid(errors=[{"field": "name", "message": "Enter the partner's name."}])
        p.name = name[:200]
    if "rate_pct" in data:
        p.commission_rule = _rule(p.type, data["rate_pct"])
    if p.type == "law_firm":
        p.commission_rule = None
    _apply(p, data)
    p.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="partner.edit", obj=p, before=before, after={"name": p.name, "type": p.type, "commission": commission_label(p), "status": p.status},
                 summary=f"Edited partner {p.name}")
    return p


def get_partner(db: Session, partner_id: str) -> Partner:
    p = db.get(Partner, partner_id)
    if p is None or p.deleted_at is not None:
        raise NotFound()
    return p


# ---------------------------------------------------------------- referrals
def record_referral(db: Session, actor: User, p: Partner, *, direction: str, organization_id: str | None = None, opportunity_id: str | None = None,
                    note: str | None = None) -> Referral:
    from app.sales.models import Opportunity

    if direction not in ("in", "out"):
        raise Invalid(errors=[{"field": "direction", "message": "Choose referred in or referred out."}])
    if opportunity_id:
        opp = db.get(Opportunity, opportunity_id)
        if opp is None:
            raise Invalid(errors=[{"field": "opportunity_id", "message": "Choose an opportunity."}])
        organization_id = opp.organization_id
    if organization_id:
        org = db.get(Organization, organization_id)
        if org is None or org.deleted_at is not None or org.type != "client":
            raise Invalid(errors=[{"field": "organization_id", "message": "Choose a client."}])
    else:
        organization_id = _futran(db).id
    r = Referral(organization_id=organization_id, partner_id=p.id, direction=direction, opportunity_id=opportunity_id, note=(str(note or "").strip()[:2000] or None),
                 at=utcnow(), recorded_by=actor.id, created_by=actor.id)
    db.add(r)
    db.flush()
    audit.record(db, actor_id=actor.id, action="partner.referral", obj=r, after={"partner": p.name, "direction": direction, "opportunity_id": opportunity_id},
                 summary=f"Referral {'from' if direction == 'in' else 'to'} {p.name}" + (f": {r.note[:120]}" if r.note else ""))
    return r


def _partner_of(db: Session, opportunity) -> Partner | None:
    pid = getattr(opportunity, "partner_id", None)
    if not pid:
        pid = db.scalar(select(Referral.partner_id).where(Referral.opportunity_id == opportunity.id, Referral.direction == "in", Referral.deleted_at.is_(None))
                        .order_by(Referral.at).limit(1))
    if not pid:
        return None
    p = db.get(Partner, pid)
    return p if p is not None and p.deleted_at is None else None


# ---------------------------------------------------------------- commissions
def commission_for_win(db: Session, opportunity, order, first_year_value) -> Commission | None:
    """The partner commission for a won opportunity, from the accepted proposal's first-year value. None when there is no
    partner, the partner is a law firm, or the partner has no commission rule."""
    p = _partner_of(db, opportunity)
    if p is None or p.type == "law_firm":
        return None
    rate = (p.commission_rule or {}).get("rate_pct")
    if not rate:
        return None
    existing = db.scalar(select(Commission).where(Commission.opportunity_id == opportunity.id, Commission.status != "void", Commission.deleted_at.is_(None)).limit(1))
    if existing is not None:
        return existing
    base = _money(first_year_value)
    start = getattr(order, "start_on", None) or today()
    org_id = getattr(order, "organization_id", None) or opportunity.organization_id
    c = Commission(organization_id=org_id, partner_id=p.id, opportunity_id=opportunity.id, order_id=getattr(order, "id", None), order_ref=getattr(order, "ref", None),
                   base_value=base, rate=float(rate), amount=_money(base * float(rate) / 100), status="due", due_on=start + timedelta(days=PAYMENT_DAYS))
    db.add(c)
    db.flush()
    audit.record(db, actor_id=None, action="partner.commission_created", obj=c, after={"partner": p.name, "base_value": base, "rate": c.rate, "amount": c.amount},
                 summary=f"Commission for {p.name}: {c.rate:g}% of ${base:,.2f} first-year value, due {c.due_on.isoformat()}")
    return c


def commissions_due(db: Session, start: date, end: date, client_id: str | None) -> list[dict]:
    q = select(Commission, Partner).join(Partner, Partner.id == Commission.partner_id).where(
        Commission.deleted_at.is_(None), Commission.status.in_(["due", "paid"]), Commission.due_on >= start, Commission.due_on <= end)
    if client_id:
        q = q.where(Commission.organization_id == client_id)
    return [{"id": c.id, "organization_id": c.organization_id, "amount": c.amount, "order_ref": c.order_ref, "partner_name": p.name, "status": c.status}
            for c, p in db.execute(q.order_by(Commission.due_on))]


def mark_paid(db: Session, actor: User, c: Commission) -> Commission:
    if c.status != "due":
        raise Conflict("Only a commission that is due can be marked paid.")
    c.status, c.paid_on, c.settled_by, c.updated_by = "paid", today(), actor.id, actor.id
    audit.record(db, actor_id=actor.id, action="partner.commission_paid", obj=c, after={"amount": c.amount}, summary=f"Commission of ${c.amount:,.2f} marked paid")
    return c


def void(db: Session, actor: User, c: Commission, reason: str) -> Commission:
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why the commission is void."}])
    if c.status != "due":
        raise Conflict("Only a commission that is due can be made void.")
    c.status, c.void_reason, c.settled_by, c.updated_by = "void", reason[:300], actor.id, actor.id
    audit.record(db, actor_id=actor.id, action="partner.commission_void", obj=c, after={"reason": c.void_reason}, summary=f"Commission of ${c.amount:,.2f} made void: {reason[:120]}")
    return c


# ---------------------------------------------------------------- the G-11 screen
def _opps_for(db: Session, p: Partner) -> set[str]:
    from app.sales.models import Opportunity

    ids = set(db.scalars(select(Referral.opportunity_id).where(Referral.partner_id == p.id, Referral.direction == "in", Referral.opportunity_id.is_not(None),
                                                               Referral.deleted_at.is_(None))))
    if hasattr(Opportunity, "partner_id"):
        ids |= set(db.scalars(select(Opportunity.id).where(Opportunity.partner_id == p.id)))
    return ids


def _won_value(db: Session, opp_ids: set[str]) -> float:
    from app.sales.models import Opportunity

    total = 0.0
    for o in db.scalars(select(Opportunity).where(Opportunity.id.in_(list(opp_ids)), Opportunity.stage == "won")) if opp_ids else []:
        y1 = None
        try:
            from app.commercial.models import Order, OrderLine

            lines = db.execute(select(OrderLine.line_value).join(Order, Order.id == OrderLine.order_id).where(Order.opportunity_id == o.id, OrderLine.deleted_at.is_(None))).scalars().all()
            y1 = sum(lines) if lines else None
        except ImportError:
            pass
        total += float(y1 if y1 is not None else (o.value or 0))
    return _money(total)


def partner_out(db: Session, p: Partner, *, money: bool) -> dict:
    opp_ids = _opps_for(db, p)
    refs = list(db.scalars(select(Referral).where(Referral.partner_id == p.id, Referral.deleted_at.is_(None))))
    due = [c.amount for c in db.scalars(select(Commission).where(Commission.partner_id == p.id, Commission.status == "due", Commission.deleted_at.is_(None)))]
    return {
        "id": p.id, "name": p.name, "type": p.type, "type_label": TYPE_LABELS.get(p.type, p.type), "status": p.status, "agreement_label": p.agreement_label,
        "agreement_file_id": p.agreement_file_id if money else None, "contact_name": p.contact_name, "contact_email": p.contact_email, "contact_phone": p.contact_phone,
        "notes": p.notes, "is_law_firm": p.type == "law_firm",
        "referred_in": len(opp_ids | {r.id for r in refs if r.direction == "in" and not r.opportunity_id}), "referred_out": sum(1 for r in refs if r.direction == "out"),
        "commission_label": commission_label(p) if money or p.type == "law_firm" else None,
        "commission_rule": p.commission_rule if money else None,
        "won_value": _won_value(db, opp_ids) if money else None,
        "commission_due": _money(sum(due)) if money and due else None,
    }


def commission_out(db: Session, c: Commission) -> dict:
    from app.sales.models import Opportunity

    p = db.get(Partner, c.partner_id)
    opp = db.get(Opportunity, c.opportunity_id)
    org = db.get(Organization, c.organization_id)
    return {"id": c.id, "partner": p.name if p else None, "partner_id": c.partner_id, "client": org.name if org else None, "opportunity": opp.service if opp else None,
            "opportunity_id": c.opportunity_id, "order_ref": c.order_ref, "base_value": c.base_value, "rate": c.rate, "amount": c.amount, "due_on": c.due_on.isoformat(),
            "status": c.status, "paid_on": c.paid_on.isoformat() if c.paid_on else None, "void_reason": c.void_reason}


def referral_out(db: Session, r: Referral) -> dict:
    from app.sales.models import Opportunity

    p = db.get(Partner, r.partner_id)
    org = db.get(Organization, r.organization_id)
    opp = db.get(Opportunity, r.opportunity_id) if r.opportunity_id else None
    who = db.get(User, r.recorded_by) if r.recorded_by else None
    return {"id": r.id, "partner": p.name if p else None, "partner_id": r.partner_id, "direction": r.direction, "client": org.name if org and org.type == "client" else None,
            "opportunity": opp.service if opp else None, "opportunity_id": r.opportunity_id, "note": r.note, "at": r.at.isoformat(), "recorded_by": who.name if who else None}


def screen(db: Session, *, money: bool) -> dict:
    ps = list(db.scalars(select(Partner).where(Partner.deleted_at.is_(None)).order_by(Partner.status, Partner.name)))
    refs = list(db.scalars(select(Referral).where(Referral.deleted_at.is_(None)).order_by(Referral.at.desc()).limit(200)))
    comms = list(db.scalars(select(Commission).where(Commission.deleted_at.is_(None)).order_by(Commission.due_on.desc()).limit(200))) if money else None
    return {"partners": [partner_out(db, p, money=money) for p in ps], "referrals": [referral_out(db, r) for r in refs],
            "commissions": [commission_out(db, c) for c in comms] if comms is not None else None,
            "types": [{"value": k, "label": v} for k, v in TYPE_LABELS.items()], "law_firm_note": LAW_FIRM_NOTE}
