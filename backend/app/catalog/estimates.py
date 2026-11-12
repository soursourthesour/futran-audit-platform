"""Estimator (SM-15): internal price estimates, saved on an opportunity as versions. The master never changes here:
every edit lives on the estimate line (edited price, description or deliverables for this client)."""
import importlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import guardrails, pricing
from app.catalog import service as cat
from app.catalog.models import Estimate, PackageTemplate
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.tenancy.models import User

REGIONS = {"us": "United States", "eu": "European Union", "uk": "United Kingdom", "in": "India", "ca": "Canada"}
TERMS = (1, 2, 3)
CONVERT_NOTE = "Convert to proposal opens once the Proposal builder (SM-09) is installed."
NEEDS_OPPORTUNITY = "Choose the opportunity this estimate is for and save it; then convert it to a proposal."


def proposal_builder():
    """R4's `proposals.service.create_from_estimate(db, estimate, actor)`, or None until it lands."""
    try:
        mod = importlib.import_module("app.proposals.service")
    except ImportError:
        return None
    return getattr(mod, "create_from_estimate", None)


def why_not(item) -> str | None:
    """Why an item can't go on a new estimate line, or None."""
    if item.status != "active":
        return f"{item.code} is retired: it stays on old estimates but can't be added to new ones."
    if item.sellable_status == "roadmap":
        return f"{item.code} is a roadmap item and can't be added. A proposal can list it under \"Optional, when available\" with no price."
    return None


def _num(v, field: str, code: str):
    if v is None or v == "":
        return None
    try:
        n = float(str(v).replace(",", "").replace("$", ""))
    except ValueError as exc:
        raise Invalid(errors=[{"field": field, "code": code, "message": f"{code}: enter a number."}]) from exc
    if n < 0:
        raise Invalid(errors=[{"field": field, "code": code, "message": f"{code}: prices and quantities cannot be negative."}])
    n = round(n, 2)
    return int(n) if n == int(n) else n


def clean_lines(db: Session, raw: list[dict], *, previous: list[dict] | None = None) -> list[dict]:
    """Check what the rep sent: known codes, quantities above zero, no roadmap items, no retired items unless the line
    was already on the previous version of this estimate."""
    if not isinstance(raw, list) or len(raw) > 200:
        raise Invalid(errors=[{"field": "lines", "message": "Send up to 200 lines."}])
    items = cat.items_by_codes(db, [r.get("code") for r in raw if isinstance(r, dict)])
    kept = {ln.get("code") for ln in previous or []}
    out, errors = [], []
    for r in raw:
        code = (r or {}).get("code")
        item = items.get(code)
        if item is None:
            errors.append({"field": "lines", "code": code, "message": f"{code} is not on the price list."})
            continue
        problem = why_not(item)
        if problem and not (item.status != "active" and code in kept and item.sellable_status != "roadmap"):
            errors.append({"field": "lines", "code": code, "message": problem})
            continue
        qty = _num(r.get("qty", 1), "qty", code)
        if qty is None or qty <= 0:
            errors.append({"field": "qty", "code": code, "message": f"{code}: quantity must be more than 0."})
            continue
        line = {"code": code, "qty": qty, "edited_price": _num(r.get("edited_price"), "edited_price", code)}
        for k, limit in (("description", 1000), ("deliverables_override", 8000)):
            v = (r.get(k) or "").strip()
            if v and v != ((item.description if k == "description" else item.deliverables) or "").strip():
                line[k] = v[:limit]
        out.append(line)
    if errors:
        raise Invalid(errors=errors)
    return out


def _terms(body: dict) -> dict:
    t = body.get("terms") or {}
    out = {}
    if t.get("payment_days") not in (None, ""):
        out["payment_days"] = int(t["payment_days"])
    for k in ("custom_liability", "sla_credits"):
        if t.get(k):
            out[k] = t[k]
    if t.get("discount_one_time_pct"):
        out["discount_one_time_pct"] = float(t["discount_one_time_pct"])
    return out


def evaluate(db: Session, lines: list[dict], discount_recurring_pct: float, terms: dict) -> dict:
    priced = pricing.price_lines(db, lines)
    limit = cat.settings(db).manager_discount_limit_pct
    approvals = guardrails.needed_approvals(priced, discount_recurring_pct, terms, discount_limit_pct=limit)
    return {"lines": priced, "totals": pricing.totals(priced, discount_recurring_pct), "approvals": approvals,
            "summary": guardrails.summary(priced, approvals), "catalog_version": cat.current_version(db)}


def _discount(body: dict) -> float:
    try:
        d = float(body.get("discount_recurring_pct") or 0)
    except (TypeError, ValueError) as exc:
        raise Invalid(errors=[{"field": "discount_recurring_pct", "message": "Enter a percentage."}]) from exc
    if not 0 <= d <= 100:
        raise Invalid(errors=[{"field": "discount_recurring_pct", "message": "Enter a percentage between 0 and 100."}])
    return d


def preview(db: Session, body: dict) -> dict:
    return evaluate(db, clean_lines(db, body.get("lines") or []), _discount(body), _terms(body))


def latest(db: Session, thread_id: str) -> Estimate | None:
    return db.scalar(select(Estimate).where(Estimate.thread_id == thread_id).order_by(Estimate.version.desc()).limit(1))


def save(db: Session, actor: User, body: dict) -> Estimate:
    """Save the estimate as a new version (the first, or the next on `thread_id`). Saving is always allowed."""
    from app.sales.models import Opportunity

    thread_id = body.get("thread_id")
    prev = latest(db, thread_id) if thread_id else None
    if thread_id and prev is None:
        raise NotFound()
    opp_id = body.get("opportunity_id") or (prev.opportunity_id if prev else None)
    if opp_id and db.get(Opportunity, opp_id) is None:
        raise Invalid(errors=[{"field": "opportunity_id", "message": "Choose an opportunity from the list."}])
    name = (body.get("name") or (prev.name if prev else "") or "").strip()
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Name the estimate."}])
    term = int(body.get("term") or (prev.term if prev else 1))
    if term not in TERMS:
        raise Invalid(errors=[{"field": "term", "message": "Choose a term of 1, 2 or 3 years."}])
    region = body.get("data_region") or None
    if region and region not in REGIONS:
        raise Invalid(errors=[{"field": "data_region", "message": "Choose a data region from the list."}])
    lines = clean_lines(db, body.get("lines") or [], previous=prev.lines if prev else None)
    discount, terms = _discount(body), _terms(body)
    ev = evaluate(db, lines, discount, terms)
    now = utcnow()
    before = {ln["code"]: ln for ln in (prev.lines if prev else [])}
    for ln in ev["lines"]:
        old = before.get(ln["code"])
        if ln["edited"]:
            same = old is not None and old.get("edited_price") == ln["edited_price"]
            ln["edited_by"] = old.get("edited_by") if same else actor.id
            ln["edited_at"] = old.get("edited_at") if same else now.isoformat()
    e = Estimate(thread_id="", opportunity_id=opp_id, name=name[:200], version=(prev.version + 1) if prev else 1, package=body.get("package") or (prev.package if prev else None),
                 lines=ev["lines"], discount_recurring_pct=discount, term=term, data_region=region, terms=terms,
                 totals={**ev["totals"], "approvals": ev["approvals"], "summary": ev["summary"]}, catalog_version=ev["catalog_version"],
                 created_by=prev.created_by if prev else actor.id, created_at=prev.created_at if prev else now, saved_by=actor.id, saved_at=now)
    db.add(e)
    db.flush()
    e.thread_id = thread_id or e.id
    db.flush()
    from app.audit_log import service as audit

    audit.record(db, actor_id=actor.id, action="estimate.save", organization_id=actor.organization_id, object_type="Estimate", object_id=e.id,
                 summary=f"Saved estimate \"{e.name}\" v{e.version}: year-1 total ${ev['totals']['y1_total']:,}")
    return e


def price_changes(db: Session, e: Estimate) -> list[dict]:
    """Lines still at list whose master list price has changed since the estimate was saved (the SM-15 banner)."""
    items = cat.items_by_codes(db, [ln["code"] for ln in e.lines])
    out = []
    for ln in e.lines:
        it = items.get(ln["code"])
        if it is None or ln.get("edited") or it.list_price == ln.get("list_price"):
            continue
        out.append({"code": ln["code"], "name": ln.get("name"), "old": ln.get("list_price"), "new": it.list_price})
    return out


def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def opportunity_label(db: Session, opp) -> str:
    from app.tenancy.models import Organization

    org = db.get(Organization, opp.organization_id)
    label = getattr(opp, "name", None) or opp.service
    return f"{org.name if org else 'Unknown'} — {label}"


def out(db: Session, e: Estimate, *, full: bool = True) -> dict:
    from app.sales.models import Opportunity

    opp = db.get(Opportunity, e.opportunity_id) if e.opportunity_id else None
    builder = proposal_builder()
    d = {"id": e.id, "thread_id": e.thread_id, "name": e.name, "version": e.version, "opportunity_id": e.opportunity_id,
         "opportunity": opportunity_label(db, opp) if opp else None, "package": e.package, "discount_recurring_pct": e.discount_recurring_pct, "term": e.term,
         "data_region": e.data_region, "terms": e.terms or {}, "totals": {k: v for k, v in (e.totals or {}).items() if k not in ("approvals", "summary")},
         "approvals": (e.totals or {}).get("approvals", []), "summary": (e.totals or {}).get("summary"), "catalog_version": e.catalog_version,
         "saved_by": _name(db, e.saved_by), "saved_at": e.saved_at.isoformat(), "created_by": _name(db, e.created_by),
         "converted_proposal_id": e.converted_proposal_id, "can_convert": builder is not None and bool(e.opportunity_id),
         "convert_note": CONVERT_NOTE if builder is None else (None if e.opportunity_id else NEEDS_OPPORTUNITY)}
    if full:
        names = {}
        for ln in e.lines:
            if ln.get("edited_by") and ln["edited_by"] not in names:
                names[ln["edited_by"]] = _name(db, ln["edited_by"])
        d["lines"] = [{**ln, "edited_by": names.get(ln.get("edited_by"), ln.get("edited_by"))} for ln in e.lines]
        d["versions"] = [{"id": v.id, "version": v.version, "saved_by": _name(db, v.saved_by), "saved_at": v.saved_at.isoformat(),
                          "y1_total": (v.totals or {}).get("y1_total")}
                         for v in db.scalars(select(Estimate).where(Estimate.thread_id == e.thread_id).order_by(Estimate.version.desc()))]
        d["price_changes"] = price_changes(db, e)
        d["current_catalog_version"] = cat.current_version(db)
    return d


def convert(db: Session, actor, e: Estimate) -> str:
    builder = proposal_builder()
    if builder is None:
        raise Conflict(CONVERT_NOTE)
    if not e.opportunity_id:
        raise Conflict(NEEDS_OPPORTUNITY)
    if e.converted_proposal_id:
        return e.converted_proposal_id
    proposal = builder(db, e, getattr(actor, "user", actor))  # the proposal builder takes the signed-in User
    for v in db.scalars(select(Estimate).where(Estimate.thread_id == e.thread_id)):
        if v.id == e.id:
            v.converted_proposal_id = proposal.id
    db.flush()
    return proposal.id


def packages(db: Session) -> list[PackageTemplate]:
    return cat.packages(db)
