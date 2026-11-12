"""Scoping questionnaires (spec §4.4): start, answer (rep and client), conflicts, suggested lines, estimate, lock.

Shared names (plan): `suggest_lines(db, questionnaire_id)` and `lock(db, questionnaire_id, actor)`.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.scoping import bank, bridge, rulebook, rules
from app.scoping.models import CONFIDENCES, ScopingAnswer, ScopingQuestionnaire
from app.scoping.rules import Ans

OPEN_STAGES = ("new", "qualified", "contacted")  # stages a started questionnaire moves on to `scoping`
MODE_LABELS = {"recorded": "recorded on the call", "sent": "sent to the client", "hybrid": "recorded on the call and sent to the client"}


def _actor_id(actor) -> str | None:
    return getattr(actor, "id", None)


def _log(db: Session, opp, summary: str, by_id: str | None, kind: str = "note") -> None:
    try:
        from app.sales.service import log

        log(db, opp, kind, summary, by_id)
    except Exception:  # noqa: BLE001 - the activity timeline is a courtesy; R2 may reshape it
        pass


def current(db: Session, opportunity_id: str) -> ScopingQuestionnaire | None:
    return db.scalar(select(ScopingQuestionnaire).where(ScopingQuestionnaire.opportunity_id == opportunity_id)
                     .order_by(ScopingQuestionnaire.version.desc()).limit(1))


def versions(db: Session, opportunity_id: str) -> list[ScopingQuestionnaire]:
    return list(db.scalars(select(ScopingQuestionnaire).where(ScopingQuestionnaire.opportunity_id == opportunity_id).order_by(ScopingQuestionnaire.version)))


def get(db: Session, questionnaire_id: str) -> ScopingQuestionnaire:
    q = db.get(ScopingQuestionnaire, questionnaire_id)
    if q is None:
        raise NotFound()
    return q


def move_to_scoping(db: Session, opp, actor_id: str | None) -> None:
    """Spec §4.2: the opportunity is in `scoping` while a questionnaire is in progress."""
    if opp.stage in OPEN_STAGES:
        opp.stage = "scoping"
        _log(db, opp, "Stage moved to Scoping.", actor_id, kind="stage")


def start(db: Session, opp, actor, mode: str = "recorded") -> ScopingQuestionnaire:
    q = current(db, opp.id)
    if q is not None:
        return q
    v = bank.ensure_seed(db)
    rulebook.ensure_seed(db)
    q = ScopingQuestionnaire(prospect_id=opp.organization_id, opportunity_id=opp.id, bank_version=v, version=1, mode=mode, status="draft",
                             removed_lines=[], created_by=_actor_id(actor))
    db.add(q)
    db.flush()
    _log(db, opp, f"Scoping questionnaire started ({MODE_LABELS.get(mode, mode)}).", _actor_id(actor))
    move_to_scoping(db, opp, _actor_id(actor))
    db.flush()
    return q


# ---- answers
def _rows(db: Session, q: ScopingQuestionnaire) -> dict[str, dict[str, ScopingAnswer]]:
    out: dict[str, dict[str, ScopingAnswer]] = {}
    for a in db.scalars(select(ScopingAnswer).where(ScopingAnswer.questionnaire_id == q.id)):
        out.setdefault(a.question_code, {})[a.slot] = a
    return out


def _same(a, b) -> bool:
    def norm(v):
        if isinstance(v, list):
            return sorted(str(x) for x in v)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return v
    return norm(a) == norm(b)


def _in_conflict(rep: ScopingAnswer, client: ScopingAnswer) -> bool:
    if rep.confidence == "unknown" and client.confidence == "unknown":
        return False
    if rep.confidence == "unknown" or client.confidence == "unknown":
        differs = True
    else:
        differs = not _same(rep.value, client.value)
    return differs and not (rep.resolved_at is not None and rep.resolved_at >= client.answered_at)


def _ans(a: ScopingAnswer) -> Ans:
    return Ans(a.value, a.confidence, a.source)


def _sum(question, parts_from: dict[str, Ans]) -> Ans | None:
    parts = [parts_from[c] for c in question.sum_of if c in parts_from and parts_from[c].known]
    if not parts:
        return None
    total = sum(float(p.value) for p in parts if isinstance(p.value, (int, float)))
    conf = "estimate" if any(p.confidence == "estimate" for p in parts) or len(parts) < len(question.sum_of) else "confirmed"
    return Ans(int(total) if float(total).is_integer() else total, conf, "derived")


def _rep_totals(qs: dict, rows: dict) -> dict[str, Ans]:
    """Totals the rep has not entered but worked out from the counts they recorded: these count as the rep's answer."""
    rep_side = {code: _ans(slots["rep"]) for code, slots in rows.items() if "rep" in slots}
    out = {}
    for code, question in qs.items():
        if question.type == "total" and question.sum_of and code not in rep_side:
            a = _sum(question, rep_side)
            if a is not None:
                out[code] = a
    return out


def effective_answers(db: Session, q: ScopingQuestionnaire) -> dict[str, Ans]:
    """The answer each question counts as: the rep's when there is one (a conflicting client answer waits on SM-08),
    else the client's. A total with no answer of its own is the sum of its parts; worked out from the rep's counts, it
    is the rep's answer and a different client total is a conflict."""
    qs = bank.by_code(db, q.bank_version)
    rows = _rows(db, q)
    out: dict[str, Ans] = dict(_rep_totals(qs, rows))
    for code, slots in rows.items():
        if "rep" in slots:
            out[code] = _ans(slots["rep"])
        elif "client" in slots and code not in out and not (qs.get(code) and qs[code].internal_only):
            out[code] = _ans(slots["client"])
    for code, question in qs.items():
        if question.type == "total" and code not in out and question.sum_of:
            a = _sum(question, out)
            if a is not None:
                out[code] = a
    return out


def _check_value(question, value):
    """Normalise one value by question type; raises Invalid with a message for the field."""
    bad = Invalid(errors=[{"field": question.code, "message": "Enter a whole number of 0 or more, or mark it unknown."}])
    if value is None or value == "":
        return None
    t = question.type
    if t in ("count", "total"):
        try:
            n = float(value)
        except (TypeError, ValueError):
            raise bad from None
        if n < 0 or n > 10_000_000 or not n.is_integer():
            raise bad
        return int(n)
    allowed = {o["value"] for o in question.options or []}
    if t in ("single", "yes_no"):
        if str(value) not in allowed:
            raise Invalid(errors=[{"field": question.code, "message": "Choose one of the options."}])
        return str(value)
    if t == "multi":
        if not isinstance(value, list) or any(str(v) not in allowed for v in value):
            raise Invalid(errors=[{"field": question.code, "message": "Tick options from the list."}])
        return list(dict.fromkeys(str(v) for v in value))
    text = str(value).strip()
    if len(text) > 2000:
        raise Invalid(errors=[{"field": question.code, "message": "Keep this under 2,000 characters."}])
    return text or None


def _require_open(q: ScopingQuestionnaire) -> None:
    if q.status == "locked":
        raise Conflict("This questionnaire version is locked. Unlock it to make a new version before changing answers.")


def _upsert(db: Session, q: ScopingQuestionnaire, rows: dict, question, slot: str, item: dict, *, source: str, by: str | None, by_name: str | None) -> None:
    confidence = item.get("confidence") or "confirmed"
    if confidence not in CONFIDENCES:
        raise Invalid(errors=[{"field": question.code, "message": "Choose confirmed, estimate or unknown."}])
    value = None if confidence == "unknown" else _check_value(question, item.get("value"))
    note = (str(item.get("note") or "").strip() or None)
    if note and len(note) > 2000:
        raise Invalid(errors=[{"field": question.code, "message": "Keep the note under 2,000 characters."}])
    existing = rows.get(question.code, {}).get(slot)
    if value is None and confidence != "unknown" and not note:
        if existing is not None:  # cleared
            db.delete(existing)
            rows[question.code].pop(slot, None)
        return
    now = utcnow()
    if existing is None:
        existing = ScopingAnswer(questionnaire_id=q.id, question_code=question.code, slot=slot)
        db.add(existing)
        rows.setdefault(question.code, {})[slot] = existing
    elif slot == "rep" and existing.source == "rep_confirmed_client" and _same(existing.value, value) and existing.confidence == confidence:
        source = existing.source  # unchanged confirmation stays a confirmation
    if existing.value == value and existing.confidence == confidence and existing.note == note and existing.source == source:
        return
    existing.value, existing.confidence, existing.note, existing.source = value, confidence, note, source
    existing.answered_by, existing.answered_by_name, existing.answered_at = by, by_name, now


def save_answers(db: Session, q: ScopingQuestionnaire, items: list[dict], *, actor) -> dict:
    """Rep answers (SM-05 autosave). Each item: {code, value, confidence, note}."""
    _require_open(q)
    qs = bank.by_code(db, q.bank_version)
    rows = _rows(db, q)
    for item in items or []:
        question = qs.get(str(item.get("code") or ""))
        if question is None:
            raise Invalid(errors=[{"field": str(item.get("code")), "message": "That question is not in this questionnaire."}])
        _upsert(db, q, rows, question, "rep", item, source="rep", by=_actor_id(actor), by_name=getattr(actor, "name", None))
    if q.mode == "sent" and items:
        q.mode = "hybrid"
    q.updated_at = utcnow()
    db.flush()
    return {"saved": len(items or []), "at": q.updated_at.isoformat()}


def save_client_answers(db: Session, q: ScopingQuestionnaire, items: list[dict], *, send_id: str, name: str, allowed: set[str] | None = None) -> int:
    """Client answers from a personal link. Only the questions on that link, never an internal-only one."""
    _require_open(q)
    qs = bank.by_code(db, q.bank_version)
    rows = _rows(db, q)
    n = 0
    for item in items or []:
        code = str(item.get("code") or "")
        question = qs.get(code)
        if question is None or question.internal_only or (allowed is not None and code not in allowed):
            continue
        _upsert(db, q, rows, question, "client", item, source="client", by=send_id, by_name=name)
        n += 1
    if q.status in ("draft", "sent"):
        q.status = "client_in_progress"
    q.updated_at = utcnow()
    db.flush()
    return n


def conflicts(db: Session, q: ScopingQuestionnaire) -> list[dict]:
    qs = bank.by_code(db, q.bank_version)
    labels = _labels(qs)
    rows = _rows(db, q)
    totals = _rep_totals(qs, rows)
    out = []
    for code, slots in rows.items():
        rep, client = slots.get("rep"), slots.get("client")
        if client is None:
            continue
        if rep is None and code in totals:  # the rep's worked-out total against the client's
            t = totals[code]
            if _same(t.value, client.value) and client.confidence != "unknown":
                continue
            rep_out = _answer_out(t, labels, code)
        elif rep is None or not _in_conflict(rep, client):
            continue
        else:
            rep_out = _answer_out(rep, labels)
        question = qs.get(code)
        out.append({"code": code, "label": question.label if question else code,
                    "rep": rep_out, "client": _answer_out(client, labels), "effect": _effect(db, q, code, client)})
    order = {c.code: i for i, c in enumerate(bank.questions(db, q.bank_version, include_inactive=True))}
    return sorted(out, key=lambda c: order.get(c["code"], 999))


def resolve(db: Session, q: ScopingQuestionnaire, code: str, keep: str, value, actor) -> None:
    """Settle a conflict (SM-08): keep the rep's value, take the client's, or enter another."""
    _require_open(q)
    rows = _rows(db, q)
    slots = rows.get(code, {})
    rep, client = slots.get("rep"), slots.get("client")
    qs = bank.by_code(db, q.bank_version)
    question = qs.get(code)
    if rep is None and client is not None and code in _rep_totals(qs, rows):  # settle a worked-out total: it becomes the rep's answer
        t = _rep_totals(qs, rows)[code]
        rep = ScopingAnswer(questionnaire_id=q.id, question_code=code, slot="rep", value=t.value, confidence=t.confidence, source="rep")
        db.add(rep)
    if rep is None or client is None:
        raise NotFound("There is no conflict on that question.")
    now = utcnow()
    if keep == "client":
        rep.value, rep.confidence, rep.source = client.value, client.confidence, "rep_confirmed_client"
    elif keep == "other":
        rep.value, rep.confidence, rep.source = _check_value(question, value), "confirmed", "rep"
        if rep.value is None:
            raise Invalid(errors=[{"field": "value", "message": "Enter the value to keep."}])
    elif keep != "rep":
        raise Invalid(errors=[{"field": "keep", "message": "Choose rep, client or other."}])
    rep.resolved_at, rep.resolved_by = now, _actor_id(actor)
    rep.answered_by, rep.answered_by_name, rep.answered_at = _actor_id(actor), getattr(actor, "name", None), now
    db.flush()


# ---- suggested lines
def _labels(qs: dict) -> dict:
    return {code: {o["value"]: o["label"] for o in (question.options or [])} for code, question in qs.items()}


def _answer_out(a: ScopingAnswer | Ans | None, labels: dict, code: str | None = None) -> dict | None:
    if a is None:
        return None
    code = code or getattr(a, "question_code", None)
    ans = a if isinstance(a, Ans) else _ans(a)
    out = {"value": ans.value, "confidence": ans.confidence, "source": ans.source, "display": rules.show(code or "", ans, labels)}
    if isinstance(a, ScopingAnswer):
        out.update({"note": a.note, "by": a.answered_by_name, "at": a.answered_at.isoformat() if a.answered_at else None})
    return out


def _lines_for(db: Session, q: ScopingQuestionnaire, answers: dict[str, Ans], errors: list | None = None) -> list[dict]:
    defs = rulebook.live_definitions(db)
    qs = bank.by_code(db, q.bank_version)
    tier_codes = set()
    for d in defs:
        try:
            tier_codes |= {t[0] for t in (d.get("qty_formula") or {}).get("excess_included", {}).get("tiers", [])}
        except (AttributeError, TypeError, IndexError):
            pass  # a malformed rule; evaluate() skips and reports it
    catalog = bridge.catalog_items(db, sorted(tier_codes)) if tier_codes else None
    return rules.evaluate(defs, answers, labels=_labels(qs), catalog=catalog, errors=errors)


def rule_errors(db: Session, q: ScopingQuestionnaire) -> list[dict]:
    """Rules that could not be applied to this questionnaire's answers: [{rule_code, line_code, message}]. Their lines
    are left out; the rep is told, and the Mapping rules tab flags them for repair."""
    errors: list = []
    _lines_for(db, q, effective_answers(db, q), errors)
    return errors


def suggest_lines(db: Session, questionnaire_id: str) -> list[dict]:
    """The lines the mapping rules propose for this questionnaire version: [{code, qty, reason, rule_code,
    removed_reason}]. A line the rep removed stays in the list with the reason they gave (None when not removed), so the
    proposal builder can keep it as a removed rule line."""
    q = get(db, questionnaire_id)
    removed = {r["code"]: r for r in q.removed_lines or []}
    out = []
    for line in _lines_for(db, q, effective_answers(db, q)):
        r = removed.get(line["code"])
        out.append({**line, "removed_reason": r["reason"] if r else None})
    return out


def remove_line(db: Session, q: ScopingQuestionnaire, code: str, reason: str, actor) -> None:
    _require_open(q)
    reason = (reason or "").strip()
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why this suggested line is removed."}])
    if len(reason) > 500:
        raise Invalid(errors=[{"field": "reason", "message": "Keep the reason under 500 characters."}])
    line = next((x for x in suggest_lines(db, q.id) if x["code"] == code), None)
    if line is None:
        raise NotFound("That line is not suggested for this questionnaire.")
    kept = [r for r in q.removed_lines or [] if r["code"] != code]
    q.removed_lines = kept + [{"code": code, "rule_code": line["rule_code"], "reason": reason, "by": _actor_id(actor), "at": utcnow().isoformat()}]
    db.flush()


def restore_line(db: Session, q: ScopingQuestionnaire, code: str, actor) -> None:
    _require_open(q)
    q.removed_lines = [r for r in q.removed_lines or [] if r["code"] != code]
    db.flush()


def _effect(db: Session, q: ScopingQuestionnaire, code: str, alt: ScopingAnswer | None) -> str:
    """What changes in the suggested lines if `alt` is used for `code` instead of the current answer."""
    answers = effective_answers(db, q)
    before = {x["code"]: x["qty"] for x in _lines_for(db, q, answers)}
    if alt is not None:
        answers = {**answers, code: _ans(alt)}
    after = {x["code"]: x["qty"] for x in _lines_for(db, q, answers)}
    parts = []
    gone = [c for c in before if c not in after]
    new = [c for c in after if c not in before]
    if len(gone) == 1 and len(new) == 1:
        parts.append(f"{gone[0]} → {new[0]}")
    else:
        parts += [f"{c} removed" for c in gone] + [f"{c} added" for c in new]
    parts += [f"{c} × {before[c]} → × {after[c]}" for c in before if c in after and before[c] != after[c]]
    return "; ".join(parts) or "No change to the suggested lines"


def assumptions(db: Session, q: ScopingQuestionnaire) -> list[dict]:
    """Proposal assumptions from unknown answers (spec §4.4 rule 1): [{code, text}]."""
    qs = bank.by_code(db, q.bank_version)
    out = []
    for code, a in effective_answers(db, q).items():
        question = qs.get(code)
        if a.confidence == "unknown" and question is not None and question.unknown_assumption:
            out.append({"code": code, "text": question.unknown_assumption})
    order = {c.code: i for i, c in enumerate(bank.questions(db, q.bank_version, include_inactive=True))}
    return sorted(out, key=lambda x: order.get(x["code"], 999))


def unknowns(db: Session, q: ScopingQuestionnaire) -> list[dict]:
    qs = bank.by_code(db, q.bank_version)
    defs = rulebook.live_definitions(db)
    out = []
    for code, a in effective_answers(db, q).items():
        if a.confidence != "unknown":
            continue
        question = qs.get(code)
        reads = sorted({d["line_code"] for d in defs if code in rules.question_codes(d)})
        effect = f"Read by the rules for {', '.join(reads)}" if reads else "Not used by any mapping rule"
        out.append({"code": code, "label": question.label if question else code, "effect": effect,
                    "assumption": question.unknown_assumption if question else None})
    order = {c.code: i for i, c in enumerate(bank.questions(db, q.bank_version, include_inactive=True))}
    return sorted(out, key=lambda x: order.get(x["code"], 999))


def estimate(db: Session, q: ScopingQuestionnaire, lines: list[dict] | None = None) -> dict:
    """Running estimate at catalog list prices (SM-05). Removed lines and % items are left out."""
    lines = [x for x in (lines if lines is not None else suggest_lines(db, q.id)) if not x.get("removed_reason")]
    items = bridge.catalog_items(db, [x["code"] for x in lines])
    if items is None:
        return {"available": False, "one_time": None, "recurring_y1": None, "missing": [], "percent": [], "catalog_version": None,
                "note": "The price list is not installed yet, so there is no running estimate."}
    one_time = recurring = 0.0
    missing, percent = [], []
    for x in lines:
        item = items.get(x["code"])
        price = bridge.list_price(item) if item is not None else None
        if item is None or price is None or bridge.is_retired(item):
            missing.append(x["code"])
            continue
        if getattr(item, "basis", "$") == "%":
            percent.append(x["code"])
            continue
        billing = str(getattr(item, "billing", "") or "").lower().replace("-", " ")
        if billing.startswith("one"):
            one_time += price * x["qty"]
        else:
            periods = getattr(item, "periods_per_year", None)
            recurring += price * x["qty"] * (1 if periods is None else periods)  # partner share rows have 0 periods
    fmt = lambda v: int(v) if float(v).is_integer() else round(v, 2)  # noqa: E731
    return {"available": True, "one_time": fmt(one_time), "recurring_y1": fmt(recurring), "missing": missing, "percent": percent,
            "catalog_version": bridge.catalog_version(db), "note": None}


# ---- completion, lock and versions
def completion(db: Session, q: ScopingQuestionnaire, answers: dict[str, Ans] | None = None) -> dict[str, dict]:
    answers = answers if answers is not None else effective_answers(db, q)
    out: dict[str, dict] = {}
    for question in bank.questions(db, q.bank_version):
        s = out.setdefault(question.section, {"answered": 0, "total": 0})
        s["total"] += 1
        if question.code in answers:
            s["answered"] += 1
    return out


def lock(db: Session, questionnaire_id: str, actor) -> ScopingQuestionnaire:
    """Lock this version before it feeds a proposal (spec §4.4 rule 4). Conflicts must be settled first."""
    q = get(db, questionnaire_id)
    if q.status == "locked":
        raise Conflict("This version is already locked.")
    latest = current(db, q.opportunity_id)
    if latest is not None and latest.id != q.id:
        raise Conflict("A newer version of this questionnaire exists.")
    open_conflicts = conflicts(db, q)
    if open_conflicts:
        raise Conflict(f"Settle the {len(open_conflicts)} conflict{'s' if len(open_conflicts) != 1 else ''} between rep and client answers first.")
    q.status, q.locked_by, q.locked_at = "locked", _actor_id(actor), utcnow()
    from app.scoping import sending

    sending.close_links(db, q)
    from app.sales.models import Opportunity

    opp = db.get(Opportunity, q.opportunity_id)
    if opp is not None:
        _log(db, opp, f"Scoping questionnaire version {q.version} locked.", _actor_id(actor))
    db.flush()
    return q


def unlock(db: Session, questionnaire_id: str, actor) -> ScopingQuestionnaire:
    """Unlocking makes the next version with the same answers; the locked version stays as it was."""
    q = get(db, questionnaire_id)
    if q.status != "locked":
        raise Conflict("Only a locked version can be unlocked.")
    latest = current(db, q.opportunity_id)
    if latest.id != q.id:
        raise Conflict("A newer version of this questionnaire exists.")
    nq = ScopingQuestionnaire(prospect_id=q.prospect_id, opportunity_id=q.opportunity_id, bank_version=q.bank_version, version=q.version + 1,
                              mode=q.mode, status="draft", previous_id=q.id, removed_lines=list(q.removed_lines or []), created_by=_actor_id(actor))
    db.add(nq)
    db.flush()
    cols = [c.key for c in ScopingAnswer.__table__.columns if c.key not in ("id", "questionnaire_id")]
    for a in db.scalars(select(ScopingAnswer).where(ScopingAnswer.questionnaire_id == q.id)):
        db.add(ScopingAnswer(questionnaire_id=nq.id, **{k: getattr(a, k) for k in cols}))
    from app.sales.models import Opportunity

    opp = db.get(Opportunity, q.opportunity_id)
    if opp is not None:
        _log(db, opp, f"Scoping questionnaire unlocked; version {nq.version} started.", _actor_id(actor))
    db.flush()
    return nq
