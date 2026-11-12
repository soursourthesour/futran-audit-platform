"""Proposal APIs for Futran staff: SM-09 builder, SM-10 preview and send, SM-11 approvals, proposal templates tab."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, Invalid, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.proposals import approvals, document, guardrails, sending, templates
from app.proposals import service as ps
from app.proposals.models import Proposal, ProposalLine
from app.tenancy.models import Organization, User

router = APIRouter(tags=["proposals"])
STATUS_LABELS = {"draft": "Draft", "awaiting_approval": "Awaiting approval", "approved": "Approved", "sent": "Sent", "viewed": "Viewed",
                 "changes_requested": "Changes requested", "accepted": "Accepted", "expired": "Expired", "superseded": "Superseded"}


def _can(db: Session, actor: Actor, action: Action) -> bool:
    try:
        authorize(db, actor, action)
        return True
    except (Forbidden, NotFound):
        return False


def _names(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    return {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def line_out(ln: ProposalLine, names: dict) -> dict:
    badges = []
    if not ln.on_catalog:
        badges.append("Not on the price list")
    elif ln.sellable_status == "roadmap":
        badges.append("Roadmap")
    elif ln.sellable_status == "manual_delivery":
        badges.append("Manual delivery")
    if ln.on_catalog and ln.sellable_status != "roadmap":
        if ln.override_price is not None:
            badges.append("Edited")
        elif ln.price_status == "proposed":
            badges.append("Proposed price")
        elif ln.price_status == "approved":
            badges.append("Approved")
        elif ln.price_status == "existing":
            badges.append("Existing price")
        if ln.unit_price_used is None:
            badges.append("No price")
        elif ln.low is not None and ln.unit_price_used < ln.low:
            badges.append("Below Low")
        elif ln.high is not None and ln.unit_price_used > ln.high:
            badges.append("Above High")
    return {"id": ln.id, "code": ln.catalog_code, "name": ln.name, "description": ln.description, "deliverables": ln.deliverables_text,
            "deliverables_edited": ln.deliverables_edited, "qty": ln.qty, "list_price": ln.list_price, "low": ln.low, "high": ln.high,
            "override_price": ln.override_price, "unit_price_used": ln.unit_price_used, "periods_per_year": ln.periods_per_year,
            "line_value": ln.line_value, "percent_of": ln.percent_of, "billing": ln.billing, "billing_label": document.BILLING_WORDS.get(ln.billing, ln.billing),
            "basis": ln.basis, "pricing_unit": ln.pricing_unit, "price_status": ln.price_status, "sellable_status": ln.sellable_status, "on_catalog": ln.on_catalog,
            "source": ln.source, "rule_code": ln.rule_code, "reason": ln.reason, "removed_reason": ln.removed_reason, "edited_by": names.get(ln.edited_by),
            "edited_at": ln.edited_at.isoformat() if ln.edited_at else None, "badges": badges}


def proposal_out(db: Session, actor: Actor, p: Proposal, full: bool = True) -> dict:
    from app.sales.models import Opportunity

    org = db.get(Organization, p.organization_id)
    opp = db.get(Opportunity, p.opportunity_id)
    d = {"id": p.id, "thread_id": p.thread_id, "version": p.version, "status": p.status, "status_label": STATUS_LABELS.get(p.status, p.status),
         "title": p.title, "company": org.name if org else None, "prospect": bool(org and org.status == "prospect"), "opportunity_id": p.opportunity_id,
         "opportunity": getattr(opp, "name", None) or (opp.service if opp else None), "opportunity_stage": opp.stage if opp else None,
         "package": p.package, "totals": p.totals or {}, "valid_days": p.valid_days, "valid_until": p.valid_until.isoformat() if p.valid_until else None,
         "sent_at": p.sent_at.isoformat() if p.sent_at else None, "editable": p.editable, "updated_at": p.updated_at.isoformat() if p.updated_at else None}
    if not full:
        return d
    ls = ps.lines(db, p)
    names = _names(db, [ln.edited_by for ln in ls] + [p.created_by, p.updated_by, p.sent_by])
    states = guardrails.rule_states(db, p, ls)
    from app.catalog.models import PackageTemplate

    d.update({
        "lines": [line_out(ln, names) for ln in ls], "discount_recurring_pct": p.discount_recurring_pct, "terms": p.terms or {},
        "sections": p.sections or [], "independence": p.independence or {}, "catalog_version": p.catalog_version,
        "questionnaire_version": p.questionnaire_version, "estimate_id": p.estimate_id, "created_by": names.get(p.created_by),
        "updated_by": names.get(p.updated_by), "sent_by": names.get(p.sent_by),
        "rules": states, "approvals_needed": [s for s in states if s["kind"] == "approval" and s["state"] != "approved"],
        "can_request": p.editable and any(s["kind"] == "approval" and s["state"] in ("missing", "returned", "outdated") for s in states),
        "send_blockers": sending.preflight(db, p) if p.editable else [],
        "versions": [{"id": v.id, "version": v.version, "status": v.status, "status_label": STATUS_LABELS.get(v.status, v.status),
                      "sent_at": v.sent_at.isoformat() if v.sent_at else None, "y1_total": (v.totals or {}).get("y1_total")} for v in ps.thread(db, p.thread_id)],
        "packages": [{"key": k.key, "name": k.name} for k in db.scalars(select(PackageTemplate).order_by(PackageTemplate.sort))],
        "regions": ps.REGIONS, "discount_limit_pct": guardrails.discount_limit(db), "can_work": _can(db, actor, Action.WORK_PROPOSALS),
        "file_ids": p.file_ids or {}, "price_changes": ps.price_changes(db, p) if p.editable else [],
    })
    return d


def _get(db: Session, proposal_id: str) -> Proposal:
    return ps.get(db, proposal_id)


def _work(db, actor, proposal_id) -> Proposal:
    authorize(db, actor, Action.WORK_PROPOSALS)
    return _get(db, proposal_id)


@router.get("/sales/proposals")
def list_proposals(opportunity_id: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_PROPOSALS)
    stmt = select(Proposal).order_by(Proposal.updated_at.desc())
    if opportunity_id:
        stmt = stmt.where(Proposal.opportunity_id == opportunity_id)
    latest: dict[str, Proposal] = {}
    for p in db.scalars(stmt):
        if p.thread_id not in latest or p.version > latest[p.thread_id].version:
            latest[p.thread_id] = p
    return {"items": [proposal_out(db, actor, p, full=False) for p in latest.values()]}


@router.post("/sales/proposals")
def create(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.sales.models import Opportunity

    authorize(db, actor, Action.WORK_PROPOSALS)
    opp = db.get(Opportunity, body.get("opportunity_id") or "")
    if opp is None:
        raise Invalid(errors=[{"field": "opportunity_id", "message": "Choose an opportunity."}])
    p = ps.create_blank(db, opp, actor.user, body.get("package") or None)
    return proposal_out(db, actor, p)


@router.get("/sales/proposals/{proposal_id}")
def get_one(proposal_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_PROPOSALS)
    p = _get(db, proposal_id)
    ps.refresh_independence(db, p)  # a prospect may have become an audit client since the draft started
    return proposal_out(db, actor, p)


@router.post("/sales/proposals/{proposal_id}/current-prices")
def current_prices(proposal_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    ps.update_to_current_prices(db, actor.user, p)
    return proposal_out(db, actor, p)


@router.patch("/sales/proposals/{proposal_id}")
def patch(proposal_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    ps.update_terms(db, actor.user, p, body)
    return proposal_out(db, actor, p)


@router.post("/sales/proposals/{proposal_id}/lines")
def add_line(proposal_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    ps.add_line(db, actor.user, p, str(body.get("code") or "").strip(), body.get("qty", 1))
    return proposal_out(db, actor, p)


@router.patch("/sales/proposals/{proposal_id}/lines/{line_id}")
def patch_line(proposal_id: str, line_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    ps.update_line(db, actor.user, p, line_id, {k: v for k, v in body.items() if k in ("qty", "override_price", "deliverables_text", "description")})
    return proposal_out(db, actor, p)


@router.post("/sales/proposals/{proposal_id}/lines/{line_id}/remove")
def remove_line(proposal_id: str, line_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    ps.remove_line(db, actor.user, p, line_id, body.get("reason"))
    return proposal_out(db, actor, p)


@router.post("/sales/proposals/{proposal_id}/lines/{line_id}/restore")
def restore_line(proposal_id: str, line_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    ps.restore_line(db, actor.user, p, line_id)
    return proposal_out(db, actor, p)


@router.post("/sales/proposals/{proposal_id}/package")
def package(proposal_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    ps.apply_package(db, actor.user, p, str(body.get("package") or ""))
    return proposal_out(db, actor, p)


@router.put("/sales/proposals/{proposal_id}/sections/{key}")
def section(proposal_id: str, key: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    ps.update_section(db, actor.user, p, key, body.get("body"))
    return proposal_out(db, actor, p)


@router.post("/sales/proposals/{proposal_id}/versions")
def new_version(proposal_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    return proposal_out(db, actor, ps.new_version(db, actor.user, p))


@router.get("/sales/proposals/{proposal_id}/diff")
def diff(proposal_id: str, against: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_PROPOSALS)
    p = _get(db, proposal_id)
    other = _get(db, against) if against else (db.get(Proposal, p.previous_id) if p.previous_id else None)
    if other is None or other.thread_id != p.thread_id:
        raise NotFound("There is no earlier version to compare with.")
    a, b = (other, p) if other.version < p.version else (p, other)
    return ps.diff(db, a, b)


@router.post("/sales/proposals/{proposal_id}/approvals")
def request_approvals(proposal_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    made = approvals.request(db, actor.user, p, settings=request.app.state.settings)
    return {"requested": [q.rule for q in made], "proposal": proposal_out(db, actor, p)}


# ---- SM-10
@router.get("/sales/proposals/{proposal_id}/document")
def preview(proposal_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_PROPOSALS)
    p = _get(db, proposal_id)
    from app.sales.models import Opportunity

    opp = db.get(Opportunity, p.opportunity_id)
    contacts = []
    try:
        from app.sales.models import OpportunityContact  # R2

        contacts = [{"name": c.name, "email": c.email, "title": getattr(c, "title", None)}
                    for c in db.scalars(select(OpportunityContact).where(OpportunityContact.opportunity_id == p.opportunity_id)) if getattr(c, "email", None)]
    except ImportError:
        pass
    me = actor.user
    return {"proposal": proposal_out(db, actor, p, full=False), "sections": document.html_sections(db, p), "log": sending.log(db, p),
            "links": sending.links_out(db, p), "send_blockers": sending.preflight(db, p) if p.editable else [],
            "approvals": [s for s in guardrails.rule_states(db, p, ps.lines(db, p)) if s["kind"] == "approval"],
            "contacts": contacts, "default_subject": sending.DEFAULT_SUBJECT, "default_message": sending.DEFAULT_MESSAGE,
            "sender": _sender_label(db, request_settings(db), me), "owner_id": opp.owner_id if opp else None,
            "valid_until_if_sent": document.fmt_day(document.valid_until(p)), "can_work": _can(db, actor, Action.WORK_PROPOSALS)}


def request_settings(db):
    from app.core.config import get_settings

    return get_settings()


def _sender_label(db: Session, settings, user: User) -> str:
    from app.mail.models import UserMailConnection

    uc = db.scalar(select(UserMailConnection).where(UserMailConnection.user_id == user.id, UserMailConnection.status == "connected",
                                                    UserMailConnection.deleted_at.is_(None)))
    if uc is not None and uc.mailbox:
        return f"{user.name} · {uc.mailbox}"
    return "Futran's mailbox (connect your own mailbox in Email settings to send as yourself)"


@router.get("/sales/proposals/{proposal_id}/export.{fmt}")
def export(proposal_id: str, fmt: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_PROPOSALS)
    p = _get(db, proposal_id)
    if fmt not in ("pdf", "docx"):
        raise NotFound()
    fid = (p.file_ids or {}).get(fmt)
    if fid:  # a sent version exports exactly the file that went out
        from app.files.models import FileObject
        from app.files.service import read

        f = db.get(FileObject, fid)
        data, name = read(request.app.state.settings, f), f.filename
    else:
        data = document.to_pdf(db, p) if fmt == "pdf" else document.to_docx(db, p)
        name = document.filename(db, p, fmt)
    ctype = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content=data, media_type=ctype, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "Cache-Control": "private, no-store"})


@router.post("/sales/proposals/{proposal_id}/send")
def send(proposal_id: str, body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    links = sending.send(db, request.app.state.settings, actor.user, p, recipients=body.get("recipients"), subject=body.get("subject"), message=body.get("message"))
    return {"sent": len(links), "proposal": proposal_out(db, actor, p, full=False)}


@router.post("/sales/proposals/{proposal_id}/links/{link_id}/remind")
def remind(proposal_id: str, link_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _work(db, actor, proposal_id)
    sending.remind(db, request.app.state.settings, actor.user, p, link_id)
    return {"links": sending.links_out(db, p), "log": sending.log(db, p)}


# ---- SM-11
@router.get("/sales/approvals")
def approvals_queue(tab: str = "mine", actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.DECIDE_PROPOSAL_APPROVALS)
    if tab not in ("mine", "pricing", "independence", "decided"):
        tab = "mine"
    return {"tab": tab, "items": approvals.queue(db, actor.user, tab), "counts": approvals.counts(db, actor.user),
            "roles": sorted(approvals.roles_of(db, actor.user) & {"sales_manager", "pricing_approver", "chief_auditor"})}


@router.get("/sales/approvals/{request_id}")
def approval_detail(request_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.DECIDE_PROPOSAL_APPROVALS)
    return approvals.detail(db, actor.user, request_id)


@router.post("/sales/approvals/{request_id}/decide")
def decide(request_id: str, body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.DECIDE_PROPOSAL_APPROVALS)
    q = approvals.decide(db, actor.user, approvals.get(db, request_id), str(body.get("decision") or ""), body.get("note"), settings=request.app.state.settings)
    return approvals.detail(db, actor.user, q.id)


# ---- SM-14 Proposal templates tab
@router.get("/sales/proposal-templates")
def list_templates(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not (_can(db, actor, Action.MANAGE_PROPOSAL_TEMPLATES) or _can(db, actor, Action.VIEW_CATALOG)):
        authorize(db, actor, Action.MANAGE_PROPOSAL_TEMPLATES)
    rows = templates.all_templates(db)
    names = _names(db, [t.updated_by for t in rows])
    return {"items": [templates.out(t, names) for t in rows], "merge_fields": list(templates.MERGE_FIELDS),
            "can_edit": _can(db, actor, Action.MANAGE_PROPOSAL_TEMPLATES)}


@router.put("/sales/proposal-templates/{key}")
def put_template(key: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.MANAGE_PROPOSAL_TEMPLATES)
    t = templates.update(db, actor.user, key, body)
    return templates.out(t, _names(db, [t.updated_by]))
