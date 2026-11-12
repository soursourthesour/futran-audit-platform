"""Mapping rules as stored data (SM-14 Mapping rules tab, `/staff/admin/catalog/rules`).

- Seeded once from `rules.SEED` (spec §4.5).
- The Futran Admin edits a rule or adds one. An edit to an approved rule waits in `pending` and the approved definition
  keeps running until the Pricing Approver approves it; a new rule runs only once approved. Nobody approves their own edit.
- A rule whose line code is not in the catalog, or points to a retired item, is flagged for repair; it is never dropped.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.scoping import bridge, rules
from app.scoping.models import MappingRule

FIELDS = ("inputs", "line_code", "qty_formula", "reason_template", "note", "active")  # every one goes through approval


def ensure_seed(db: Session) -> None:
    if db.scalar(select(MappingRule.id).limit(1)) is not None:
        return
    for d in rules.seed_definitions():
        db.add(MappingRule(code=d["code"], line_code=d["line_code"], inputs=d["inputs"], qty_formula=d["qty_formula"],
                           reason_template=d["reason_template"], note=d.get("note"), order=d["order"], active=True, status="approved"))
    db.flush()


def all_rules(db: Session) -> list[MappingRule]:
    ensure_seed(db)
    return list(db.scalars(select(MappingRule).order_by(MappingRule.order, MappingRule.code)))


def as_definition(r: MappingRule) -> dict:
    return {"code": r.code, "line_code": r.line_code, "inputs": r.inputs or {}, "qty_formula": r.qty_formula or {}, "reason_template": r.reason_template,
            "order": r.order, "active": r.active, "status": r.status, "note": r.note}


def live_definitions(db: Session) -> list[dict]:
    return [as_definition(r) for r in all_rules(db)]


def get(db: Session, code: str) -> MappingRule:
    ensure_seed(db)
    r = db.scalar(select(MappingRule).where(MappingRule.code == code))
    if r is None:
        raise NotFound("That mapping rule does not exist.")
    return r


def _validate(data: dict, types: dict[str, str], base: dict | None = None) -> dict:
    """The changes in `data`, checked. `types` maps each bank question code to its answer type; `base` is the rule the
    changes apply to, so the whole rule is checked as it would run."""
    out = {k: data[k] for k in FIELDS if k in data and data[k] is not None}
    errors = []
    if "line_code" in out:
        out["line_code"] = str(out["line_code"]).strip()
        if not out["line_code"]:
            errors.append({"field": "line_code", "message": "Enter the price list code the rule proposes."})
    if "reason_template" in out and not str(out["reason_template"]).strip():
        errors.append({"field": "reason_template", "message": "Say why the line is proposed, for the rep to read."})
    if "active" in out and not isinstance(out["active"], bool):
        errors.append({"field": "active", "message": "Switch the rule on or off."})
    for key in ("inputs", "qty_formula"):
        if key in out and not isinstance(out[key], dict):
            errors.append({"field": key, "message": "This must be a JSON object."})
    if not errors:
        whole = {**(base or {}), **out}
        for problem in rules.validate(whole, types):
            errors.append({"field": "inputs", "message": problem})
    if errors:
        raise Invalid(errors=errors)
    return out


def _live(r: MappingRule) -> dict:
    return {k: getattr(r, k) for k in FIELDS}


def propose_edit(db: Session, code: str, data: dict, actor_id: str, types: dict[str, str]) -> MappingRule:
    """An edit (including switching the rule on or off) waits for the Pricing Approver. A second edit before approval
    adds to the one already waiting."""
    r = get(db, code)
    base = {**_live(r), **(r.pending or {})}
    changes = _validate(data, types, base)
    if not changes:
        raise Invalid(errors=[{"field": "inputs", "message": "Nothing to change."}])
    if r.status == "pending":  # a new rule not yet approved: edit it in place
        for k, v in changes.items():
            setattr(r, k, v)
    else:
        r.pending = {**base, **changes}
    r.pending_by, r.pending_at = actor_id, utcnow()
    db.flush()
    return r


def add(db: Session, data: dict, actor_id: str, types: dict[str, str]) -> MappingRule:
    import re

    code = str(data.get("code") or "").strip().upper()
    if not re.fullmatch(r"MR-\d{2}[a-z]?", code, flags=re.I):
        raise Invalid(errors=[{"field": "code", "message": "Use a code like MR-20 or MR-20a."}])
    code = code[:5] + code[5:].lower()
    if db.scalar(select(MappingRule.id).where(MappingRule.code == code)):
        raise Invalid(errors=[{"field": "code", "message": "That rule code is already used."}])
    fields = _validate(data, types, {"inputs": {"all": []}, "qty_formula": {"const": 1}})
    for need in ("line_code", "reason_template"):
        if need not in fields:
            raise Invalid(errors=[{"field": need, "message": "Enter the line code and the reason."}])
    order = max((x.order for x in all_rules(db)), default=0) + 10
    r = MappingRule(code=code, status="pending", active=True, order=order, created_by=actor_id, pending_by=actor_id, pending_at=utcnow(),
                    **{"inputs": {"all": []}, "qty_formula": {"const": 1}, **fields})
    db.add(r)
    db.flush()
    return r


def approve(db: Session, code: str, actor_id: str) -> MappingRule:
    r = get(db, code)
    if r.status != "pending" and not r.pending:
        raise Conflict("Nothing on this rule is waiting for approval.")
    if r.pending_by == actor_id:
        raise Forbidden("You made this change, so someone else must approve it.")
    if r.pending:
        for k in FIELDS:
            if k in r.pending:
                setattr(r, k, r.pending[k])
    r.status, r.pending, r.approved_by, r.approved_at = "approved", None, actor_id, utcnow()
    r.catalog_version = bridge.catalog_version(db)
    db.flush()
    return r


def reject(db: Session, code: str, actor_id: str) -> MappingRule:
    r = get(db, code)
    if r.status == "pending":
        r.status = "rejected"
    elif r.pending:
        r.pending = None
    else:
        raise Conflict("Nothing on this rule is waiting for approval.")
    r.pending_by = r.pending_at = None
    db.flush()
    return r


def set_active(db: Session, code: str, active: bool, actor_id: str, types: dict[str, str]) -> MappingRule:
    """Switching a rule on or off is a rule change: it waits for approval like any other edit."""
    return propose_edit(db, code, {"active": bool(active)}, actor_id, types)


def flags(db: Session, rows: list[MappingRule] | None = None) -> dict[str, str]:
    """{rule code: why it needs repair} for active rules whose line is missing from the catalog or retired, the same
    test as the price list's `catalog.service.rule_flags` (the "to repair" count on its tabs). Empty when the catalog
    is not installed (nothing to check against yet)."""
    rows = rows if rows is not None else all_rules(db)
    codes = {r.line_code for r in rows} | {(r.pending or {}).get("line_code") for r in rows if r.pending}
    codes.discard(None)
    items = bridge.catalog_items(db, sorted(codes))
    if items is None:
        return {}
    out = {}
    for r in rows:
        if not r.active:  # as the price list's own count (catalog.service.rule_flags): switched-off rules need no repair
            continue
        item = items.get(r.line_code)
        if item is None:
            out[r.code] = f"{r.line_code} is not in the price list. Add it there, or change the rule."
        elif bridge.is_retired(item):
            out[r.code] = f"{r.line_code} is retired in the price list. Change the rule to a current item."
        pending_code = (r.pending or {}).get("line_code")
        if pending_code and pending_code != r.line_code:
            p_item = items.get(pending_code)
            if p_item is None or bridge.is_retired(p_item):
                note = f"The edit waiting for approval points to {pending_code}, which is {'retired in' if p_item is not None else 'not in'} the price list."
                out[r.code] = f"{out[r.code]} {note}" if r.code in out else note
    return out


def run_flags(db: Session, rows: list[MappingRule] | None = None) -> dict[str, str]:
    """{rule code: message} for rules (approved, or an edit waiting) that cannot run on a filled-in or an empty
    questionnaire, e.g. one saved before rules were checked. Scoping skips them; this tab shows them for repair."""
    from app.scoping import bank

    rows = rows if rows is not None else all_rules(db)
    qs = {q.code: (q.type, [o.get("value") for o in (q.options or [])]) for q in bank.questions(db, include_inactive=True)}
    out = {}
    for r in rows:
        for d in (as_definition(r), {**as_definition(r), **(r.pending or {})} if r.pending else None):
            if d is None:
                continue
            msg = rules.probe(d, qs)
            if msg:
                out[r.code] = msg.replace(". Ask the Futran Admin to repair it on the Mapping rules tab.", ". Repair its conditions or quantity.")
                break
    return out


def rule_out(r: MappingRule, flag: str | None, names: dict) -> dict:
    return {"code": r.code, "line_code": r.line_code, "inputs": r.inputs, "qty_formula": r.qty_formula, "reason_template": r.reason_template,
            "note": r.note, "order": r.order, "active": r.active, "status": r.status, "pending": r.pending,
            "pending_by_name": names.get(r.pending_by), "pending_at": r.pending_at.isoformat() if r.pending_at else None,
            "approved_by_name": names.get(r.approved_by) or ("Seeded from spec §4.5" if r.status == "approved" and not r.approved_by else None),
            "approved_at": r.approved_at.isoformat() if r.approved_at else None, "catalog_version": r.catalog_version,
            "questions": sorted(rules.question_codes(as_definition(r))), "flag": flag}
