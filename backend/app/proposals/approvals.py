"""Approvals (SM-11; spec §4.7). One request per rule per proposal version, decided by someone holding the rule's role
who did not build or edit this version and does not own the opportunity: nobody approves their own proposal.

- P-2, P-5 → Sales Manager (a Pricing Approver may decide them too)
- P-1, P-3, P-4, P-6 → Pricing Approver
- I-1, I-2, I-3 → Chief Auditor (I-1 needs a note)
Approving here applies to this proposal version only; the master price list never changes from SM-11."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.proposals import guardrails
from app.proposals import service as ps
from app.proposals.models import ApprovalRequest, Proposal
from app.tenancy.models import Organization, RoleAssignment, User

PRICING_RULES = ("P-1", "P-2", "P-3", "P-4", "P-5", "P-6")
INDEPENDENCE_RULES = ("I-1", "I-2", "I-3", "I-4")
NOTE_REQUIRED = ("I-1",)


def roles_of(db: Session, user: User) -> set[str]:
    return {r.role for r in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == user.id, RoleAssignment.deleted_at.is_(None)))}


def users_with(db: Session, roles) -> list[User]:
    q = (select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).join(Organization, Organization.id == User.organization_id)
         .where(RoleAssignment.role.in_(list(roles)), RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None), User.status != "disabled",
                Organization.type == "futran"))
    return list({u.id: u for u in db.scalars(q)}.values())


def unmet(db: Session, p: Proposal) -> list[dict]:
    return guardrails.unmet(db, p, ps.lines(db, p))


def _company(db: Session, p: Proposal) -> str:
    org = db.get(Organization, p.organization_id)
    return org.name if org else "Unknown"


def request(db: Session, actor, p: Proposal, settings=None) -> list[ApprovalRequest]:
    """Ask for every approval this version still needs (missing, returned or outdated). Already pending: left alone."""
    from app.notifications.service import notify

    if not p.editable:
        raise Conflict("This version was sent: approvals are asked before sending.")
    ls = ps.lines(db, p)
    fp = guardrails.fingerprint(p, ls)
    by_line = {}
    for ln in ls:
        by_line.setdefault(ln.catalog_code, ln.id)
    made = []
    for r in guardrails.rule_states(db, p, ls):
        if r["kind"] != "approval" or r["state"] in ("pending", "approved"):
            continue
        for old in db.scalars(select(ApprovalRequest).where(ApprovalRequest.proposal_id == p.id, ApprovalRequest.rule == r["rule"], ApprovalRequest.status == "pending")):
            old.status = "withdrawn"  # an outdated pending request is replaced
        q = ApprovalRequest(proposal_id=p.id, rule=r["rule"], codes=r["codes"], line_ids=[by_line[c] for c in r["codes"] if c in by_line], message=r["message"],
                            fingerprint=fp, requested_by=actor.id, approver_role=r["approver_role"], status="pending")
        db.add(q)
        made.append(q)
    db.flush()
    company = _company(db, p)
    for q in made:
        approvers = [u for u in users_with(db, guardrails.DECIDERS[q.approver_role]) if u.id not in ps.touched_by(db, p)]
        notify(db, approvers, "proposal_approval_needed", f"Approval needed: {company} proposal v{p.version} · {q.rule}", q.message,
               f"/sales/approvals?request={q.id}", settings=settings, email_template="notification" if settings is not None else None)
        audit.record(db, actor_id=actor.id, action="proposal.approval_requested", organization_id=actor.organization_id, object_type="ApprovalRequest",
                     object_id=q.id, summary=f"{company} proposal v{p.version}: {q.rule} sent to the {guardrails.APPROVER_LABELS[q.approver_role]}")
    ps.refresh_status(db, p, ls)
    return made


def get(db: Session, request_id: str) -> ApprovalRequest:
    q = db.get(ApprovalRequest, request_id)
    if q is None:
        raise NotFound()
    return q


def why_not(db: Session, actor: User, q: ApprovalRequest) -> str | None:
    p = db.get(Proposal, q.proposal_id)
    if not (roles_of(db, actor) & guardrails.DECIDERS.get(q.approver_role, set())):
        return f"{q.rule} is decided by the {guardrails.APPROVER_LABELS.get(q.approver_role, q.approver_role)}."
    if actor.id in ps.touched_by(db, p) or actor.id == q.requested_by:
        return "You built, edited or own this proposal. Nobody approves their own proposal."
    return None


def decide(db: Session, actor: User, q: ApprovalRequest, decision: str, note: str | None, settings=None) -> ApprovalRequest:
    from app.notifications.service import notify
    from app.sales.models import Opportunity

    if decision not in ("approve", "return"):
        raise Invalid(errors=[{"field": "decision", "message": "Approve or return."}])
    if q.status != "pending":
        raise Conflict("This request was already decided or replaced.")
    problem = why_not(db, actor, q)
    if problem:
        raise Forbidden(problem)
    p = db.get(Proposal, q.proposal_id)
    if not p.editable:
        raise Conflict("This version was already sent.")
    note = " ".join((note or "").split())[:2000] or None
    if decision == "return" and not note:
        raise Invalid(errors=[{"field": "note", "message": "Say what the rep should change."}])
    if decision == "approve" and q.rule in NOTE_REQUIRED and not note:
        raise Invalid(errors=[{"field": "note", "message": "I-1 is approved with a note: say why the line can be sold."}])
    ls = ps.lines(db, p)
    if decision == "approve" and q.fingerprint != guardrails.fingerprint(p, ls):
        q.status = "withdrawn"
        db.flush()
        raise Conflict("The proposal changed after this request was made. The rep asks again for the current version.")
    q.status = "approved" if decision == "approve" else "returned"
    q.note, q.approver_id, q.decided_at = note, actor.id, utcnow()
    db.flush()
    ps.refresh_status(db, p, ls)
    opp = db.get(Opportunity, p.opportunity_id)
    company = _company(db, p)
    word = "approved" if decision == "approve" else "returned"
    owner = db.get(User, opp.owner_id) if opp and opp.owner_id else None
    requester = db.get(User, q.requested_by)
    notify(db, [owner, requester], "proposal_approval_decided", f"{q.rule} {word} on {company} proposal v{p.version}", note or q.message,
           f"/sales/proposals/{p.id}")
    if opp is not None:
        ps._log_opp(db, opp, f"{q.rule} {word} by {actor.name} on proposal v{p.version}" + (f": {note}" if note else "."), actor)
    audit.record(db, actor_id=actor.id, action=f"proposal.approval_{word}", organization_id=actor.organization_id, object_type="ApprovalRequest",
                 object_id=q.id, summary=f"{company} proposal v{p.version}: {q.rule} {word}")
    return q


# ---- SM-11 queue
def _visible_roles(db: Session, actor: User) -> set[str]:
    mine = roles_of(db, actor)
    out = set()
    for role, deciders in guardrails.DECIDERS.items():
        if mine & deciders:
            out.add(role)
    return out


def _item(db: Session, q: ApprovalRequest, names: dict) -> dict:
    p = db.get(Proposal, q.proposal_id)
    return {"id": q.id, "rule": q.rule, "message": q.message, "codes": q.codes, "status": q.status, "approver_role": q.approver_role,
            "approver_label": guardrails.APPROVER_LABELS.get(q.approver_role), "proposal_id": p.id, "version": p.version, "company": _company(db, p),
            "y1_total": (p.totals or {}).get("y1_total"), "requested_by": names.get(q.requested_by), "requested_at": q.requested_at.isoformat(),
            "decided_at": q.decided_at.isoformat() if q.decided_at else None, "decided_by": names.get(q.approver_id), "note": q.note,
            "kind": "independence" if q.rule.startswith("I-") else "pricing"}


def _names(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    return {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def queue(db: Session, actor: User, tab: str = "mine") -> list[dict]:
    """mine: pending requests this person may decide; pricing / independence: every pending request of that kind;
    decided: the last 100 decisions."""
    stmt = select(ApprovalRequest)
    if tab == "decided":
        stmt = stmt.where(ApprovalRequest.status.in_(("approved", "returned"))).order_by(ApprovalRequest.decided_at.desc()).limit(100)
    else:
        stmt = stmt.where(ApprovalRequest.status == "pending").order_by(ApprovalRequest.requested_at)
    rows = list(db.scalars(stmt))
    if tab == "mine":
        roles = _visible_roles(db, actor)
        rows = [q for q in rows if q.approver_role in roles and why_not(db, actor, q) is None]
    elif tab == "pricing":
        rows = [q for q in rows if q.rule in PRICING_RULES]
    elif tab == "independence":
        rows = [q for q in rows if q.rule in INDEPENDENCE_RULES]
    names = _names(db, [q.requested_by for q in rows] + [q.approver_id for q in rows])
    return [_item(db, q, names) for q in rows]


def counts(db: Session, actor: User) -> dict:
    return {"mine": len(queue(db, actor, "mine")), "pricing": len(queue(db, actor, "pricing")), "independence": len(queue(db, actor, "independence"))}


def detail(db: Session, actor: User, request_id: str) -> dict:
    """The selected request: its lines with the price used against the catalog Low, List and High, a margin note, and
    the independence context for I-rules."""
    from app.catalog.service import items_by_codes

    q = get(db, request_id)
    p = db.get(Proposal, q.proposal_id)
    ls = ps.lines(db, p)
    names = _names(db, [q.requested_by, q.approver_id])
    focus = set(q.codes or [])
    items = items_by_codes(db, [ln.catalog_code for ln in ls])
    rows = []
    for ln in guardrails.offered(ls):
        it = items.get(ln.catalog_code)
        rows.append({"code": ln.catalog_code, "name": ln.name, "qty": ln.qty, "low": ln.low, "list": ln.list_price, "used": ln.unit_price_used,
                     "high": ln.high, "edited": ln.override_price is not None, "price_status": ln.price_status, "value": ln.line_value,
                     "current_list": it.list_price if it else None, "focus": ln.catalog_code in focus or not focus})
    below = [r for r in rows if r["low"] is not None and r["used"] is not None and r["used"] < r["low"]]
    list_value = sum((r["list"] or 0) * r["qty"] * (ln.periods_per_year if ln.billing != "one_time" else 1)
                     for r, ln in zip(rows, guardrails.offered(ls)) if ln.basis != "%")
    used_value = sum(r["value"] or 0 for r, ln in zip(rows, guardrails.offered(ls)) if ln.basis != "%")
    t = p.totals or {}
    margin = (f"Year-1 total {_money(t.get('y1_total'))}. Lines are {_pct(used_value, list_value)} of list value"
              f"{'' if not (t.get('discount') or t.get('one_time_discount')) else f', and discounts take {_money((t.get('discount') or 0) + (t.get('one_time_discount') or 0))}'}."
              f"{' Below Low: ' + ', '.join(r['code'] for r in below) + '.' if below else ''}")
    ind = p.independence or {}
    return {**_item(db, q, names), "lines": rows, "margin_note": margin, "totals": t, "discount_recurring_pct": p.discount_recurring_pct, "terms": p.terms or {},
            "independence": {"flag": bool(ind.get("flag")), "reason": ind.get("reason")} if q.rule.startswith("I-") or ind.get("flag") else None,
            "can_decide": q.status == "pending" and why_not(db, actor, q) is None, "why_not": why_not(db, actor, q) if q.status == "pending" else None,
            "note_required": q.rule in NOTE_REQUIRED,
            "history": [{"rule": h.rule, "status": h.status, "note": h.note, "decided_at": h.decided_at.isoformat() if h.decided_at else None}
                        for h in db.scalars(select(ApprovalRequest).where(ApprovalRequest.proposal_id == p.id, ApprovalRequest.id != q.id))]}


def _money(v) -> str:
    return "—" if v is None else f"${v:,.0f}"


def _pct(a: float, b: float) -> str:
    return "100%" if not b else f"{a / b * 100:.0f}%"
