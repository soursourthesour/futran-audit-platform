"""The refresh pipeline for laws and litigation (spec §25.3, §27.4).

One structured Claude call per jurisdiction. The reply must be JSON matching SCHEMAS[kind]; anything else is rejected.
Each proposed change is checked (quote present, field path exists, law or case belongs to the jurisdiction, source on
the allowlist — else confidence is forced to low), merged with the same proposal from earlier runs, saved as a
ProposedChange with its impact, and the Chief Auditor is alerted when the run ends (§27.9). Nothing is applied here:
approval is in review.py.
"""
import hashlib
import json
from datetime import date
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.config import Settings
from app.laws.models import Regulation
from app.laws.publish import current_regulations
from app.litigation.models import STAGES as CASE_STAGES
from app.litigation.models import Case, CaseClientMatch
from app.reference.models import Jurisdiction
from app.refresh.claude import StructuredClaude
from app.refresh.models import CHECKS, RefreshProposalMeta, RefreshRun, RefreshSetting
from app.regmaster.models import ChangeImpact, ClientGeography, LawRoleMap, LawVersion, ProposedChange, Requirement, RoleCatalog, Source
from app.tenancy.models import User

PROMPT_VERSIONS = {"law": "law-refresh-2026-10-30.1", "litigation": "litigation-refresh-2026-10-30.1"}
LAW_CHANGE_TYPES = ["new_law", "amendment", "effective_date", "new_rule", "guidance", "role_mapping", "repeal", "enforcement"]
CASE_CHANGE_TYPES = ["new_case", "case_update"]
VERSION_FIELDS = ["status", "signed_on", "effective_on", "compliance_on", "effective_text", "scope_text", "applies_to", "enforcer", "private_right_of_action",
                  "penalty_text", "cure_period", "exemptions_text", "removed_text", "litigation_text", "main_duty"]
REGULATION_FIELDS = ["short_name", "citation", "type", "binding", "topics"]
CASE_FIELDS = ["stage", "stage_note", "last_update_on", "court", "docket_ref", "description", "why_matters", "talking_points_client"]
OPEN = ("pending", "held", "legal_review")
MAX_JURISDICTIONS = 60


def _schema(kind: str) -> dict:
    ref_key = "case_id" if kind == "litigation" else "regulation_id"
    item = {
        "type": "object",
        "properties": {
            "change_type": {"type": "string", "enum": CASE_CHANGE_TYPES if kind == "litigation" else LAW_CHANGE_TYPES},
            ref_key: {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "field_path": {"type": "string"},
            "old_value": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "new_value": {"type": "string"},
            "summary": {"type": "string"},
            "source_url": {"type": "string"},
            "source_quote": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["change_type", ref_key, "field_path", "old_value", "new_value", "summary", "source_url", "source_quote", "confidence"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"changes": {"type": "array", "items": item}}, "required": ["changes"], "additionalProperties": False}


SCHEMAS = {"law": _schema("law"), "litigation": _schema("litigation")}


class ItemIn(BaseModel):
    change_type: str
    regulation_id: str | None = None
    case_id: str | None = None
    field_path: str = Field(min_length=1, max_length=120)
    old_value: str | None = None
    new_value: str
    summary: str = Field(min_length=1, max_length=1000)
    source_url: str = Field(min_length=8, max_length=600)
    source_quote: str = ""
    confidence: str


class ReplyIn(BaseModel):
    model_config = {"extra": "forbid"}
    changes: list[dict]


SYSTEM = {
    "law": ("You keep Futran Solutions' regulatory master of AI laws current. Compare the approved records you are given with what the "
            "official sources say today and propose only real changes. Search only the allowlisted sources. Every change quotes the exact "
            "passage it rests on. Reply with JSON that matches the schema and nothing else."),
    "litigation": ("You keep Futran Solutions' AI litigation tracker current. Compare the approved case records you are given with the "
                   "official court and regulator sources and propose only real changes in stage, dates or substance, or new cases that interpret "
                   "AI laws. Search only the allowlisted sources. Every change quotes the exact passage it rests on. Reply with JSON that matches "
                   "the schema and nothing else."),
}

LAW_RULES = """Field paths:
  law.<field>             fields: {fields}
  requirement.<code>      new_value = JSON object {{"code","text","applies_to","needed_by_stage","evidence_text","citation"}}, or "null" to remove
  role_map.<role_code>    new_value = JSON object {{"level": "required" | "recommended", "needed_by_stage"}}, or "null" to remove; role codes: {roles}
  new_law                 new_value = JSON object {{"jurisdiction_code","short_name","citation","type","status","effective_on","scope_text"}}; regulation_id null
  repeal                  new_value = JSON object {{"status": "repealed", "effective_on"}}
Dates are YYYY-MM-DD. old_value is the value in the approved record, or null. regulation_id is the id from the records.
Confidence: high only when the quoted official text states the change outright; medium when it is adopted but details are pending;
low when the source is a proposal, a press release, a secondary source or you are unsure. If nothing changed, return {{"changes": []}}."""

CASE_RULES = """Field paths:
  case.<field>            fields: {fields}; stage is one of {stages}
  new_case                new_value = JSON object {{"name","court","docket_ref","area","stage","description","last_update_on"}}; case_id null
Dates are YYYY-MM-DD. old_value is the value in the approved record, or null. case_id is the id from the records.
Report only what the court record or the regulator publishes. If nothing changed, return {{"changes": []}}."""


# ---- scope
def jurisdictions_for(db: Session, kind: str, scope_mode: str, codes: list[str] | None) -> list[Jurisdiction]:
    if scope_mode == "chosen":
        rows = list(db.scalars(select(Jurisdiction).where(Jurisdiction.code.in_([c.upper() for c in codes or []]))))
        order = {c.upper(): i for i, c in enumerate(codes or [])}
        return sorted(rows, key=lambda j: order.get(j.code, 0))
    if scope_mode == "client_geographies":
        ids = set(db.scalars(select(ClientGeography.jurisdiction_id).where(ClientGeography.deleted_at.is_(None))))
    elif kind == "litigation":
        ids = {c.jurisdiction_id for c in db.scalars(select(Case).where(Case.deleted_at.is_(None))) if c.jurisdiction_id}
    else:
        ids = {r.jurisdiction_id for r in current_regulations(db)}
    rows = list(db.scalars(select(Jurisdiction).where(Jurisdiction.id.in_(ids)))) if ids else []
    return sorted(rows, key=lambda j: j.code)[:MAX_JURISDICTIONS]


def get_run_setting(db: Session, kind: str) -> RefreshSetting:
    s = db.scalar(select(RefreshSetting).where(RefreshSetting.kind == kind))
    if s is None:
        s = RefreshSetting(kind=kind, schedule_enabled=True, every_days=14, scope_mode="all", jurisdiction_ids=[], checks=list(CHECKS[kind]), source_set="official", cost_cap_usd=5.0)
        db.add(s)
        db.flush()
    return s


def start_run(db: Session, *, kind: str, actor: User | None, settings: Settings, scope_mode: str = "chosen", jurisdiction_codes: list[str] | None = None,
              checks: list[str] | None = None, source_set: str | None = None, cost_cap_usd: float | None = None, trigger: str = "manual",
              alert_recipients: str = "setting") -> RefreshRun:
    rs = get_run_setting(db, kind)
    js = jurisdictions_for(db, kind, scope_mode, jurisdiction_codes)
    run = RefreshRun(kind=kind, trigger=trigger, started_by=actor.id if actor else None, scope_mode=scope_mode, jurisdiction_ids=[j.id for j in js],
                     checks=[c for c in (checks or rs.checks or CHECKS[kind]) if c in CHECKS[kind]], source_set=source_set or rs.source_set,
                     cost_cap_usd=cost_cap_usd if cost_cap_usd is not None else rs.cost_cap_usd, prompt_version=PROMPT_VERSIONS[kind],
                     status="queued", warnings=[], responses=[], alert_recipients=alert_recipients)
    db.add(run)
    db.flush()
    audit.record(db, actor_id=actor.id if actor else None, action="refresh.start", object_type="RefreshRun", object_id=run.id,
                 organization_id=actor.organization_id if actor else "futran", summary=f"{'Litigation' if kind == 'litigation' else 'Law'} refresh started ({trigger}) for {len(js)} geographies")
    return run


# ---- allowlist
def host_of(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def allowlist(db: Session, j: Jurisdiction, source_set: str) -> list[Source]:
    ids, cur, seen = [j.id], j, set()
    while cur is not None and cur.parent_id and cur.parent_id not in seen:
        seen.add(cur.parent_id)
        ids.append(cur.parent_id)
        cur = db.get(Jurisdiction, cur.parent_id)
    kinds = ["official", "secondary"] if source_set == "with_secondary" else ["official"]
    q = select(Source).where(Source.active.is_(True), Source.kind.in_(kinds), (Source.jurisdiction_id.in_(ids)) | (Source.jurisdiction_id.is_(None)))
    return list(db.scalars(q.order_by(Source.name)))


def on_allowlist(url: str, domains: list[str]) -> bool:
    h = host_of(url)
    return bool(h) and any(h == d or h.endswith("." + d) for d in domains)


def _ws(text: str | None) -> str:
    return " ".join((text or "").split())


def _page(url: str) -> str:
    """A cited page, compared without scheme, a leading www, a fragment or a trailing slash; the host is case-blind."""
    p = urlparse((url or "").strip())
    host = (p.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return f"{host}{p.path.rstrip('/')}" + (f"?{p.query}" if p.query else "")


def citation_supported(cited: dict[str, list[str]] | None, url: str, quote: str) -> bool:
    """True when `url` is a page web search cited and `quote` comes from what it cited there (whitespace normalised;
    the quote may be part of a passage, or run across the passages cited from that page)."""
    if not cited or not (quote or "").strip():
        return False
    want, q = _page(url), _ws(quote)
    for page, passages in cited.items():
        if _page(page) != want:
            continue
        texts = [_ws(p) for p in passages or []]
        if any(q in t for t in texts) or q in " ".join(texts):
            return True
    return False


def _domains(sources: list[Source]) -> list[str]:
    out = set()
    for s in sources:
        out.add(_bare(s.domain or host_of(s.url)))
    return sorted(d for d in out if d)


# ---- records sent to Claude
def _law_records(db: Session, regs: list[Regulation]) -> list[dict]:
    roles = {r.id: r.code for r in db.scalars(select(RoleCatalog))}
    out = []
    for r in regs:
        v = db.get(LawVersion, r.current_version_id) if r.current_version_id else None
        rec = {"regulation_id": r.id, "short_name": r.short_name, "citation": r.citation, "type": r.type}
        if v is not None:
            rec |= {"version_no": v.version_no, **{f: _plain(getattr(v, f)) for f in VERSION_FIELDS if getattr(v, f) not in (None, [], "")}}
            rec["requirements"] = [{"code": q.code, "text": q.text} for q in db.scalars(select(Requirement).where(Requirement.law_version_id == v.id).order_by(Requirement.order))]
            rec["roles"] = [{"role": roles.get(m.role_id, m.role_id), "level": m.level} for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == v.id))]
        else:
            rec |= {"status_text": r.status_text, "effective_date_text": r.effective_date_text, "obligations": r.obligations_text}
        out.append(rec)
    return out


def _case_records(cases: list[Case]) -> list[dict]:
    return [{"case_id": c.id, "name": c.name, "court": c.court, "docket_ref": c.docket_ref, "stage": c.stage, "stage_note": c.stage_note,
             "last_update_on": _plain(c.last_update_on), "description": c.description} for c in cases]


def _plain(v):
    return v.isoformat() if isinstance(v, date) else v


def build_prompt(db: Session, run: RefreshRun, j: Jurisdiction, records: list[dict], sources: list[Source]) -> str:
    roles = ", ".join(sorted(db.scalars(select(RoleCatalog.code)))) or "(none)"
    rules = (CASE_RULES.format(fields=", ".join(CASE_FIELDS), stages=", ".join(CASE_STAGES)) if run.kind == "litigation"
             else LAW_RULES.format(fields=", ".join(VERSION_FIELDS + REGULATION_FIELDS), roles=roles))
    allow = "\n".join(f"- {s.name}: {s.url}" + (" (secondary)" if s.kind == "secondary" else "") for s in sources) or "- (none recorded)"
    return (f"Prompt version: {run.prompt_version}\nJurisdiction code: {('litigation:' if run.kind == 'litigation' else '') + j.code}\nJurisdiction: {j.name}\n"
            f"Today: {today().isoformat()}\nCheck for: {', '.join(run.checks)}\n\nApproved records (JSON):\n{json.dumps(records, ensure_ascii=False, indent=1)}\n\n"
            f"Source allowlist:\n{allow}\n\n{rules}")


# ---- validation
def _parse_value(v: str | None):
    if v is None:
        return None
    t = v.strip()
    if t == "null":
        return None
    if t[:1] in ("{", "["):
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            return v
    return v


def dedupe_key(kind: str, ref: str, field_path: str, new_value) -> str:
    raw = f"{kind}|{ref}|{field_path}|{json.dumps(new_value, sort_keys=True, ensure_ascii=False)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:40]


def _process_item(db: Session, run: RefreshRun, j: Jurisdiction, i: int, raw: dict, domains: list[str], regs: dict[str, Regulation],
                  cases: dict[str, Case], warnings: list[str], official: list[str] | None = None, cited: dict | None = None) -> str:
    label = f"{j.code}, item {i}"
    try:
        it = ItemIn.model_validate(raw)
    except ValidationError as exc:
        warnings.append(f"{label}: skipped because it does not match the schema ({exc.errors()[0]['msg']}).")
        return "skipped"
    allowed_types = CASE_CHANGE_TYPES if run.kind == "litigation" else LAW_CHANGE_TYPES
    if it.change_type not in allowed_types:
        warnings.append(f"{label}: skipped because the change type {it.change_type} is not known.")
        return "skipped"
    if len(it.source_quote.strip()) < 10:
        warnings.append(f"{label}: skipped because it has no source quote.")
        return "skipped"
    if run.kind == "litigation" and not (it.field_path == "new_case" or (it.field_path.startswith("case.") and it.field_path[5:] in CASE_FIELDS)):
        warnings.append(f"{label}: skipped because the field {it.field_path} does not exist.")
        return "skipped"
    reg = case = None
    if run.kind == "law" and it.change_type != "new_law":
        reg = regs.get(it.regulation_id or "")
        if reg is None:
            warnings.append(f"{label}: skipped because it refers to a law that is not in this jurisdiction.")
            return "skipped"
    if run.kind == "litigation" and it.change_type == "case_update":
        case = cases.get(it.case_id or "")
        if case is None:
            warnings.append(f"{label}: skipped because it refers to a case that is not in this jurisdiction.")
            return "skipped"
    new_value = _parse_value(it.new_value)
    off = not on_allowlist(it.source_url, domains)
    secondary = not off and not on_allowlist(it.source_url, official if official is not None else domains)  # a law-firm alert, not an official source
    uncited = not citation_supported(cited, it.source_url, it.source_quote)
    if uncited:
        warnings.append(f"{label}: the link or quote is not among the passages the search cited; marked low confidence for a second review.")
    confidence = "low" if off or secondary or uncited else it.confidence
    if run.kind == "law":
        return _propose_law(db, run, j, label, it, reg, new_value, confidence, off, warnings)
    return _propose_case(db, run, j, label, it, case, new_value, confidence, off, domains, warnings)


def _merge(db: Session, run: RefreshRun, change: ProposedChange) -> str:
    meta = db.get(RefreshProposalMeta, change.id)
    if meta is None:
        meta = RefreshProposalMeta(proposed_change_id=change.id, kind=run.kind, run_ids=[change.refresh_run_id] if change.refresh_run_id else [], seen_count=1,
                                   needs_second_review=change.confidence == "low" or change.change_type == "new_law", claude_confidence=change.confidence)
        db.add(meta)
    if run.id not in (meta.run_ids or []):
        meta.run_ids = [*(meta.run_ids or []), run.id]
        meta.seen_count = (meta.seen_count or 0) + 1
    meta.last_seen_at = utcnow()
    return "merged"


def _propose_law(db: Session, run: RefreshRun, j: Jurisdiction, label: str, it: ItemIn, reg: Regulation | None, new_value, confidence: str, off: bool,
                 warnings: list[str]) -> str:
    """Laws go through the regulatory master's `propose` (validation, old value, open-duplicate merge, impact)."""
    from app.core.errors import Invalid
    from app.regmaster import changes as master

    keys = master.dedupe_keys(db, reg.id if reg else None, it.field_path, new_value)  # any row of the law
    closed = db.scalar(select(ProposedChange).where(ProposedChange.dedupe_key.in_(keys), ProposedChange.status.not_in(OPEN)).limit(1))
    if closed is None and it.field_path == "new_law" and isinstance(new_value, dict):
        closed = master.same_new_law(db, new_value, ("approved", "edited_approved", "rejected"))  # the same law in other words
    if closed is not None:
        warnings.append(f"{label}: not proposed again; the same change was already {'rejected' if closed.status == 'rejected' else 'approved'}.")
        return "skipped"
    before = db.scalar(select(ProposedChange.id).where(ProposedChange.dedupe_key.in_(keys), ProposedChange.status.in_(OPEN)).limit(1))
    try:
        pc = master.propose(db, actor_id=None, regulation_id=reg.id if reg else None, field_path=it.field_path, new_value=new_value, summary=it.summary,
                            origin="claude_refresh", change_type=it.change_type, source_url=it.source_url, source_quote=it.source_quote.strip(),
                            confidence=confidence, refresh_run_id=run.id, jurisdiction_id=j.id)
    except Invalid as exc:
        reason = (exc.errors[0]["message"] if exc.errors else exc.detail).rstrip(".")
        warnings.append(f"{label}: skipped because {reason[:1].lower() + reason[1:]}.")
        return "skipped"
    if before is not None and pc.id == before:
        return _merge(db, run, pc)
    db.add(RefreshProposalMeta(proposed_change_id=pc.id, kind="law", run_ids=[run.id], seen_count=1, off_allowlist=off or pc.source_id is None,
                               claude_confidence=it.confidence, needs_second_review=master.needs_second_review(pc)))
    db.flush()
    return "created"


def _propose_case(db: Session, run: RefreshRun, j: Jurisdiction, label: str, it: ItemIn, case: Case | None, new_value, confidence: str, off: bool,
                  domains: list[str], warnings: list[str]) -> str:
    if it.field_path == "case.stage" and new_value not in CASE_STAGES:
        warnings.append(f"{label}: skipped because {new_value} is not a stage.")
        return "skipped"
    if it.field_path == "new_case" and not (isinstance(new_value, dict) and new_value.get("name") and new_value.get("stage") in CASE_STAGES):
        warnings.append(f"{label}: skipped because a new case needs a name and a stage.")
        return "skipped"
    if it.field_path == "new_case":  # one case: same court and docket, or same court and name when there is no docket
        key = dedupe_key("litigation", j.id, "new_case", case_identity(new_value))
        same = db.scalar(select(ProposedChange).where(ProposedChange.dedupe_key == key).order_by(ProposedChange.created_at.desc()).limit(1)) or same_new_case(db, j.id, new_value)
    else:
        key = dedupe_key("litigation", case.id if case else j.id, it.field_path, new_value)
        same = db.scalar(select(ProposedChange).where(ProposedChange.dedupe_key == key).order_by(ProposedChange.created_at.desc()).limit(1))
    if same is not None:
        if same.status in OPEN:
            return _merge(db, run, same)
        warnings.append(f"{label}: not proposed again; the same change was already {'rejected' if same.status == 'rejected' else 'approved'}.")
        return "skipped"
    src = next((s for s in db.scalars(select(Source).where(Source.active.is_(True))) if s.domain and on_allowlist(it.source_url, [_bare(s.domain)])), None) if not off else None
    pc = ProposedChange(
        refresh_run_id=run.id, origin="claude_refresh", change_type=it.change_type, regulation_id=None, jurisdiction_id=j.id, field_path=it.field_path,
        old_value=_plain(getattr(case, it.field_path[5:])) if case is not None and it.field_path.startswith("case.") else None, new_value=new_value,
        summary=it.summary, source_id=src.id if src else None, source_url=it.source_url, source_quote=it.source_quote.strip(), confidence=confidence,
        status="pending", dedupe_key=key,
    )
    db.add(pc)
    db.flush()
    meta = RefreshProposalMeta(proposed_change_id=pc.id, kind="litigation", case_id=case.id if case else None, run_ids=[run.id], seen_count=1, off_allowlist=off,
                               claude_confidence=it.confidence, needs_second_review=confidence == "low")
    db.add(meta)
    db.flush()
    case_impacts(db, pc, meta)
    return "created"


def case_identity(value: dict) -> str:
    """Court plus docket, or court plus name when there is no docket (normalised)."""
    from app.regmaster.changes import norm_name

    court, docket = norm_name(value.get("court")), norm_name(value.get("docket_ref"))
    return f"{court}|docket|{docket}" if docket else f"{court}|name|{norm_name(value.get('name'))}"


def same_new_case(db: Session, jurisdiction_id: str | None, value: dict) -> ProposedChange | None:
    """A new-case proposal for the same case in this geography, whatever its free text says (covers older keys)."""
    want = case_identity(value)
    q = select(ProposedChange).where(ProposedChange.field_path == "new_case", ProposedChange.jurisdiction_id == jurisdiction_id).order_by(ProposedChange.created_at.desc())
    return next((pc for pc in db.scalars(q) if isinstance(pc.new_value, dict) and case_identity(pc.new_value) == want), None)


def case_in_tracker(db: Session, jurisdiction_id: str | None, value: dict) -> Case | None:
    want = case_identity(value)
    q = select(Case).where(Case.deleted_at.is_(None), Case.jurisdiction_id == jurisdiction_id)
    return next((c for c in db.scalars(q) if case_identity({"court": c.court, "docket_ref": c.docket_ref, "name": c.name}) == want), None)


def _bare(d: str) -> str:
    d = d.lower()
    return d[4:] if d.startswith("www.") else d


def case_impacts(db: Session, change: ProposedChange, meta: RefreshProposalMeta) -> None:
    """A case change touches the clients whose registers hold similar AI (§27.4)."""
    for old in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == change.id)):
        db.delete(old)
    if meta.case_id:
        for m in db.scalars(select(CaseClientMatch).where(CaseClientMatch.case_id == meta.case_id)):
            db.add(ChangeImpact(proposed_change_id=change.id, organization_id=m.organization_id, ai_system_ids=list(m.ai_system_ids or []),
                                roles_affected=[], letter_update_needed=False, summary=m.match_reason[:600]))
    db.flush()


def _cost(settings: Settings, input_tokens: int, output_tokens: int, searches: int) -> float:
    return (input_tokens * settings.claude_input_usd_per_mtok + output_tokens * settings.claude_output_usd_per_mtok) / 1e6 + searches * settings.claude_search_usd_each


def execute_run(db: Session, settings: Settings, run: RefreshRun, client: StructuredClaude, commit=None) -> RefreshRun:
    """Research each jurisdiction in turn. `commit` (when given) runs before every network call so no database
    transaction stays open while Claude searches."""
    run.status = "running"
    run.model_id = getattr(client, "model", None)
    warnings: list[str] = list(run.warnings or [])
    responses: list[dict] = list(run.responses or [])
    js = [db.get(Jurisdiction, jid) for jid in run.jurisdiction_ids]
    js = [j for j in js if j is not None]
    try:
        for n, j in enumerate(js):
            if run.cost_cap_usd is not None and run.cost_usd >= run.cost_cap_usd:
                left = ", ".join(x.code for x in js[n:])
                warnings.append(f"Stopped at the cost cap of ${run.cost_cap_usd:.2f}; not checked: {left}.")
                run.status = "capped"
                break
            if run.kind == "litigation":
                cases = {c.id: c for c in db.scalars(select(Case).where(Case.jurisdiction_id == j.id, Case.deleted_at.is_(None)))}
                regs: dict[str, Regulation] = {}
                records = _case_records(list(cases.values()))
            else:
                regs = {r.id: r for r in current_regulations(db) if r.jurisdiction_id == j.id}
                cases = {}
                records = _law_records(db, list(regs.values()))
            sources = allowlist(db, j, run.source_set)
            domains = _domains(sources)
            official = _domains([s for s in sources if s.kind == "official"])
            prompt = build_prompt(db, run, j, records, sources)
            run.sources_read += len(sources)
            run.records_compared += len(records)
            if commit is not None:
                commit()
            reply = client.propose(system=SYSTEM[run.kind], prompt=prompt, schema=SCHEMAS[run.kind], allowed_domains=domains)
            cost = _cost(settings, reply.input_tokens, reply.output_tokens, reply.searches)
            run.input_tokens += reply.input_tokens
            run.output_tokens += reply.output_tokens
            run.searches += reply.searches
            run.cost_usd = round((run.cost_usd or 0) + cost, 6)
            run.model_id = reply.model or run.model_id
            entry = {"jurisdiction": j.code, "model": reply.model, "prompt_version": run.prompt_version, "sources": len(sources), "records": len(records),
                     "cost_usd": round(cost, 4), "reply": reply.text[:20000], "accepted": 0, "merged": 0, "skipped": 0, "outcome": "ok"}
            try:
                items = ReplyIn.model_validate(json.loads(reply.text)).changes
            except (json.JSONDecodeError, ValidationError, TypeError):
                warnings.append(f"{j.code}: the reply was rejected because it was not JSON matching the schema.")
                entry["outcome"] = "rejected"
                responses.append(entry)
                continue
            for i, raw in enumerate(items, start=1):
                result = _process_item(db, run, j, i, raw, domains, regs, cases, warnings, official=official, cited=getattr(reply, "cited", None))
                entry[{"created": "accepted", "merged": "merged", "skipped": "skipped"}[result]] += 1
                if result == "created":
                    run.proposals_created += 1
                elif result == "merged":
                    run.proposals_merged += 1
            for s in sources:
                s.last_read_at = utcnow()
            responses.append(entry)
        if run.status == "running":
            run.status = "completed"
    except Exception as exc:  # recorded, never half-applied: proposals only exist until reviewed
        run.status = "failed"
        run.error = str(exc)[:2000]
    run.warnings = warnings
    run.responses = responses
    run.finished_at = utcnow()
    db.flush()
    audit.record(db, actor_id=run.started_by, action="refresh.finish", object_type="RefreshRun", object_id=run.id, organization_id="futran",
                 summary=f"Refresh {run.status}: {run.proposals_created} new proposals, {run.proposals_merged} merged, ${run.cost_usd:.2f}")
    try:
        from app.staffalerts.service import alert_run_finished

        alert_run_finished(db, settings, run)
    except Exception as exc:  # an alert failure must not lose the run
        run.alert_status = f"Alert failed: {exc.__class__.__name__}"
    db.flush()
    return run
