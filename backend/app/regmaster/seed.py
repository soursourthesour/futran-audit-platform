"""Load the regulatory master seed (`seeds/regmaster.yaml`): role catalogue, source allowlist, and the cited
requirements, scope tests, role maps and committee rules of each named law. Content already present on a law's
current version is never overwritten, so approved changes survive a re-run."""
import re
from datetime import date
from urllib.parse import urlparse

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.laws.importer import SEEDS
from app.laws.models import MatrixVersion, Regulation
from app.reference.models import Jurisdiction
from app.regmaster.models import CommitteeRule, LawRoleMap, LawVersion, Requirement, RoleCatalog, ScopeTest, Source
from app.regmaster.versioning import clone_version, first_version

SEED_FILE = SEEDS / "regmaster.yaml"


def _data() -> dict:
    return yaml.safe_load(SEED_FILE.read_text(encoding="utf-8"))


def domain_of(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def load_roles(db: Session, data: dict | None = None) -> int:
    data = data or _data()
    have = {r.code: r for r in db.scalars(select(RoleCatalog))}
    for r in data["roles"]:
        row = have.get(r["code"]) or RoleCatalog(code=r["code"])
        for k in ("number", "name", "level", "default_stage", "main_sources", "description", "extra_checks", "headline_code"):
            if r.get(k) is not None or k in ("extra_checks", "headline_code"):
                if row.id is None or getattr(row, k) is None:
                    setattr(row, k, r.get(k))
        db.add(row)
    db.flush()
    return len(data["roles"])


def _jurisdiction(db: Session, code: str | None) -> Jurisdiction | None:
    return db.scalar(select(Jurisdiction).where(Jurisdiction.code == code)) if code else None


def load_sources(db: Session, data: dict | None = None) -> int:
    data = data or _data()
    have = {s.url: s for s in db.scalars(select(Source).where(Source.regulation_id.is_(None)))}
    n = 0
    for s in data["sources"]:
        if s["url"] in have:
            continue
        j = _jurisdiction(db, s.get("jurisdiction"))
        db.add(Source(jurisdiction_id=j.id if j else None, name=s["name"], url=s["url"], domain=domain_of(s["url"]), kind=s.get("kind", "official")))
        n += 1
    db.flush()
    return n


def ensure_versions(db: Session) -> int:
    """Every current law has an approved version. A law the matrix import replaced carries its predecessor's
    content forward; a new law gets version 1 from its matrix fields."""
    made = 0
    live = (Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None))
    missing = list(db.scalars(select(Regulation).where(*live, Regulation.current_version_id.is_(None))))
    # a row copied from its predecessor (Reference data edit, accepted law update) still points at the old law's version
    borrowed = {r.id: r.current_version_id for r in db.scalars(select(Regulation).join(LawVersion, LawVersion.id == Regulation.current_version_id).where(*live, LawVersion.regulation_id != Regulation.id))}
    missing += [db.get(Regulation, rid) for rid in borrowed]
    if not missing:
        return 0
    preds = {r.superseded_by_id: r for r in db.scalars(select(Regulation).where(Regulation.superseded_by_id.in_([m.id for m in missing]), Regulation.current_version_id.is_not(None)))}
    for reg in missing:
        prev = preds.get(reg.id)
        base_id = borrowed.get(reg.id) or (prev.current_version_id if prev is not None else None)
        if base_id is not None and (old := db.get(LawVersion, base_id)) is not None:
            new = clone_version(db, old, regulation_id=reg.id, summary="Law matrix re-import: content carried forward")
            new.approved_at = utcnow()
            reg.current_version_id = new.id
            for k in ("binding", "topics", "region", "reviewer_id", "review_due_on", "refresh_every_days", "watch"):
                if prev is not None and getattr(reg, k) is None:
                    setattr(reg, k, getattr(prev, k))
        else:
            first_version(db, reg, flush=False)
        made += 1
    db.flush()
    return made


def find_law(db: Session, code: str, pattern: str) -> Regulation | None:
    j = _jurisdiction(db, code)
    if j is None:
        return None
    rx = re.compile(pattern, re.I)
    regs = db.scalars(select(Regulation).where(Regulation.jurisdiction_id == j.id, Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None)).order_by(Regulation.created_at))
    return next((r for r in regs if rx.search(r.short_name or "")), None)


def _create_law(db: Session, code: str, spec: dict) -> Regulation | None:
    j = _jurisdiction(db, code)
    if j is None:
        return None
    mv = db.scalar(select(MatrixVersion).order_by(MatrixVersion.published_at.desc()).limit(1))
    if mv is None:
        mv = MatrixVersion(label="Regulatory master seed", origin="manual")
        db.add(mv)
        db.flush()
    reg = Regulation(jurisdiction_id=j.id, matrix_version_id=mv.id, last_seen_version_id=mv.id, origin="manual", **spec)
    db.add(reg)
    j.has_laws = True
    db.flush()
    first_version(db, reg)
    return reg


def _date(v):
    return v if isinstance(v, date) or v is None else date.fromisoformat(str(v))


def _populated(db: Session, version_id: str) -> bool:
    return any(db.scalar(select(m.id).where(m.law_version_id == version_id).limit(1)) for m in (Requirement, LawRoleMap, ScopeTest))


def _apply_law(db: Session, reg: Regulation, law: dict, roles: dict[str, RoleCatalog]) -> bool:
    for k in ("label", "region", "binding", "topics"):
        if getattr(reg, k) is None and law.get(k) is not None:
            setattr(reg, k, law[k])
    v = db.get(LawVersion, reg.current_version_id)
    if _populated(db, v.id):
        return False
    spec = law.get("version", {})
    sources = []
    for s in spec.get("sources", []):
        src = db.scalar(select(Source).where(Source.regulation_id == reg.id, Source.url == s["url"]))
        if src is None:
            src = Source(jurisdiction_id=reg.jurisdiction_id, regulation_id=reg.id, name=s["name"], url=s["url"], domain=domain_of(s["url"]), kind=s.get("kind", "official"), last_read_at=utcnow())
            db.add(src)
            db.flush()
        sources.append(src)
    for k in ("status", "effective_text", "scope_text", "applies_to", "enforcer", "private_right_of_action", "penalty_text", "cure_period", "exemptions_text", "removed_text", "litigation_text", "main_duty", "change_summary"):
        if k in spec:
            setattr(v, k, spec[k])
    for k in ("signed_on", "effective_on", "compliance_on"):
        if k in spec:
            setattr(v, k, _date(spec[k]))
    v.verify_flag = bool(spec.get("verify", False))
    v.source_ids = [s.id for s in sources]
    v.approved_at = v.approved_at or utcnow()
    for i, t in enumerate(law.get("scope_tests", []), start=1):
        rule = dict(t.get("rule") or {})
        if t.get("prefill_codes"):
            rule["codes"] = t["prefill_codes"]
        if t.get("prefill_feature"):
            rule["feature"] = t["prefill_feature"]
        db.add(ScopeTest(law_version_id=v.id, order=i, question_text=t["question"], answer_type=t.get("answer_type", "yes_no"), in_scope_rule=rule, decisive=t.get("decisive", True), prefill_from=t.get("prefill"), note=t.get("note")))
    by_code: dict[str, Requirement] = {}
    for i, r in enumerate(law.get("requirements", []), start=1):
        src = sources[r["source"]] if r.get("source") is not None and r["source"] < len(sources) else None
        req = Requirement(
            law_version_id=v.id, code=r["code"], order=i, text=r["text"], applies_to=r.get("applies_to"), needed_by_stage=r.get("needed_by"),
            evidence_text=r.get("evidence"), role_id=roles[r["role"]].id if r.get("role") else None, ai_types=r.get("ai_types"),
            citation=r.get("citation"), source_quote=r.get("quote"), source_id=src.id if src else None, source_url=src.url if src else None,
            verify_flag=bool(r.get("verify", False)),
        )
        db.add(req)
        by_code[r["code"]] = req
    db.flush()
    for m in law.get("role_maps", []):
        db.add(LawRoleMap(law_version_id=v.id, role_id=roles[m["role"]].id, level=m["level"], needed_by_stage=m.get("needed_by"), applies_to=m.get("applies_to"), requirement_ids=[by_code[c].id for c in m.get("requirements", [])], basis_text=m.get("basis"), verify_flag=bool(m.get("verify", False))))
    for c in law.get("committees", []):
        db.add(CommitteeRule(law_version_id=v.id, committee_type=c["type"], level=c["level"], title=c.get("title"), composition_text=c.get("composition"), cadence=c.get("cadence"), triggers_text=c.get("triggers"), condition_text=c.get("condition"), basis_text=c.get("basis"), items=c.get("items")))
    db.flush()
    return True


def seed_regmaster(db: Session) -> str:
    data = _data()
    load_roles(db, data)
    load_sources(db, data)
    ensure_versions(db)
    roles = {r.code: r for r in db.scalars(select(RoleCatalog))}
    filled, missing = 0, []
    for law in data["laws"]:
        reg = find_law(db, law["jurisdiction"], law["match"])
        if reg is None and law.get("create"):
            reg = _create_law(db, law["jurisdiction"], law["create"])
        if reg is None:
            missing.append(law["key"])
            continue
        filled += _apply_law(db, reg, law, roles)
    db.flush()
    note = f"; not found in the law library: {', '.join(missing)}" if missing else ""
    return f"{len(roles)} roles, {filled} laws filled{note}"
