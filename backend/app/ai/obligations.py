"""Obligation extraction (spec §21 F5). The model reads a law's stored text (the law record's full text, scope,
penalty and exemption text, and each requirement with its source passage) and proposes Obligation rows. Each quote is
checked against that stored text; one that is not there makes the obligation `unsupported`, and it cannot be approved.
The Legal Reviewer or the Chief Auditor approves, edits or rejects each one. Approved obligations show on the law
record (M2) and are read by lineage (F6, WS-K)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import prompts as P
from app.ai import service as ai
from app.ai.models import AIInteraction, Obligation
from app.ai.text import normalise, quote_in
from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid
from app.laws.models import Regulation
from app.questionnaire.models import Question
from app.regmaster.models import LawVersion, Requirement
from app.tenancy.models import User

ACTORS = ("developer", "deployer", "employer", "provider", "data_fiduciary")
# template questions an obligation's wording points at, for the fake and as a hint in the prompt
QUESTION_CUES = {"6.2.01": r"bias audit|bias test", "7.2.01": r"notice|notif|explain", "7.1.02": r"human (?:review|oversight)|override", "8.2.01": r"monitor",
                 "8.3.01": r"incident", "5.3.01": r"consent|legal basis"}


def law_sources(db: Session, reg: Regulation) -> tuple[LawVersion | None, list[dict], list[Requirement]]:
    v = db.get(LawVersion, reg.current_version_id) if reg.current_version_id else None
    srcs = []
    for kind, text in (("full_text", reg.full_text), ("obligations_text", reg.obligations_text), ("trigger_text", reg.trigger_text)):
        if text:
            srcs.append({"kind": kind, "id": reg.id, "label": kind.replace("_", " "), "citation": reg.citation, "text": text})
    if v is not None:
        for kind in ("scope_text", "penalty_text", "exemptions_text", "main_duty"):
            text = getattr(v, kind)
            if text:
                srcs.append({"kind": kind, "id": v.id, "label": kind.replace("_", " "), "citation": reg.citation, "text": text})
    reqs = list(db.scalars(select(Requirement).where(Requirement.law_version_id == v.id).order_by(Requirement.order))) if v else []
    for r in reqs:
        srcs.append({"kind": "requirement", "id": r.id, "label": r.code, "citation": r.citation, "text": " ".join(x for x in (r.text + ".", r.source_quote or "") if x)})
    return v, srcs, reqs


def obligation_out(db: Session, o: Obligation, req_codes: dict[str, str] | None = None) -> dict:
    by = db.get(User, o.approved_by) if o.approved_by else None
    codes = req_codes if req_codes is not None else {r.id: r.code for r in db.scalars(select(Requirement).where(Requirement.id.in_(o.requirement_ids or [])))}
    reg = db.get(Regulation, o.regulation_id)
    found = (db.get(AIInteraction, o.interaction_id).citations or [{}])[0].get("found") if o.interaction_id else None
    return {"id": o.id, "regulation_id": o.regulation_id, "law": reg.short_name if reg else None, "text": o.text, "actor": o.actor, "action": o.action, "condition": o.condition,
            "deadline": o.deadline, "citation": o.citation, "quote": o.quote, "quote_found": found, "effective_date": o.effective_date.isoformat() if o.effective_date else None,
            "control_ids": o.control_ids or [], "question_ids": o.question_ids or [], "requirement_ids": o.requirement_ids or [],
            "requirements": [codes[i] for i in o.requirement_ids or [] if i in codes], "confidence": o.confidence, "status": o.status,
            "approved_by": by.name if by else None, "approved_at": o.approved_at.isoformat() if o.approved_at else None, "rejected_reason": o.rejected_reason}


CHUNK_CHARS = 30_000  # law text per model call, so the obligations it proposes fit inside the model's reply limit


def _pieces(src: dict) -> list[dict]:
    """A source split on line breaks into pieces of at most CHUNK_CHARS (a longer line is cut)."""
    if len(src["text"]) <= CHUNK_CHARS:
        return [src]
    out, cur = [], ""
    for line in src["text"].split("\n"):
        while len(line) > CHUNK_CHARS:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:CHUNK_CHARS])
            line = line[CHUNK_CHARS:]
        if cur and len(cur) + 1 + len(line) > CHUNK_CHARS:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return [src | {"text": t, "label": f"{src['label']}, part {n + 1} of {len(out)}"} for n, t in enumerate(out)]


def chunks(srcs: list[dict]) -> list[list[dict]]:
    """The law's sources grouped into calls of at most CHUNK_CHARS of text each, in order."""
    out, cur, used = [], [], 0
    for p in (p for s in srcs for p in _pieces(s)):
        if cur and used + len(p["text"]) > CHUNK_CHARS:
            out.append(cur)
            cur, used = [], 0
        cur.append(p)
        used += len(p["text"])
    if cur:
        out.append(cur)
    return out


def extract(db: Session, app_state, settings, actor: User, reg: Regulation) -> tuple[list[Obligation], dict]:
    """Propose obligations from the law's stored text, read CHUNK_CHARS at a time. Obligations from parts the model read
    are kept when another part fails; the result says how many parts failed. When every part fails nothing changes (503)."""
    v, srcs, reqs = law_sources(db, reg)
    if not srcs:
        raise Invalid("This law has no stored text to read yet.", [{"field": "law", "message": "No text."}])
    known_q = set(db.scalars(select(Question.code)))
    req_list = "\n".join(f"- {r.code}: {r.text}" for r in reqs) or "(none)"
    parts = chunks(srcs)
    calls, failed, error = [], 0, None
    for n, part in enumerate(parts):
        text = "\n\n".join(f"[{s['label']}{' · ' + s['citation'] if s.get('citation') else ''}]\n{s['text']}" for s in part)
        prompt = (f"Law: {reg.short_name}" + (f" ({reg.citation})" if reg.citation else "") + f"\nApplies to: {', '.join((v.applies_to or []) if v else []) or reg.applies_to}\n\n"
                  f"Requirements already recorded:\n{req_list}\n\n" + (f"Part {n + 1} of {len(parts)} of the law's text. Propose only obligations stated in this part.\n\n" if len(parts) > 1 else "") +
                  f"Stored text of the law:\n{text}")
        try:
            calls.append(ai.call(app_state, settings, task="obligation_extract", prompt_version=P.OBLIGATION_VERSION, system=P.OBLIGATION_SYSTEM, prompt=prompt, schema=P.OBLIGATION_SCHEMA,
                                 context={"law": reg.short_name, "sources": part, "requirements": [{"code": r.code, "text": r.text} for r in reqs], "question_cues": QUESTION_CUES,
                                          "default_actor": ((v.applies_to or [None])[0] if v else None) or "deployer"}))
        except ai.AIUnavailable as ex:
            failed, error = failed + 1, ex
    if not calls and error is not None:
        raise error
    # a new run replaces the earlier run's undecided suggestions; decided rows stay
    now = utcnow()
    for old in db.scalars(select(Obligation).where(Obligation.regulation_id == reg.id, Obligation.status.in_(("suggested", "unsupported")), Obligation.deleted_at.is_(None))):
        old.deleted_at = now
    seen = {normalise(o.text) for o in db.scalars(select(Obligation).where(Obligation.regulation_id == reg.id, Obligation.status == "approved", Obligation.deleted_at.is_(None)))}
    by_code = {r.code: r.id for r in reqs}
    out = []
    for c in calls:
        rows = []
        for x in c.reply.data.get("obligations") or []:
            if not isinstance(x, dict) or not str(x.get("text") or "").strip() or normalise(x["text"]) in seen:
                continue
            seen.add(normalise(x["text"]))
            quote = str(x.get("quote") or "").strip()
            hit = next((s for s in srcs if quote and quote_in(s["text"], quote)), None)  # checked against the whole stored text
            actor_v = x.get("actor") if x.get("actor") in ACTORS else "deployer"
            cite = {"source_type": hit["kind"] if hit else "law_text", "source_id": hit["id"] if hit else reg.id, "label": hit["label"] if hit else reg.short_name, "quote": quote[:2000], "found": hit is not None}
            status = "suggested" if hit else "unsupported"
            row = ai.record(db, actor, c, organization_id=actor.organization_id, feature="obligation_extract", input_refs=[{"type": "regulation", "id": reg.id}] + ([{"type": "law_version", "id": v.id}] if v else []),
                            target_type="law", target_id=reg.id, target_code=(x.get("citation") or "")[:40] or None, output=x, citations=[cite], confidence=x.get("confidence"), status=status, first=not rows)
            rows.append(row)
            o = Obligation(organization_id=actor.organization_id, regulation_id=reg.id, law_version_id=v.id if v else None, text=str(x["text"]).strip()[:4000], actor=actor_v,
                           action=(x.get("action") or None), condition=(x.get("condition") or None), deadline=(str(x.get("deadline"))[:300] if x.get("deadline") else None),
                           citation=(str(x.get("citation"))[:200] if x.get("citation") else None), quote=quote or None, effective_date=v.effective_on if v else None, control_ids=[],
                           question_ids=[q for q in x.get("question_codes") or [] if q in known_q], requirement_ids=[by_code[k] for k in x.get("requirement_codes") or [] if k in by_code],
                           confidence=x.get("confidence") if x.get("confidence") in ("high", "medium", "low") else None, status=status, interaction_id=row.id, created_by=actor.id)
            db.add(o)
            out.append(o)
        db.flush()
        found = len(rows)
        if not rows:
            rows.append(ai.record(db, actor, c, organization_id=actor.organization_id, feature="obligation_extract", input_refs=[{"type": "regulation", "id": reg.id}], target_type="law",
                                  target_id=reg.id, output={"none_found": True}))
        ai.log_call(db, actor, c, rows, f"Extracted {found} proposed obligation{'s' if found != 1 else ''} from {reg.short_name}" + (f" (one of {len(parts)} parts of its text)" if len(parts) > 1 else ""),
                    None, actor.organization_id)
    message = f"{failed} of {len(parts)} parts of the law's text could not be read because the model did not answer. Extract again to read the whole law." if failed else None
    return out, {"parts": len(parts), "failed_parts": failed, "message": message}


EDITABLE = ("text", "actor", "action", "condition", "deadline", "citation", "question_ids", "control_ids", "requirement_ids", "effective_date")


def approve(db: Session, actor: User, o: Obligation, body: dict) -> Obligation:
    from datetime import date

    if o.status == "unsupported":
        raise Conflict("The quoted passage is not in the law's stored text, so this obligation cannot be approved. Reject it, or add the law text and extract again.")
    if o.status != "suggested":
        raise Conflict("This obligation has already been decided.")
    errs, changes = [], {}
    for k in EDITABLE:
        if k not in body:
            continue
        val = body[k]
        if k == "actor" and val not in ACTORS:
            errs.append({"field": k, "message": "Choose developer, deployer, employer, provider or data fiduciary."})
        elif k == "question_ids":
            known = set(db.scalars(select(Question.code)))
            if not isinstance(val, list) or any(q not in known for q in val):
                errs.append({"field": k, "message": "Choose questions from the audit template."})
        elif k == "requirement_ids":
            ok = {r.id for r in db.scalars(select(Requirement).where(Requirement.law_version_id == o.law_version_id))}
            if not isinstance(val, list) or any(r not in ok for r in val):
                errs.append({"field": k, "message": "Choose requirements of this law."})
        elif k == "effective_date" and val:
            try:
                val = date.fromisoformat(str(val))
            except ValueError:
                errs.append({"field": k, "message": "Enter a date."})
        elif k == "text" and not str(val or "").strip():
            errs.append({"field": k, "message": "Describe the obligation."})
        if not errs and val != getattr(o, k):
            changes[k] = val
    if errs:
        raise Invalid(errors=errs)
    for k, val in changes.items():
        setattr(o, k, val.strip() if isinstance(val, str) else val)
    o.status, o.approved_by, o.approved_at, o.updated_by = "approved", actor.id, utcnow(), actor.id
    i = db.get(AIInteraction, o.interaction_id) if o.interaction_id else None
    if i is not None:
        ai.decide(db, actor, i, "edited" if changes else "accepted", result_refs=[{"type": "obligation", "id": o.id}])
    audit.record(db, actor_id=actor.id, action="obligation.approve", obj=o, after={"changes": {k: str(v) for k, v in changes.items()}}, summary=f"Approved an obligation of {db.get(Regulation, o.regulation_id).short_name}")
    return o


def reject(db: Session, actor: User, o: Obligation, reason) -> Obligation:
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why this is not an obligation."}])
    if o.status not in ("suggested", "unsupported"):
        raise Conflict("This obligation has already been decided.")
    o.status, o.rejected_reason, o.updated_by = "rejected", reason[:2000], actor.id
    i = db.get(AIInteraction, o.interaction_id) if o.interaction_id else None
    if i is not None:
        ai.decide(db, actor, i, "rejected", reason[:2000])
    audit.record(db, actor_id=actor.id, action="obligation.reject", obj=o, after={"reason": reason}, summary=f"Rejected a proposed obligation: {reason[:120]}")
    return o


def approved_for(db: Session, regulation_id: str) -> list[Obligation]:
    """Approved obligations of a law, for the law record and for lineage (WS-K)."""
    return list(db.scalars(select(Obligation).where(Obligation.regulation_id == regulation_id, Obligation.status == "approved", Obligation.deleted_at.is_(None)).order_by(Obligation.created_at)))
