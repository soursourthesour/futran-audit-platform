"""Claude-assisted law refresh (schematic D5). Claude researches with web search and proposes changes;
an Admin accepts or rejects each one; accepted changes publish as a new matrix version (origin 'claude')."""
import json
import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field, HttpUrl, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.config import Settings
from app.core.errors import Invalid
from app.laws.importer import FEATURE_LABELS, FEATURES, TYPES
from app.laws.models import LawRefreshRun, MatrixVersion, Regulation, RegulationProposal
from app.laws.publish import current_regulations
from app.laws.service import EDITABLE, add_law, new_manual_version
from app.reference.models import Jurisdiction
from app.tenancy.models import User


class ClaudeClient(Protocol):
    def research(self, prompt: str) -> str: ...


class AnthropicClaudeClient:
    def __init__(self, settings: Settings):
        import anthropic

        self.settings = settings
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def research(self, prompt: str) -> str:
        msg = self.client.messages.create(
            model=self.settings.claude_model,
            max_tokens=8000,
            tools=[{"type": self.settings.claude_web_search_tool, "name": "web_search", "max_uses": 8}],
            messages=[{"role": "user", "content": prompt}],
        )
        return "\n".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")


def default_factory(settings: Settings) -> ClaudeClient:
    return AnthropicClaudeClient(settings)


class SourceIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl


class ProposalIn(BaseModel):
    change_type: Literal["add", "update", "retire"]
    regulation_id: str | None = None
    fields: dict = {}
    rationale: str = Field(min_length=1, max_length=4000)
    sources: list[SourceIn] = Field(min_length=1)


PROMPT = """You maintain Futran Solutions' AI law matrix for {name} ({code}). Today is {today}.

Below are the laws currently recorded for {name}, as JSON. Research what has changed since they were recorded:
new AI-relevant laws, regulations, executive actions or significant pending bills; changes to status, effective
dates, obligations or enforcement; and laws repealed, struck down or superseded. Focus on obligations for
organizations that use AI (deployers). Use primary sources (legislature, regulator, official gazette) where possible.

Current entries:
{current}

Reply with a JSON array inside a ```json fenced block, and nothing after it. Each item:
{{"change_type": "add" | "update" | "retire",
  "regulation_id": "<id from the current entries; required for update and retire>",
  "fields": {{ only for add/update; any of: {fields} }},
  "rationale": "<one or two plain sentences: what changed and when>",
  "sources": [{{"title": "<publisher and page title>", "url": "<https URL>"}}]}}
Use feature values from: {features}. Use type values from: {types}.
Every item needs at least one source URL. If nothing has changed, reply with ```json [] ```."""


def _current_payload(regs: list[Regulation]) -> str:
    return json.dumps(
        [
            {"id": r.id, "short_name": r.short_name, "feature": r.feature, "type": r.type, "obligations": r.obligations_text or r.full_text, "developments": r.developments_text, "verify": r.verify_flag}
            for r in regs
        ],
        ensure_ascii=False,
        indent=1,
    )


def _extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        start, end = text.find("["), text.rfind("]")
        raw = text[start : end + 1] if start != -1 and end > start else None
    if raw is None:
        raise ValueError("The reply contained no JSON array.")
    return json.loads(raw)


BOOL_FIELDS = {"verify_flag", "public_summary"}


def _field_problem(fields: dict) -> str | None:
    """Claude's fields must fit the columns they land in."""
    for k, v in fields.items():
        if k in BOOL_FIELDS:
            if not isinstance(v, bool):
                return f"{k} is not true or false"
            continue
        if v is None:
            continue
        if not isinstance(v, str):
            return f"{k} is not text"
        length = getattr(Regulation.__table__.columns[k].type, "length", None)
        if length and len(v) > length:
            return f"{k} is longer than {length} characters"
    return None


STALE_AFTER_HOURS = 2


def fail_stale_runs(db: Session) -> None:
    """A run still 'running' long after it started was cut off by a restart; say so instead of spinning forever."""
    from datetime import timedelta

    cutoff = utcnow() - timedelta(hours=STALE_AFTER_HOURS)
    for run in db.scalars(select(LawRefreshRun).where(LawRefreshRun.status == "running", LawRefreshRun.created_at < cutoff)):
        run.status, run.error, run.finished_at = "failed", "The run was interrupted before it finished (the server restarted). Start it again.", utcnow()


def run_refresh(
    db: Session,
    actor: User,
    jurisdiction_ids: list[str],
    client: ClaudeClient,
    model: str | None = None,
    run: LawRefreshRun | None = None,
    commit=None,
) -> LawRefreshRun:
    """Research each jurisdiction in turn. `commit` (when given) is called before every network call so no database
    transaction stays open while Claude researches; proposals for finished jurisdictions are kept if a later one fails."""
    if run is None:
        run = LawRefreshRun(jurisdiction_ids=jurisdiction_ids, requested_by=actor.id, model=model, status="running", warnings=[])
        db.add(run)
        db.flush()
    warnings: list[str] = []
    current = current_regulations(db)
    created = 0
    try:
        for jid in jurisdiction_ids:
            j = db.get(Jurisdiction, jid)
            if j is None:
                warnings.append(f"Jurisdiction {jid} not found.")
                continue
            regs = [r for r in current if r.jurisdiction_id == j.id]
            valid_ids = {r.id for r in regs}
            prompt = PROMPT.format(
                name=j.name, code=j.code, today=today().isoformat(), current=_current_payload(regs),
                fields=", ".join(EDITABLE), features=", ".join(FEATURES), types=", ".join(TYPES),
            )
            if commit is not None:
                commit()
            reply = client.research(prompt)
            try:
                items = _extract_json(reply)
            except (ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Claude's reply for {j.name} was not valid JSON: {exc}") from exc
            if not isinstance(items, list):
                raise RuntimeError(f"Claude's reply for {j.name} was not a JSON array.")
            for i, item in enumerate(items, start=1):
                try:
                    p = ProposalIn.model_validate(item)
                except ValidationError as exc:
                    reason = "it has no source" if any(e["loc"][:1] == ("sources",) for e in exc.errors()) else exc.errors()[0]["msg"]
                    warnings.append(f"{j.name}, item {i}: skipped because {reason}.")
                    continue
                if p.change_type in ("update", "retire") and p.regulation_id not in valid_ids:
                    warnings.append(f"{j.name}, item {i}: skipped because it refers to a law that is not in the matrix.")
                    continue
                fields = {k: v for k, v in p.fields.items() if k in EDITABLE}
                problem = _field_problem(fields)
                if problem:
                    warnings.append(f"{j.name}, item {i}: skipped because {problem}.")
                    continue
                if p.change_type == "add" and not (fields.get("short_name") or "").strip():
                    warnings.append(f"{j.name}, item {i}: skipped because a new law needs a short name.")
                    continue
                if fields.get("feature") and fields["feature"] not in FEATURES:
                    fields["feature"] = "government_other"
                if fields.get("type") and fields["type"] not in TYPES:
                    fields.pop("type")
                db.add(RegulationProposal(
                    run_id=run.id, jurisdiction_id=j.id, regulation_id=p.regulation_id, change_type=p.change_type,
                    proposed=fields, rationale=p.rationale, sources=[{"title": s.title, "url": str(s.url)} for s in p.sources],
                ))
                created += 1
        run.status = "completed"
    except Exception as exc:  # a failed run is recorded, never half-applied: proposals only exist until reviewed
        run.status = "failed"
        run.error = str(exc)[:2000]
    run.warnings = warnings
    run.finished_at = utcnow()
    audit.record(db, actor_id=actor.id, action="law_refresh.run", object_type="LawRefreshRun", object_id=run.id, organization_id=actor.organization_id, summary=f"Law update run {run.status}: {created} proposals")
    db.flush()
    return run


def accept_proposals(db: Session, actor: User, accept: list[str], reject: list[str]) -> MatrixVersion | None:
    now = utcnow()
    version = None
    for pid in reject:
        p = db.get(RegulationProposal, pid)
        if p and p.status == "pending":
            p.status, p.reviewed_by, p.reviewed_at = "rejected", actor.id, now
    to_apply = [db.get(RegulationProposal, pid) for pid in accept]
    to_apply = [p for p in to_apply if p is not None and p.status == "pending"]
    if not to_apply:
        return None
    version = new_manual_version(db, actor, f"Claude law updates — {len(to_apply)} accepted")
    version.origin = "claude"
    for p in to_apply:
        j = db.get(Jurisdiction, p.jurisdiction_id)
        if p.change_type == "add":
            add_law(db, actor, j.code, dict(p.proposed), version=version, origin="claude")
        elif p.change_type == "update":
            old = db.get(Regulation, p.regulation_id)
            if old is None or old.superseded_by_id or old.retired_in_version_id:
                raise Invalid(f"The law '{old.short_name if old else p.regulation_id}' changed after this proposal was made. Run the update again.")
            data = {c.key: getattr(old, c.key) for c in Regulation.__table__.columns if c.key not in ("id", "created_at", "superseded_by_id", "retired_in_version_id")}
            data.update({k: v for k, v in p.proposed.items() if k in EDITABLE})
            data.update(matrix_version_id=version.id, last_seen_version_id=version.id, origin="claude", updated_by=actor.id)
            new = Regulation(**data)
            db.add(new)
            db.flush()
            old.superseded_by_id = new.id
            from app.laws.publish import carry_forward

            carry_forward(db, old.id, new.id)
        elif p.change_type == "retire":
            old = db.get(Regulation, p.regulation_id)
            if old is None or old.superseded_by_id or old.retired_in_version_id:
                raise Invalid(f"The law '{old.short_name if old else p.regulation_id}' changed after this proposal was made. Run the update again.")
            old.retired_in_version_id = version.id
        p.status, p.reviewed_by, p.reviewed_at = "accepted", actor.id, now
    for old_v in db.scalars(select(MatrixVersion).where(MatrixVersion.status == "published", MatrixVersion.id != version.id)):
        old_v.status = "superseded"
    version.status = "published"
    audit.record(db, actor_id=actor.id, action="law_refresh.accept", object_type="MatrixVersion", object_id=version.id, organization_id=actor.organization_id, summary=f"Accepted {len(to_apply)} Claude law updates")
    db.flush()
    return version


def feature_label(f: str) -> str:
    return FEATURE_LABELS.get(f, f)
