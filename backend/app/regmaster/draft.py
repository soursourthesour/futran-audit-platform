"""M1b "Draft with Claude": Claude reads the official text of a bill and fills the add-a-law form.

Nothing is saved here. The person checks every field and sends the form for approval, which creates a ProposedChange
for the Chief Auditor (§25.1 principle 1). Uses the Claude client from app.laws.refresh."""
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import today
from app.regmaster.models import AI_TYPES, APPLIES_TO, STAGES, VERSION_STATUSES, RoleCatalog, Source
from app.regmaster.seed import domain_of

PROMPT_VERSION = "m1b-draft-1"

PROMPT = """You help Futran Solutions keep a regulatory master of AI laws. Today is {today}.
Read the official text of this law and draft its record: {ref}

Use only official sources (legislature, regulator, official journal). Allowed official domains: {domains}.
Quote the exact words of the law for every requirement. If you cannot find a quote, leave the requirement out.

Reply with one JSON object inside a ```json fenced block and nothing after it:
{{"short_name": str, "citation": str, "jurisdiction_code": str (e.g. US-CO, EU, IN), "type": "statute"|"regulation"|"executive"|"guidance"|"framework"|"pending",
  "binding": bool, "status": one of {statuses}, "signed_on": "YYYY-MM-DD"|null, "effective_on": "YYYY-MM-DD"|null, "compliance_on": "YYYY-MM-DD"|null,
  "enforcer": str, "private_right_of_action": bool|null, "penalty_text": str, "cure_period": str|null, "applies_to": [one or more of {applies}],
  "scope_text": str, "exemptions_text": str|null,
  "sources": [{{"name": str, "url": str}}],
  "requirements": [{{"code": str, "text": str, "applies_to": [...], "needed_by_stage": one of {stages}, "evidence_text": str,
                     "role": one of {roles} or null, "ai_types": [one or more of {ai_types}], "citation": str, "source_quote": str, "source_url": str}}],
  "scope_tests": [{{"question_text": str, "prefill_from": "client_geographies"|"decision_impact"|null}}]}}"""


def _object(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def draft_law(db: Session, client, ref: str) -> dict:
    """Ask Claude for a draft record. Returns {"draft": {...}, "warnings": [...], "prompt_version": ...}."""
    official = sorted({s.domain for s in db.scalars(select(Source).where(Source.kind == "official", Source.active.is_(True), Source.regulation_id.is_(None))) if s.domain})
    roles = [r.code for r in db.scalars(select(RoleCatalog).order_by(RoleCatalog.number))]
    prompt = PROMPT.format(today=today().isoformat(), ref=ref, domains=", ".join(official), statuses=VERSION_STATUSES, applies=APPLIES_TO, stages=STAGES, roles=roles, ai_types=AI_TYPES)
    reply = client.research(prompt)
    try:
        data = _object(reply)
    except (ValueError, json.JSONDecodeError):
        return {"draft": None, "warnings": ["Claude's reply could not be read as a law record. Try again or fill the form by hand."], "prompt_version": PROMPT_VERSION}
    warnings: list[str] = []
    sources = []
    for s in data.get("sources") or []:
        if not isinstance(s, dict) or not str(s.get("url", "")).startswith("http"):
            continue
        kind = "official" if domain_of(s["url"]) in official else "secondary"
        if kind == "secondary":
            warnings.append(f"{s['url']} is not on the official source list; it is marked secondary.")
        sources.append({"name": str(s.get("name") or s["url"])[:300], "url": s["url"][:600], "kind": kind})
    reqs = []
    for i, r in enumerate(data.get("requirements") or [], start=1):
        if not isinstance(r, dict):
            continue
        if not (r.get("source_quote") or "").strip() or not (r.get("citation") or "").strip():
            warnings.append(f"Requirement {r.get('code') or i} was left out: it had no citation or quote.")
            continue
        reqs.append({
            "code": str(r.get("code") or f"R-{i:02d}")[:20], "text": str(r.get("text", ""))[:600],
            "applies_to": [a for a in r.get("applies_to") or [] if a in APPLIES_TO], "needed_by_stage": r.get("needed_by_stage") if r.get("needed_by_stage") in STAGES else "go_live",
            "evidence_text": str(r.get("evidence_text") or "")[:400], "role": r.get("role") if r.get("role") in roles else None,
            "ai_types": [t for t in r.get("ai_types") or [] if t in AI_TYPES] or ["decision"], "citation": str(r["citation"])[:200],
            "source_quote": str(r["source_quote"]), "source_url": str(r.get("source_url") or (sources[0]["url"] if sources else ""))[:600], "verify_flag": True,
        })
    if not sources:
        warnings.append("Claude gave no source link. Add the official source before sending for approval.")
    draft = {k: data.get(k) for k in ("short_name", "citation", "jurisdiction_code", "type", "binding", "status", "signed_on", "effective_on", "compliance_on", "enforcer", "private_right_of_action", "penalty_text", "cure_period", "scope_text", "exemptions_text")}
    if draft.get("status") not in VERSION_STATUSES:
        draft["status"] = None
    draft["applies_to"] = [a for a in data.get("applies_to") or [] if a in APPLIES_TO]
    draft["sources"] = sources
    draft["requirements"] = reqs
    draft["scope_tests"] = [{"question_text": str(t.get("question_text"))[:500], "prefill_from": t.get("prefill_from") if t.get("prefill_from") in ("client_geographies", "decision_impact") else None}
                            for t in data.get("scope_tests") or [] if isinstance(t, dict) and t.get("question_text")]
    return {"draft": draft, "warnings": warnings, "prompt_version": PROMPT_VERSION}
