"""Proposal builder (SM-09; spec §4.6).

Functions other workstreams call:
- `create_from_estimate(db, estimate, actor)` — R1's Estimator "Convert to proposal".
- `create_from_questionnaire(db, questionnaire, actor)` — R3's "Lock and build proposal"; lines from
  `scoping.service.suggest_lines`.

Price precedence per line: the price edited on this proposal → the catalog list price → none (blocked from sending).
Year-1 value = unit price used × qty × periods per year; %-items are their percentage of the lines they apply to and
are shown as their own lines (`catalog.pricing.compute`). Saving is never blocked; guardrails only stop a send.
The master price list never changes from here. A version is editable while it is a draft and frozen once sent."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.catalog import pricing
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.proposals import guardrails, independence, templates
from app.proposals.models import EDITABLE, Proposal, ProposalLine

MAX_LINES = 200
TERM_KEYS = ("payment_days", "payment_terms", "term_years", "sla", "data_region", "custom_liability", "sla_credits", "discount_one_time_pct", "start_on")
REGIONS = {"us": "United States", "eu": "European Union", "uk": "United Kingdom", "in": "India", "ca": "Canada"}
EARLY_STAGES = ("new", "contacted", "qualified", "scoping")


def _r(x):
    if x is None:
        return None
    x = round(float(x) + 0.0, 2)
    return int(x) if x == int(x) else x


# ---- reading
def get(db: Session, proposal_id: str) -> Proposal:
    p = db.get(Proposal, proposal_id)
    if p is None:
        raise NotFound()
    return p


def lines(db: Session, p: Proposal) -> list[ProposalLine]:
    return list(db.scalars(select(ProposalLine).where(ProposalLine.proposal_id == p.id).order_by(ProposalLine.sort, ProposalLine.catalog_code)))


def thread(db: Session, thread_id: str) -> list[Proposal]:
    return list(db.scalars(select(Proposal).where(Proposal.thread_id == thread_id).order_by(Proposal.version)))


def latest_for_opportunity(db: Session, opportunity_id: str) -> Proposal | None:
    return db.scalar(select(Proposal).where(Proposal.opportunity_id == opportunity_id).order_by(Proposal.created_at.desc(), Proposal.version.desc()).limit(1))


def needed(db: Session, p: Proposal) -> list[dict]:
    return guardrails.needed(db, p, lines(db, p))


# ---- pricing
def recalc(db: Session, p: Proposal, ls: list[ProposalLine] | None = None) -> None:
    """Unit price used, line values and totals. Removed, roadmap and off-list lines carry no value."""
    ls = ls if ls is not None else lines(db, p)
    calc = []
    for ln in ls:
        ln.unit_price_used = ln.override_price if ln.override_price is not None else ln.list_price
        ln.line_value = None
        ln.percent_of = None
        if ln.removed_reason or ln.sellable_status == "roadmap" or not ln.on_catalog or ln.unit_price_used is None:
            continue
        calc.append({"code": ln.catalog_code, "product": ln.product, "basis": ln.basis, "billing": ln.billing, "qty": ln.qty,
                     "periods_per_year": ln.periods_per_year if ln.billing != "one_time" else 1, "unit_price_used": ln.unit_price_used,
                     "applies_to": list(ln.applies_to or []), "_line": ln})
    pricing.compute(calc)
    for d in calc:
        d["_line"].line_value = d["line_value"]
        d["_line"].percent_of = d.get("percent_of")
    p.totals = pricing.totals(calc, p.discount_recurring_pct)  # the Estimator's totals, so both agree for the same lines
    db.flush()
    refresh_status(db, p, ls)


def refresh_status(db: Session, p: Proposal, ls: list[ProposalLine] | None = None) -> None:
    """A draft's status follows its approvals: draft (nothing asked yet or something missing), awaiting_approval
    (requests pending), approved (every needed approval given for the content as it is now)."""
    if p.status not in EDITABLE:
        return
    states = guardrails.rule_states(db, p, ls if ls is not None else lines(db, p))
    approvals = [s for s in states if s["kind"] == "approval"]
    if approvals and all(s["state"] == "approved" for s in approvals):
        p.status = "approved"
    elif any(s["state"] == "pending" for s in approvals):
        p.status = "awaiting_approval"
    else:
        p.status = "draft"
    db.flush()


# ---- building
def _actor_id(actor) -> str | None:
    return getattr(actor, "id", None)


def _require_editable(p: Proposal) -> None:
    if not p.editable:
        raise Conflict(f"Version {p.version} was sent and can't change. Start a new version to make changes.")


TOUCH = "edit"  # ProposalEvent kind: the append-only record of who changed what on a proposal (never shown in the send log)


def _touch(p: Proposal, actor, what: str = "changed the proposal") -> None:
    """Every change goes on the touch log with who made it, so nobody who worked on any version can approve it."""
    from sqlalchemy.orm import object_session

    from app.proposals.models import ProposalEvent

    p.updated_by, p.updated_at = _actor_id(actor), utcnow()
    if _actor_id(actor):
        object_session(p).add(ProposalEvent(proposal_id=p.id, kind=TOUCH, by_id=_actor_id(actor), by_name=getattr(actor, "name", None), detail=what))


def _opportunity(db: Session, opportunity_id: str | None):
    from app.sales.models import Opportunity

    opp = db.get(Opportunity, opportunity_id) if opportunity_id else None
    if opp is None:
        raise Invalid(errors=[{"field": "opportunity_id", "message": "Save the estimate to an opportunity first: a proposal belongs to an opportunity."}])
    return opp


def _line_from_item(item, *, code: str, qty, sort: int, source: str, override=None, description=None, deliverables=None, rule_code=None, reason=None,
                    removed_reason=None) -> ProposalLine:
    if item is None:
        return ProposalLine(catalog_code=code, name=code, qty=qty, sort=sort, source=source, rule_code=rule_code, reason=(reason or "")[:400] or None,
                            removed_reason=removed_reason, on_catalog=False, sellable_status=None, price_status=None)
    override = None if override is None or override == item.list_price else override
    return ProposalLine(catalog_code=item.code, name=item.name, product=item.product, description=description or item.description,
                        deliverables_text=deliverables or item.deliverables, deliverables_edited=bool(deliverables), qty=qty, list_price=item.list_price,
                        low=item.low, high=item.high, override_price=override, periods_per_year=item.periods_per_year or 1, billing=item.billing,
                        basis=item.basis, pricing_unit=item.pricing_unit, applies_to=list(item.applies_to or []),
                        included_quantities=dict(item.included_quantities or {}), price_status=item.price_status, sellable_status=item.sellable_status,
                        on_catalog=True, sort=sort, source=source, rule_code=rule_code, reason=(reason or "")[:400] or None, removed_reason=removed_reason)


def _company(db: Session, org_id: str) -> str:
    from app.tenancy.models import Organization

    org = db.get(Organization, org_id)
    return org.name if org else "the client"


def _new(db: Session, opp, actor, *, package=None, estimate_id=None, questionnaire=None, discount=0.0, terms=None) -> Proposal:
    """A new proposal: the next version on the opportunity's proposal when one exists, else v1."""
    from app.catalog.service import current_version

    prev = latest_for_opportunity(db, opp.id)
    if prev is not None and prev.status == "accepted":
        raise Conflict("A version of this proposal was accepted. Start a new opportunity for further work.")
    flag, why = independence.flag_for(db, opp.organization_id)
    p = Proposal(thread_id="", opportunity_id=opp.id, organization_id=opp.organization_id, version=(prev.version + 1) if prev else 1,
                 previous_id=prev.id if prev else None, package=package, estimate_id=estimate_id, status="draft", discount_recurring_pct=discount or 0,
                 terms={"payment_days": 30, "term_years": 1, **(terms or {})}, catalog_version=current_version(db), independence={"flag": flag, "reason": why},
                 title=f"AI governance proposal for {_company(db, opp.organization_id)}"[:200], created_by=_actor_id(actor), updated_by=_actor_id(actor))
    if questionnaire is not None:
        p.questionnaire_id, p.questionnaire_version = questionnaire.id, getattr(questionnaire, "version", None)
    db.add(p)
    db.flush()
    p.thread_id = prev.thread_id if prev else p.id
    if prev is not None and prev.status in EDITABLE:
        prev.status = "superseded"  # an unsent draft is replaced by the new build
    p.sections = _starter_sections(db, p, questionnaire)
    db.flush()
    return p


def _questionnaire_for(db: Session, opp_id: str):
    try:
        from app.scoping.models import ScopingQuestionnaire
    except ImportError:
        return None
    return db.scalar(select(ScopingQuestionnaire).where(ScopingQuestionnaire.opportunity_id == opp_id, ScopingQuestionnaire.status == "locked")
                     .order_by(ScopingQuestionnaire.version.desc()).limit(1))


def _situation(db: Session, questionnaire) -> str:
    """Section A trigger and Sections B–C footprint answers, as plain sentences the rep edits."""
    if questionnaire is None:
        return ""
    try:
        from app.scoping import bank, rules
        from app.scoping import service as scoping

        answers = scoping.effective_answers(db, questionnaire)
        qs = bank.by_code(db, questionnaire.bank_version)
        labels = {code: {o["value"]: o["label"] for o in (q.options or [])} for code, q in qs.items()}
    except Exception:  # noqa: BLE001  the scoping module is someone else's; a missing piece leaves the section for the rep
        return ""
    out = []
    for code, q in sorted(qs.items(), key=lambda kv: (kv[1].section, kv[1].order)):
        a = answers.get(code)
        if q.section not in ("A", "B", "C") or a is None or q.internal_only or a.confidence == "unknown":
            continue
        out.append(f"- {q.client_label or q.label}: {rules.show(code, a, labels)}")
    return "\n".join(out)


def _starter_sections(db: Session, p: Proposal, questionnaire=None) -> list[dict]:
    tpl = templates.by_key(db)
    out = []
    for key in templates.KEYS:
        t = tpl.get(key)
        if t is None or (not t.active and key not in ("cover", "pricing", "acceptance", "independence")):
            continue
        if key == "independence" and not (p.independence or {}).get("flag"):
            continue
        body = t.body
        if key == "situation":
            filled = _situation(db, questionnaire)
            body = f"{body}\n\n{filled}".strip() if filled else body
        out.append({"key": key, "title": t.title, "body": body, "edited": False})
    return out


def _log_opp(db: Session, opp, summary: str, actor) -> None:
    try:
        from app.sales.service import log

        log(db, opp, "proposal", summary, _actor_id(actor))
    except Exception:  # noqa: BLE001  activity logging never stops the proposal
        pass


def move_stage(db: Session, opp, stage: str, actor=None) -> None:
    """Move the opportunity on (R2 owns the field): proposal from an early stage, negotiation, won. A stage this
    installation's opportunities don't have yet is skipped."""
    from app.sales import models as sm

    if stage not in getattr(sm, "STAGES", ()):
        return
    length = getattr(sm.Opportunity.__table__.c.stage.type, "length", None)
    if length and len(stage) > length:
        return
    if opp.stage in ("won", "lost") or opp.stage == stage:
        return
    if stage == "proposal" and opp.stage not in EARLY_STAGES:
        return
    old = opp.stage
    opp.stage = stage
    if stage == "won":
        opp.closed_at = utcnow()
    _log_opp(db, opp, f"Stage moved from {old} to {stage}.", actor)
    db.flush()


def _finish_create(db: Session, p: Proposal, opp, actor, how: str) -> Proposal:
    _touch(p, actor, f"drafted v{p.version} {how}")
    recalc(db, p)
    move_stage(db, opp, "negotiation" if p.version > 1 else "proposal", actor)
    _log_opp(db, opp, f"Proposal v{p.version} drafted {how}.", actor)
    audit.record(db, actor_id=_actor_id(actor), action="proposal.create", organization_id=getattr(actor, "organization_id", None), object_type="Proposal",
                 object_id=p.id, summary=f"Proposal v{p.version} for {_company(db, p.organization_id)} drafted {how}")
    return p


def create_from_estimate(db: Session, estimate, actor) -> Proposal:
    """R1's "Convert to proposal". Lines, edited prices, wording, discount and terms come across; the estimate stays."""
    from app.catalog.models import PackageTemplate
    from app.catalog.service import items_by_codes

    opp = _opportunity(db, estimate.opportunity_id)
    pkg = db.scalar(select(PackageTemplate).where(PackageTemplate.key == estimate.package)) if estimate.package else None
    pkg_codes = {ln["code"] for ln in (pkg.lines if pkg else [])}
    terms = {k: v for k, v in (estimate.terms or {}).items() if k in TERM_KEYS}
    terms["term_years"] = estimate.term or 1
    if estimate.data_region:
        terms["data_region"] = estimate.data_region
    p = _new(db, opp, actor, package=estimate.package, estimate_id=estimate.id, questionnaire=_questionnaire_for(db, opp.id),
             discount=estimate.discount_recurring_pct, terms=terms)
    items = items_by_codes(db, [ln["code"] for ln in estimate.lines or []])
    for i, ln in enumerate(estimate.lines or []):
        item = items.get(ln["code"])
        pl = _line_from_item(item, code=ln["code"], qty=ln.get("qty", 1), sort=i, source="package" if ln["code"] in pkg_codes else "manual",
                             override=ln.get("edited_price"), description=ln.get("description_override"), deliverables=ln.get("deliverables_override"))
        if item is not None:  # the prices the estimate was saved with; the builder offers the update when the list has moved
            for col, key in (("list_price", "list_price"), ("low", "low"), ("high", "high"), ("price_status", "price_status")):
                if key in ln:
                    setattr(pl, col, ln[key])
            if pl.override_price is not None and pl.override_price == pl.list_price:
                pl.override_price = None
        if pl.override_price is not None:
            pl.edited_by = ln.get("edited_by") if isinstance(ln.get("edited_by"), str) else _actor_id(actor)
            pl.edited_at = utcnow()
        pl.proposal_id = p.id
        db.add(pl)
    db.flush()
    return _finish_create(db, p, opp, actor, f"from estimate \"{estimate.name}\" v{estimate.version}")


def create_from_questionnaire(db: Session, questionnaire, actor) -> Proposal:
    """R3's "Lock and build proposal": one line per mapping-rule suggestion, with its reason; lines the rep removed on
    the review screen stay removed with the reason given there."""
    from app.catalog.service import items_by_codes
    from app.scoping import service as scoping

    opp = _opportunity(db, questionnaire.opportunity_id)
    suggested = scoping.suggest_lines(db, questionnaire.id)
    p = _new(db, opp, actor, questionnaire=questionnaire)
    items = items_by_codes(db, [s["code"] for s in suggested])
    now = utcnow()
    for i, s in enumerate(suggested):
        pl = _line_from_item(items.get(s["code"]), code=s["code"], qty=s.get("qty") or 1, sort=i, source="rule", rule_code=s.get("rule_code"),
                             reason=s.get("reason"), removed_reason=s.get("removed_reason"))
        if pl.removed_reason:
            pl.removed_by, pl.removed_at = _actor_id(actor), now
        pl.proposal_id = p.id
        db.add(pl)
    db.flush()
    return _finish_create(db, p, opp, actor, f"from scoping questionnaire v{getattr(questionnaire, 'version', '?')}")


def create_blank(db: Session, opp, actor, package: str | None = None) -> Proposal:
    p = _new(db, opp, actor, questionnaire=_questionnaire_for(db, opp.id))
    if package:
        apply_package(db, actor, p, package, _log=False)
    return _finish_create(db, p, opp, actor, "by hand")


# ---- editing a draft
def _qty(v) -> float:
    try:
        q = float(v)
    except (TypeError, ValueError) as exc:
        raise Invalid(errors=[{"field": "qty", "message": "Enter a quantity."}]) from exc
    if q <= 0 or q > 100000:
        raise Invalid(errors=[{"field": "qty", "message": "Quantity must be more than 0."}])
    return _r(q)


def _price(v):
    if v is None or v == "":
        return None
    try:
        n = float(str(v).replace(",", "").replace("$", ""))
    except ValueError as exc:
        raise Invalid(errors=[{"field": "override_price", "message": "Enter a price."}]) from exc
    if n < 0:
        raise Invalid(errors=[{"field": "override_price", "message": "Prices cannot be negative."}])
    return _r(n)


def _line(db: Session, p: Proposal, line_id: str) -> ProposalLine:
    ln = db.get(ProposalLine, line_id)
    if ln is None or ln.proposal_id != p.id:
        raise NotFound()
    return ln


def add_line(db: Session, actor, p: Proposal, code: str, qty=1) -> ProposalLine:
    from app.catalog.service import items_by_codes

    _require_editable(p)
    item = items_by_codes(db, [code]).get(code)
    if item is None:
        raise Invalid(errors=[{"field": "code", "message": f"{code} is not on the price list."}])
    if item.status != "active":
        raise Invalid(errors=[{"field": "code", "message": f"{code} is retired and can't be added to a new proposal."}])
    ls = lines(db, p)
    if len(ls) >= MAX_LINES:
        raise Invalid(errors=[{"field": "code", "message": f"A proposal holds up to {MAX_LINES} lines."}])
    existing = next((ln for ln in ls if ln.catalog_code == code), None)
    if existing is not None:
        if existing.removed_reason:
            raise Conflict(f"{code} is on this proposal as a removed line. Restore it instead.")
        raise Conflict(f"{code} is already on this proposal. Change its quantity instead.")
    ln = _line_from_item(item, code=code, qty=_qty(qty), sort=max([x.sort for x in ls], default=-1) + 1, source="manual")
    ln.proposal_id = p.id
    db.add(ln)
    db.flush()
    _touch(p, actor, "added a line")
    recalc(db, p)
    return ln


def update_line(db: Session, actor, p: Proposal, line_id: str, changes: dict) -> ProposalLine:
    _require_editable(p)
    ln = _line(db, p, line_id)
    if "qty" in changes:
        ln.qty = _qty(changes["qty"])
    if "override_price" in changes:
        if ln.sellable_status == "roadmap":
            raise Invalid(errors=[{"field": "override_price", "message": f"{ln.catalog_code} is a roadmap item: it is listed with no price (P-7)."}])
        price = _price(changes["override_price"])
        if price is not None and price == ln.list_price:
            price = None
        if price != ln.override_price:
            ln.override_price = price
            ln.edited_by, ln.edited_at = (_actor_id(actor), utcnow()) if price is not None else (None, None)
    if "deliverables_text" in changes:
        text = (changes["deliverables_text"] or "").replace("\r\n", "\n").strip()
        if len(text) > 8000:
            raise Invalid(errors=[{"field": "deliverables_text", "message": "Keep the wording under 8,000 characters."}])
        if not text:  # empty resets to the price list wording
            from app.catalog.service import items_by_codes

            item = items_by_codes(db, [ln.catalog_code]).get(ln.catalog_code)
            text = item.deliverables if item else ln.deliverables_text
            ln.deliverables_edited = False
        else:
            ln.deliverables_edited = True
        ln.deliverables_text = text
    if "description" in changes:
        ln.description = (changes["description"] or "").strip()[:1000] or None
    _touch(p, actor, "changed a line")
    recalc(db, p)
    return ln


def remove_line(db: Session, actor, p: Proposal, line_id: str, reason: str | None) -> None:
    """A rule-proposed line stays on the record with the reason; a line the rep added is simply taken off."""
    _require_editable(p)
    ln = _line(db, p, line_id)
    reason = " ".join((reason or "").split())
    if ln.source == "rule":
        if not reason:
            raise Invalid(errors=[{"field": "reason", "message": "Say why this suggested line is removed."}])
        if len(reason) > 500:
            raise Invalid(errors=[{"field": "reason", "message": "Keep the reason under 500 characters."}])
        ln.removed_reason, ln.removed_by, ln.removed_at = reason, _actor_id(actor), utcnow()
    else:
        db.delete(ln)
    db.flush()
    _touch(p, actor, "removed a line")
    recalc(db, p)


def restore_line(db: Session, actor, p: Proposal, line_id: str) -> None:
    _require_editable(p)
    ln = _line(db, p, line_id)
    ln.removed_reason = ln.removed_by = ln.removed_at = None
    _touch(p, actor, "restored a line")
    recalc(db, p)


def apply_package(db: Session, actor, p: Proposal, key: str, _log: bool = True) -> None:
    """Pick a package: its lines replace the lines that came from the previous package; rule and hand-added lines stay."""
    from app.catalog.models import PackageTemplate
    from app.catalog.service import items_by_codes

    _require_editable(p)
    pkg = db.scalar(select(PackageTemplate).where(PackageTemplate.key == key))
    if pkg is None:
        raise Invalid(errors=[{"field": "package", "message": "Choose a package from the list."}])
    ls = lines(db, p)
    for ln in ls:
        if ln.source == "package":
            db.delete(ln)
    db.flush()
    keep = {ln.catalog_code for ln in ls if ln.source != "package"}
    items = items_by_codes(db, [x["code"] for x in pkg.lines or []])
    sort = max([ln.sort for ln in ls if ln.source != "package"], default=-1)
    for x in pkg.lines or []:
        item = items.get(x["code"])
        if x["code"] in keep or item is None or item.status != "active":
            continue
        sort += 1
        ln = _line_from_item(item, code=x["code"], qty=x.get("qty") or 1, sort=sort, source="package")
        ln.proposal_id = p.id
        db.add(ln)
    p.package = key
    db.flush()
    _touch(p, actor, "picked a package")
    recalc(db, p)


def update_terms(db: Session, actor, p: Proposal, body: dict) -> Proposal:
    _require_editable(p)
    if "discount_recurring_pct" in body:
        try:
            d = float(body["discount_recurring_pct"] or 0)
        except (TypeError, ValueError) as exc:
            raise Invalid(errors=[{"field": "discount_recurring_pct", "message": "Enter a percentage."}]) from exc
        if not 0 <= d <= 100:
            raise Invalid(errors=[{"field": "discount_recurring_pct", "message": "Enter a percentage between 0 and 100."}])
        p.discount_recurring_pct = _r(d)
    if "valid_days" in body:
        try:
            days = int(body["valid_days"])
        except (TypeError, ValueError) as exc:
            raise Invalid(errors=[{"field": "valid_days", "message": "Enter a number of days."}]) from exc
        if not 1 <= days <= 180:
            raise Invalid(errors=[{"field": "valid_days", "message": "A proposal is valid for 1 to 180 days."}])
        p.valid_days = days
    if "title" in body:
        title = " ".join((body["title"] or "").split())
        if not title:
            raise Invalid(errors=[{"field": "title", "message": "Give the proposal a title."}])
        p.title = title[:200]
    if "terms" in body:
        p.terms = clean_terms({**(p.terms or {}), **(body["terms"] or {})})
    _touch(p, actor, "changed the discount or terms")
    recalc(db, p)
    return p


def clean_terms(t: dict) -> dict:
    out: dict = {}
    for k in TERM_KEYS:
        v = t.get(k)
        if v in (None, "", False):
            continue
        if k in ("payment_days", "term_years"):
            try:
                v = int(v)
            except (TypeError, ValueError) as exc:
                raise Invalid(errors=[{"field": k, "message": "Enter a whole number."}]) from exc
            if k == "payment_days" and not 0 <= v <= 180:
                raise Invalid(errors=[{"field": k, "message": "Payment terms are 0 to 180 days."}])
            if k == "term_years" and v not in (1, 2, 3):
                raise Invalid(errors=[{"field": k, "message": "Choose a term of 1, 2 or 3 years."}])
        elif k == "discount_one_time_pct":
            try:
                v = _r(float(v))
            except (TypeError, ValueError) as exc:
                raise Invalid(errors=[{"field": k, "message": "Enter a percentage."}]) from exc
            if not 0 <= v <= 100:
                raise Invalid(errors=[{"field": k, "message": "Enter a percentage between 0 and 100."}])
            if v == 0:
                continue
        elif k == "data_region":
            if v not in REGIONS:
                raise Invalid(errors=[{"field": k, "message": "Choose a data region from the list."}])
        elif k == "sla_credits" or k == "custom_liability":
            v = " ".join(str(v).split())[:500] if not isinstance(v, bool) else v
        else:
            v = " ".join(str(v).split())[:500]
        out[k] = v
    return out


def update_section(db: Session, actor, p: Proposal, key: str, body: str | None) -> dict:
    """The rep's wording for one section of this proposal; empty resets it to the template. The independence statement
    is fixed wording (I-4) and can't be edited per proposal."""
    _require_editable(p)
    if key == "independence":
        raise Conflict("The independence statement is fixed wording. The Futran Admin maintains it in Proposal templates.")
    sections = [dict(s) for s in p.sections or []]
    s = next((x for x in sections if x["key"] == key), None)
    if s is None:
        raise NotFound()
    text = (body or "").replace("\r\n", "\n").strip()
    if len(text) > 12000:
        raise Invalid(errors=[{"field": "body", "message": "Keep the section under 12,000 characters."}])
    if not text:
        fresh = {x["key"]: x for x in _starter_sections(db, p, _questionnaire_for(db, p.opportunity_id) if key == "situation" else None)}
        s["body"], s["edited"] = fresh.get(key, s)["body"], False
    else:
        s["body"], s["edited"] = text, True
    p.sections = sections
    _touch(p, actor, "changed a section")
    db.flush()
    return s


# ---- versions
def new_version(db: Session, actor, p: Proposal) -> Proposal:
    """The next version, copied from this one. Only from the latest version; a draft latest is returned as it is."""
    versions = thread(db, p.thread_id)
    last = versions[-1]
    if any(v.status == "accepted" for v in versions):
        raise Conflict("A version of this proposal was accepted. It can't have a new version.")
    if last.id != p.id:
        raise Conflict(f"Version {last.version} is the latest. Start from it.")
    if p.editable:
        return p
    n = Proposal(thread_id=p.thread_id, opportunity_id=p.opportunity_id, organization_id=p.organization_id, estimate_id=p.estimate_id,
                 questionnaire_id=p.questionnaire_id, questionnaire_version=p.questionnaire_version, catalog_version=p.catalog_version,
                 version=p.version + 1, previous_id=p.id, package=p.package, title=p.title, status="draft", valid_days=p.valid_days,
                 discount_recurring_pct=p.discount_recurring_pct, terms=dict(p.terms or {}), sections=[dict(s) for s in p.sections or []],
                 independence=dict(p.independence or {}), created_by=_actor_id(actor), updated_by=_actor_id(actor))
    flag, why = independence.flag_for(db, p.organization_id)
    n.independence = {"flag": flag, "reason": why}
    db.add(n)
    db.flush()
    _touch(n, actor, f"started v{n.version} from v{p.version}")
    keys = [s["key"] for s in n.sections]
    if flag and "independence" not in keys:
        tpl = templates.by_key(db)["independence"]
        n.sections = n.sections[:-1] + [{"key": "independence", "title": tpl.title, "body": tpl.body, "edited": False}] + n.sections[-1:]
    elif not flag and "independence" in keys:
        n.sections = [s for s in n.sections if s["key"] != "independence"]
    cols = [c.key for c in ProposalLine.__table__.columns if c.key not in ("id", "proposal_id")]
    for ln in lines(db, p):
        db.add(ProposalLine(proposal_id=n.id, **{k: getattr(ln, k) for k in cols}))
    db.flush()
    from app.sales.models import Opportunity

    opp = db.get(Opportunity, p.opportunity_id)
    if opp is not None:
        move_stage(db, opp, "negotiation", actor)
        _log_opp(db, opp, f"Proposal v{n.version} started from v{p.version}.", actor)
    recalc(db, n)
    return n


def diff(db: Session, a: Proposal, b: Proposal) -> dict:
    """What changed from version a to version b: lines (added, removed, quantity, unit price, wording), discount and terms."""
    la = {ln.catalog_code: ln for ln in lines(db, a)}
    lb = {ln.catalog_code: ln for ln in lines(db, b)}
    out_lines = []
    for code in list(la) + [c for c in lb if c not in la]:
        x, y = la.get(code), lb.get(code)
        live_x = x is not None and not x.removed_reason
        live_y = y is not None and not y.removed_reason
        name = (y or x).name
        if live_y and not live_x:
            out_lines.append({"code": code, "name": name, "kind": "added", "changes": [], "value": y.line_value})
        elif live_x and not live_y:
            out_lines.append({"code": code, "name": name, "kind": "removed", "changes": [], "value": x.line_value,
                              "reason": y.removed_reason if y is not None else None})
        elif live_x and live_y:
            ch = []
            if x.qty != y.qty:
                ch.append({"field": "qty", "from": _r(x.qty), "to": _r(y.qty)})
            if x.unit_price_used != y.unit_price_used:
                ch.append({"field": "unit price", "from": x.unit_price_used, "to": y.unit_price_used})
            if (x.deliverables_text or "") != (y.deliverables_text or ""):
                ch.append({"field": "wording", "from": None, "to": None})
            if ch:
                out_lines.append({"code": code, "name": name, "kind": "changed", "changes": ch, "value": y.line_value})
    terms = []
    if (a.discount_recurring_pct or 0) != (b.discount_recurring_pct or 0):
        terms.append({"field": "discount on recurring", "from": _r(a.discount_recurring_pct or 0), "to": _r(b.discount_recurring_pct or 0)})
    if a.valid_days != b.valid_days:
        terms.append({"field": "valid for (days)", "from": a.valid_days, "to": b.valid_days})
    ta, tb = a.terms or {}, b.terms or {}
    for k in TERM_KEYS:
        if ta.get(k) != tb.get(k):
            terms.append({"field": k.replace("_", " ").replace("pct", "%"), "from": ta.get(k), "to": tb.get(k)})
    totals = {k: {"from": (a.totals or {}).get(k), "to": (b.totals or {}).get(k)} for k in ("one_time", "recurring_y1", "discount", "y1_total", "arr")
              if (a.totals or {}).get(k) != (b.totals or {}).get(k)}
    return {"from": a.version, "to": b.version, "lines": out_lines, "terms": terms, "totals": totals}


def touched_by(db: Session, p: Proposal) -> set[str]:
    """Everyone who worked on any version of this proposal (created, edited anything, sent it) and the opportunity
    owner: none of them can approve it."""
    from app.sales.models import Opportunity

    from app.proposals.models import ProposalEvent

    versions = thread(db, p.thread_id) if p.thread_id else [p]
    ids = {v.created_by for v in versions} | {v.updated_by for v in versions} | {v.sent_by for v in versions}
    vids = [v.id for v in versions]
    ids |= set(db.scalars(select(ProposalLine.edited_by).where(ProposalLine.proposal_id.in_(vids))))
    ids |= set(db.scalars(select(ProposalLine.removed_by).where(ProposalLine.proposal_id.in_(vids))))
    ids |= set(db.scalars(select(ProposalEvent.by_id).where(ProposalEvent.proposal_id.in_(vids), ProposalEvent.kind == TOUCH)))
    opp = db.get(Opportunity, p.opportunity_id)
    if opp is not None:
        ids.add(opp.owner_id)
    return {i for i in ids if i}


# ---- the price list moved on since the draft
PRICE_FIELDS = (("list_price", "list_price"), ("low", "low"), ("high", "high"), ("price_status", "price_status"), ("sellable_status", "sellable_status"))


def price_changes(db: Session, p: Proposal) -> list[dict]:
    """Lines whose catalog list price, range or status changed since they were put on this proposal."""
    from app.catalog.service import items_by_codes

    ls = [ln for ln in lines(db, p) if ln.on_catalog and not ln.removed_reason]
    items = items_by_codes(db, [ln.catalog_code for ln in ls])
    out = []
    for ln in ls:
        it = items.get(ln.catalog_code)
        if it is None:
            continue
        diffs = {col: {"from": getattr(ln, col), "to": getattr(it, attr)} for col, attr in PRICE_FIELDS if getattr(ln, col) != getattr(it, attr)}
        if diffs:
            out.append({"code": ln.catalog_code, "name": ln.name, "changes": diffs, "edited": ln.override_price is not None})
    return out


def update_to_current_prices(db: Session, actor, p: Proposal) -> list[dict]:
    """Bring every line's list price, range and statuses up to the current price list. Edited prices stay edited."""
    from app.catalog.service import current_version, items_by_codes

    _require_editable(p)
    changed = price_changes(db, p)
    if not changed:
        return []
    items = items_by_codes(db, [c["code"] for c in changed])
    for ln in lines(db, p):
        it = items.get(ln.catalog_code)
        if it is None or ln.removed_reason or not ln.on_catalog:
            continue
        for col, attr in PRICE_FIELDS:
            setattr(ln, col, getattr(it, attr))
        if ln.override_price is not None and ln.override_price == ln.list_price:
            ln.override_price = ln.edited_by = ln.edited_at = None
    p.catalog_version = current_version(db)
    _touch(p, actor, f"updated {', '.join(c['code'] for c in changed)} to current list prices")
    recalc(db, p)
    return changed


def refresh_independence(db: Session, p: Proposal) -> bool:
    """Recompute the independence flag on a draft (on opening the builder and at send): a prospect that became an audit
    client mid-draft gets rules I-1 to I-4 and the independence statement. Returns True when it changed."""
    if not p.editable:
        return False
    flag, why = independence.flag_for(db, p.organization_id)
    old = p.independence or {}
    if bool(old.get("flag")) == flag and old.get("reason") == why:
        return False
    p.independence = {"flag": flag, "reason": why}
    keys = [s["key"] for s in p.sections or []]
    if flag and "independence" not in keys:
        tpl = templates.by_key(db)["independence"]
        secs = [dict(s) for s in p.sections or []]
        at = keys.index("acceptance") if "acceptance" in keys else len(secs)
        p.sections = secs[:at] + [{"key": "independence", "title": tpl.title, "body": tpl.body, "edited": False}] + secs[at:]
    elif not flag and "independence" in keys:
        p.sections = [s for s in p.sections if s["key"] != "independence"]
    db.flush()
    refresh_status(db, p)
    return True


def stamp(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
