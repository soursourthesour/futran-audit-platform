"""Proposed changes to the regulatory master and their approval (spec §25.1, §25.3 steps 5 and 7, §25.7).

`propose` records a change against the current approved version (nothing live changes) and computes its impact.
`apply_changes` is what an approval does: one new LawVersion per law carrying every approved change, with
requirements, role maps, scope tests and committee rules copied forward; then affected clients are re-run.
The refresh review queue (M3, WS-D) calls `apply_changes`; `needs_second_review` is its rule for low-confidence and
new-law items.
"""
import hashlib
import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid
from app.laws.models import MatrixVersion, Regulation
from app.reference.models import Jurisdiction
from app.regmaster.models import (
    AI_TYPES, APPLIES_TO, STAGES, VERSION_STATUSES, ChangeImpact, ClientLawApplicability, CommitteeRule, IntroLetter, LawRoleMap,
    LawVersion, ProposedChange, Requirement, RoleCatalog, ScopeTest, Source,
)
from app.regmaster.versioning import VERSION_FIELDS, clone_version

REG_FIELDS = {"short_name", "citation", "type", "binding", "topics", "label", "region"}
LAW_FIELDS = set(VERSION_FIELDS) - {"source_ids"} | REG_FIELDS
DATE_FIELDS = {"signed_on", "effective_on", "compliance_on", "repealed_on"}
ORIGINS = {"admin_edit", "bulk_edit", "auditor_suggestion", "claude_draft", "claude_refresh"}
CHANGE_TYPES = {"new_law", "amendment", "effective_date", "new_rule", "guidance", "role_mapping", "repeal", "enforcement"}
OPEN = ("pending", "held", "legal_review")


def _bad(field: str, message: str):
    raise Invalid(errors=[{"field": field, "message": message}])


def _role(db: Session, code: str | None) -> RoleCatalog | None:
    if not code:
        return None
    r = db.scalar(select(RoleCatalog).where(RoleCatalog.code == code))
    if r is None:
        _bad("new_value.role", f"Unknown role {code}.")
    return r


def _jsonable(v):
    return v.isoformat() if isinstance(v, date) else v


def current_value(db: Session, reg: Regulation | None, field_path: str):
    """The value the change would replace, from the current approved version."""
    if reg is None:
        return None
    v = db.get(LawVersion, reg.current_version_id) if reg.current_version_id else None
    head, _, key = field_path.partition(".")
    if head == "law":
        return _jsonable(getattr(reg, key)) if key in REG_FIELDS else (_jsonable(getattr(v, key)) if v else None)
    if v is None:
        return None
    if head == "requirement":
        r = db.scalar(select(Requirement).where(Requirement.law_version_id == v.id, Requirement.code == key))
        return requirement_out(db, r) if r else None
    if head == "role_map":
        role = db.scalar(select(RoleCatalog).where(RoleCatalog.code == key))
        m = db.scalar(select(LawRoleMap).where(LawRoleMap.law_version_id == v.id, LawRoleMap.role_id == role.id)) if role else None
        return {"level": m.level, "needed_by_stage": m.needed_by_stage, "basis_text": m.basis_text} if m else None
    if head == "scope_test":
        t = db.scalar(select(ScopeTest).where(ScopeTest.law_version_id == v.id, ScopeTest.order == int(key)))
        return {"question_text": t.question_text, "answer_type": t.answer_type, "in_scope_rule": t.in_scope_rule, "prefill_from": t.prefill_from} if t else None
    if head == "committee":
        c = db.scalar(select(CommitteeRule).where(CommitteeRule.law_version_id == v.id, CommitteeRule.committee_type == key))
        return {"level": c.level, "title": c.title, "items": c.items} if c else None
    if head == "repeal":
        return v.status
    return None


def requirement_out(db: Session, r: Requirement) -> dict:
    role = db.get(RoleCatalog, r.role_id) if r.role_id else None
    return {
        "id": r.id, "code": r.code, "text": r.text, "applies_to": r.applies_to or [], "needed_by_stage": r.needed_by_stage, "evidence_text": r.evidence_text,
        "role": role.code if role else None, "role_name": role.name if role else None, "ai_types": r.ai_types or [], "citation": r.citation,
        "source_quote": r.source_quote, "source_url": r.source_url, "verify_flag": r.verify_flag,
    }


def _validate(db: Session, field_path: str, value) -> None:
    head, _, key = field_path.partition(".")
    if field_path in ("new_law", "repeal"):
        if field_path == "repeal" and isinstance(value, dict) and value.get("effective_on"):
            try:
                date.fromisoformat(str(value["effective_on"])[:10])
            except ValueError:
                _bad("new_value.effective_on", "Use a date (YYYY-MM-DD) for when the repeal takes effect.")
        if field_path == "new_law":
            if not isinstance(value, dict) or not (value.get("short_name") or "").strip() or not value.get("jurisdiction_code"):
                _bad("new_value", "A new law needs a geography and a short name.")
            if db.scalar(select(Jurisdiction).where(Jurisdiction.code == str(value["jurisdiction_code"]).upper())) is None:
                _bad("new_value.jurisdiction_code", "Unknown geography.")
        return
    if head == "law":
        if key not in LAW_FIELDS:
            _bad("field_path", f"{key} is not a law field that can change.")
        if key == "status" and value not in VERSION_STATUSES + ["pending"]:
            _bad("new_value", "Choose a valid status.")
        if key in DATE_FIELDS and value:
            try:
                date.fromisoformat(str(value))
            except ValueError:
                _bad("new_value", "Use a date (YYYY-MM-DD).")
        if key == "applies_to" and (not isinstance(value, list) or any(a not in APPLIES_TO for a in value)):
            _bad("new_value", "Choose who the law applies to.")
        return
    if head == "requirement":
        if value is None:
            return
        if not isinstance(value, dict) or not (value.get("text") or "").strip():
            _bad("new_value.text", "Write the requirement.")
        if not (value.get("citation") or "").strip() or not (value.get("source_quote") or "").strip():
            _bad("new_value.source_quote", "Every requirement needs a citation and a quote from its source.")
        _role(db, value.get("role"))
        if value.get("needed_by_stage") and value["needed_by_stage"] not in STAGES:
            _bad("new_value.needed_by_stage", "Choose a stage.")
        if any(t not in AI_TYPES for t in value.get("ai_types") or []):
            _bad("new_value.ai_types", "Unknown AI type.")
        return
    if head == "role_map":
        _role(db, key)
        if value is not None and (not isinstance(value, dict) or value.get("level") not in ("required", "recommended", "not_required")):
            _bad("new_value.level", "Choose required, recommended or not required.")
        return
    if head == "scope_test":
        if not key.isdigit():
            _bad("field_path", "Scope tests are numbered.")
        if value is not None and not (isinstance(value, dict) and (value.get("question_text") or "").strip()):
            _bad("new_value.question_text", "Write the question.")
        return
    if head == "committee":
        if value is not None and (not isinstance(value, dict) or value.get("level") not in ("required", "recommended")):
            _bad("new_value.level", "Choose required or recommended.")
        return
    _bad("field_path", "Unknown kind of change.")


def _dedupe_key(regulation_id, field_path, value) -> str:
    raw = json.dumps([regulation_id, field_path, value], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def norm_name(text: str | None) -> str:
    """Case, punctuation and spacing do not make a different law or case ("Utah AI Policy Act." = "utah ai policy act")."""
    return " ".join("".join(ch if ch.isalnum() else " " for ch in (text or "").casefold()).split())


def law_identity(jurisdiction_code: str | None, short_name: str | None, citation: str | None) -> set[str]:
    """A new law is the same law as another in the same geography with the same short name or the same citation."""
    j = str(jurisdiction_code or "").upper()
    return {f"{j}|{kind}|{n}" for kind, n in (("name", norm_name(short_name)), ("cite", norm_name(citation))) if n}


def same_new_law(db: Session, value: dict, statuses) -> ProposedChange | None:
    """A new-law proposal in these statuses for the same law, whatever its free text says."""
    want = law_identity(value.get("jurisdiction_code"), value.get("short_name"), value.get("citation"))
    for pc in db.scalars(select(ProposedChange).where(ProposedChange.field_path == "new_law", ProposedChange.status.in_(statuses)).order_by(ProposedChange.created_at)):
        v = pc.new_value if isinstance(pc.new_value, dict) else {}
        if want & law_identity(v.get("jurisdiction_code"), v.get("short_name"), v.get("citation")):
            return pc
    return None


def law_in_library(db: Session, value: dict) -> Regulation | None:
    """The current law in the library that a new-law proposal duplicates (same geography, name or citation)."""
    from app.laws.publish import current_regulations

    code = str(value.get("jurisdiction_code") or "").upper()
    j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == code))
    if j is None:
        return None
    want = law_identity(code, value.get("short_name"), value.get("citation"))
    return next((r for r in current_regulations(db) if r.jurisdiction_id == j.id and want & law_identity(code, r.short_name, r.citation)), None)


def dedupe_keys(db: Session, regulation_id: str | None, field_path: str, value) -> list[str]:
    """The same change proposed against any row of the law (a Reference data edit replaces the row)."""
    from app.laws.publish import chain_ids

    return [_dedupe_key(i, field_path, value) for i in (chain_ids(db, regulation_id) or [regulation_id])]


def propose(
    db: Session, *, actor_id: str | None, regulation_id: str | None, field_path: str, new_value, summary: str, origin: str,
    change_type: str = "amendment", reason: str | None = None, source_url: str | None = None, source_quote: str | None = None,
    confidence: str = "high", batch_id: str | None = None, refresh_run_id: str | None = None, jurisdiction_id: str | None = None,
) -> ProposedChange:
    if origin not in ORIGINS:
        _bad("origin", "Unknown origin.")
    if change_type not in CHANGE_TYPES:
        _bad("change_type", "Unknown change type.")
    if not (summary or "").strip():
        _bad("summary", "Say what changes.")
    from app.laws.publish import current_version_of

    reg = current_version_of(db, regulation_id) if regulation_id else None  # a stale id from an open screen lands on the live row
    if regulation_id and reg is None:
        _bad("regulation_id", "Unknown law.")
    regulation_id = reg.id if reg is not None else None
    if reg is None and field_path != "new_law":
        _bad("regulation_id", "Choose the law this change is for.")
    if origin in ("auditor_suggestion", "claude_refresh", "claude_draft") and not ((source_url or "").strip() and (source_quote or "").strip()):
        _bad("source_url", "A suggestion needs the source link and the quoted passage it relies on.")
    _validate(db, field_path, new_value)
    key = _dedupe_key(regulation_id, field_path, new_value)
    dup = db.scalar(select(ProposedChange).where(ProposedChange.dedupe_key.in_(dedupe_keys(db, regulation_id, field_path, new_value)), ProposedChange.status.in_(OPEN)).limit(1))
    if dup is None and field_path == "new_law":
        dup = same_new_law(db, new_value, OPEN)  # the same law in other words
    if dup is not None:
        return dup
    src = None
    if source_url:
        from app.regmaster.seed import allowlisted_source

        src = allowlisted_source(db, source_url)
        if src is None:
            confidence = "low" if origin in ("claude_refresh", "claude_draft") else confidence
    if reg is not None and jurisdiction_id is None:
        jurisdiction_id = reg.jurisdiction_id
    if field_path == "new_law" and jurisdiction_id is None:
        j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == str(new_value["jurisdiction_code"]).upper()))
        jurisdiction_id = j.id
    pc = ProposedChange(
        origin=origin, batch_id=batch_id, refresh_run_id=refresh_run_id, change_type=change_type, regulation_id=regulation_id,
        jurisdiction_id=jurisdiction_id, base_version_id=reg.current_version_id if reg else None, field_path=field_path,
        old_value=current_value(db, reg, field_path), new_value=new_value, summary=summary.strip()[:1000], reason=(reason or None),
        source_id=src.id if src else None, source_url=source_url, source_quote=source_quote, confidence=confidence, dedupe_key=key,
        proposed_by=actor_id,
    )
    db.add(pc)
    db.flush()
    compute_impacts(db, pc)
    return pc


def needs_second_review(pc: ProposedChange) -> bool:
    return pc.confidence == "low" or pc.change_type == "new_law"


# ------------------------------------------------------------------ impact

def compute_impacts(db: Session, pc: ProposedChange) -> list[ChangeImpact]:
    for old in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == pc.id)):
        db.delete(old)
    if pc.regulation_id is None:
        return []
    from app.laws.publish import chain_ids

    ids = chain_ids(db, pc.regulation_id) or [pc.regulation_id]
    orgs = list(dict.fromkeys(db.scalars(select(ClientLawApplicability.organization_id).where(ClientLawApplicability.regulation_id.in_(ids), ClientLawApplicability.in_scope.is_(True), ClientLawApplicability.deleted_at.is_(None)))))
    head, _, key = pc.field_path.partition(".")
    roles: list[str] = []
    if head == "role_map":
        roles = [key]
    elif head == "requirement" and isinstance(pc.new_value, dict) and pc.new_value.get("role"):
        roles = [pc.new_value["role"]]
    out = []
    for org_id in orgs:
        systems: list[str] = []
        try:
            from app.register.models import RegisterSystemLaw

            systems = list(db.scalars(select(RegisterSystemLaw.register_system_id).where(RegisterSystemLaw.organization_id == org_id, RegisterSystemLaw.regulation_id.in_(ids), RegisterSystemLaw.deleted_at.is_(None))))
        except Exception:  # register not installed in this build
            systems = []
        letter = db.scalar(select(IntroLetter.id).where(IntroLetter.organization_id == org_id, IntroLetter.status == "sent", IntroLetter.deleted_at.is_(None)).limit(1))
        imp = ChangeImpact(proposed_change_id=pc.id, organization_id=org_id, ai_system_ids=systems, roles_affected=roles, letter_update_needed=letter is not None, summary=pc.summary[:600])
        db.add(imp)
        out.append(imp)
    db.flush()
    return out


# ------------------------------------------------------------------ approval

def _apply_one(db: Session, reg: Regulation, v: LawVersion, pc: ProposedChange, value) -> None:
    head, _, key = pc.field_path.partition(".")
    if pc.field_path == "repeal":
        on = value.get("effective_on") if isinstance(value, dict) else None
        v.status, v.repealed_on = "repealed", date.fromisoformat(str(on)[:10]) if on else None  # in force until then
        return
    if head == "law":
        if key in REG_FIELDS:
            setattr(reg, key, value)
        else:
            setattr(v, key, date.fromisoformat(value) if key in DATE_FIELDS and value else value)
        return
    if head == "requirement":
        row = db.scalar(select(Requirement).where(Requirement.law_version_id == v.id, Requirement.code == key))
        if value is None:
            if row is not None:
                for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == v.id)):
                    if row.id in (m.requirement_ids or []):
                        m.requirement_ids = [i for i in m.requirement_ids if i != row.id]
                db.delete(row)
            return
        if row is None:
            n = len(db.scalars(select(Requirement.id).where(Requirement.law_version_id == v.id)).all())
            row = Requirement(law_version_id=v.id, code=key, order=n + 1)
            db.add(row)
        role = _role(db, value.get("role")) if "role" in value else None
        row.text = value["text"]
        for k in ("applies_to", "needed_by_stage", "evidence_text", "ai_types", "citation", "source_quote", "source_url"):
            if k in value:
                setattr(row, k, value[k])
        if "role" in value:
            row.role_id = role.id if role else None
        row.verify_flag = bool(value.get("verify_flag", False))
        return
    if head == "role_map":
        role = _role(db, key)
        m = db.scalar(select(LawRoleMap).where(LawRoleMap.law_version_id == v.id, LawRoleMap.role_id == role.id))
        if value is None or value.get("level") == "not_required":
            if m is not None:
                db.delete(m)
            return
        if m is None:
            m = LawRoleMap(law_version_id=v.id, role_id=role.id, level=value["level"], requirement_ids=[])
            db.add(m)
        m.level = value["level"]
        m.needed_by_stage = value.get("needed_by_stage") or m.needed_by_stage or role.default_stage
        if "basis_text" in value:
            m.basis_text = value["basis_text"]
        if "requirement_codes" in value:
            reqs = db.scalars(select(Requirement).where(Requirement.law_version_id == v.id, Requirement.code.in_(value["requirement_codes"] or [])))
            m.requirement_ids = [r.id for r in reqs]
        return
    if head == "scope_test":
        t = db.scalar(select(ScopeTest).where(ScopeTest.law_version_id == v.id, ScopeTest.order == int(key)))
        if value is None:
            if t is not None:
                db.delete(t)
            return
        if t is None:
            t = ScopeTest(law_version_id=v.id, order=int(key), question_text=value["question_text"])
            db.add(t)
        for k in ("question_text", "answer_type", "in_scope_rule", "prefill_from", "decisive", "note"):
            if k in value:
                setattr(t, k, value[k])
        return
    if head == "committee":
        c = db.scalar(select(CommitteeRule).where(CommitteeRule.law_version_id == v.id, CommitteeRule.committee_type == key))
        if value is None:
            if c is not None:
                db.delete(c)
            return
        if c is None:
            c = CommitteeRule(law_version_id=v.id, committee_type=key, level=value["level"])
            db.add(c)
        for k in ("level", "title", "composition_text", "cadence", "triggers_text", "condition_text", "basis_text", "items"):
            if k in value:
                setattr(c, k, value[k])


def _create_new_law(db: Session, pc: ProposedChange, value: dict, reviewer_id: str) -> LawVersion:
    j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == str(value["jurisdiction_code"]).upper()))
    have = law_in_library(db, value)
    if have is not None:
        raise Conflict(f"{have.short_name} is already in the law library for {j.name}. Reject this proposal, or propose a change to that law instead.")
    mv = db.scalar(select(MatrixVersion).order_by(MatrixVersion.published_at.desc()).limit(1))
    if mv is None:
        mv = MatrixVersion(label="Regulatory master", origin="manual")
        db.add(mv)
        db.flush()
    reg = Regulation(
        jurisdiction_id=j.id, matrix_version_id=mv.id, last_seen_version_id=mv.id, origin="manual", updated_by=reviewer_id,
        short_name=value["short_name"].strip()[:200], citation=(value.get("citation") or None), type=value.get("type") or "statute",
        feature=value.get("feature") or "government_other", binding=value.get("binding"), topics=value.get("topics"), label=value.get("label"),
        region=value.get("region"), full_text=value.get("full_text") or value["short_name"], applies_to="deployer",
    )
    db.add(reg)
    j.has_laws = True
    db.flush()
    spec = value.get("version") or {}
    v = LawVersion(regulation_id=reg.id, version_no=1, change_summary=pc.summary, created_by=pc.proposed_by)
    for k in VERSION_FIELDS:
        if k in spec and k != "source_ids":
            setattr(v, k, date.fromisoformat(spec[k]) if k in DATE_FIELDS and spec[k] else spec[k])
    v.status = v.status or "in_force"
    db.add(v)
    db.flush()
    for i, t in enumerate(value.get("scope_tests") or [], start=1):
        db.add(ScopeTest(law_version_id=v.id, order=i, question_text=t["question_text"], answer_type=t.get("answer_type", "yes_no"), in_scope_rule=t.get("in_scope_rule"), prefill_from=t.get("prefill_from"), decisive=t.get("decisive", True)))
    sources = []
    for s in value.get("sources") or []:
        from app.regmaster.seed import domain_of

        src = Source(jurisdiction_id=j.id, regulation_id=reg.id, name=s.get("name") or s["url"], url=s["url"], domain=domain_of(s["url"]), kind=s.get("kind", "official"))
        db.add(src)
        sources.append(src)
    db.flush()
    v.source_ids = [s.id for s in sources]
    reg.current_version_id = v.id
    pc.regulation_id = reg.id
    return v


def _content(v):
    """A value as the reviewer sees it: row ids (which change when a version is copied forward) do not count."""
    if isinstance(v, dict):
        return {k: _content(x) for k, x in v.items() if k != "id"}
    if isinstance(v, list):
        return [_content(x) for x in v]
    return v


def _check_base(db: Session, reg: Regulation, pc: ProposedChange) -> None:
    """Refuse to overwrite a field that changed after the change was proposed (another approval, a Reference data edit
    or a re-import); a change to another field of the law since then does not matter."""
    if not pc.base_version_id or pc.base_version_id == reg.current_version_id:
        return
    if _content(current_value(db, reg, pc.field_path)) != _content(pc.old_value):
        raise Conflict(f"This change was proposed against an earlier version of {reg.short_name}, and {pc.field_path} has changed since. "
                       "Review it again against the current version: reject it and propose it again if it is still needed.")


def apply_changes(db: Session, items: list[ProposedChange], reviewer_id: str, edited: dict[str, object] | None = None, note: str | None = None) -> LawVersion | None:
    """Approve changes. Changes to one law become one new version. `edited` maps change id -> the value as edited
    by the reviewer (status `edited_approved`). Returns the last version written."""
    from app.regmaster import engine

    edited = edited or {}
    now = utcnow()
    last = None
    from app.laws.publish import current_version_of

    by_reg: dict[str | None, list[ProposedChange]] = {}
    for pc in items:
        if pc.status not in OPEN:
            raise Conflict(f"'{pc.summary[:80]}' has already been decided.")
        live = current_version_of(db, pc.regulation_id) if pc.regulation_id else None
        if pc.regulation_id and live is None:
            raise Conflict(f"'{pc.summary[:80]}': the law no longer exists.")
        by_reg.setdefault(live.id if live else None, []).append(pc)  # changes to any row of a law become one version of the live row
    touched: list[str] = []
    for reg_id, group in by_reg.items():
        if reg_id is None:
            for pc in group:
                value = edited.get(pc.id, pc.new_value)
                _validate(db, pc.field_path, value)
                v = _create_new_law(db, pc, value, reviewer_id)
                v.approved_by, v.approved_at = reviewer_id, now
                pc.status = "edited_approved" if pc.id in edited else "approved"
                pc.reviewer_id, pc.reviewed_at, pc.review_note, pc.applied_version_id = reviewer_id, now, note, v.id
                touched.append(v.regulation_id)
                last = v
            continue
        reg = db.get(Regulation, reg_id)
        for pc in group:
            _check_base(db, reg, pc)
        base = db.get(LawVersion, reg.current_version_id)
        v = clone_version(db, base, summary="; ".join(pc.summary for pc in group)[:2000], created_by=group[0].proposed_by)
        for pc in group:
            value = edited.get(pc.id, pc.new_value)
            _validate(db, pc.field_path, value)
            _apply_one(db, reg, v, pc, value)
            pc.status = "edited_approved" if pc.id in edited else "approved"
            pc.reviewer_id, pc.reviewed_at, pc.review_note, pc.applied_version_id = reviewer_id, now, note, v.id
        db.flush()
        v.approved_by, v.approved_at = reviewer_id, now
        reg.current_version_id = v.id
        touched.append(reg.id)
        last = v
    db.flush()
    for reg_id in dict.fromkeys(touched):
        engine.rerun_for_regulation(db, reg_id)
    return last


def decide(db: Session, pc: ProposedChange, status: str, reviewer_id: str, note: str | None = None) -> ProposedChange:
    """Hold, reject or send to legal review (approval goes through `apply_changes`)."""
    if status not in ("held", "rejected", "legal_review"):
        _bad("status", "Choose hold, reject or legal review.")
    if pc.status not in OPEN:
        raise Conflict("This change has already been decided.")
    pc.status, pc.reviewer_id, pc.reviewed_at, pc.review_note = status, reviewer_id, utcnow(), note
    db.flush()
    return pc
