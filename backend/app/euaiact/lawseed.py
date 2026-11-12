"""Seed EU AI Act requirements into the law library (spec B8: the regulatory master's international law sheet).

For each row under `library:` in `seeds/eu_ai_act.yaml`, the current version of the EU AI Act is checked for a
requirement that already covers the same article (by its citation). Covered rows are linked, never duplicated or
changed; missing rows are added with the next free EU-nn code and marked "verify". Idempotent. When the EU AI Act is
not in the law library at all, nothing is created: adding a law is the law library's own business."""
from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.euaiact import rules

log = logging.getLogger(__name__)
LAW_MATCH = ("EU", "2024/1689")  # the regulatory master seed's match for the EU AI Act


def eu_ai_act(db: Session):
    """(Regulation, LawVersion) of the EU AI Act's current approved version, or (None, None)."""
    from app.regmaster.models import LawVersion
    from app.regmaster.seed import find_law

    reg = find_law(db, *LAW_MATCH)
    if reg is None or reg.current_version_id is None:
        return None, None
    return reg, db.get(LawVersion, reg.current_version_id)


def _requirements(db: Session, version_id: str) -> list:
    from app.regmaster.models import Requirement

    return list(db.scalars(select(Requirement).where(Requirement.law_version_id == version_id).order_by(Requirement.order, Requirement.code)))


def _covering(reqs: list, ref: str):
    return next((r for r in reqs if any(rules.covers(e, ref) for e in rules.article_refs(r.citation))), None)


def library_row(db: Session, ref: str):
    """The EU AI Act requirement that covers an article reference, or None."""
    _reg, v = eu_ai_act(db)
    return _covering(_requirements(db, v.id), ref) if v is not None else None


def library_rows(db: Session) -> dict[str, object]:
    """{ref: Requirement} for every obligation in the data file that the library covers (one query for the workspace)."""
    _reg, v = eu_ai_act(db)
    if v is None:
        return {}
    reqs = _requirements(db, v.id)
    out = {}
    for o in rules.data()["obligations"]:
        r = _covering(reqs, o["ref"])
        if r is not None:
            out[o["ref"]] = r
    return out


def _next_code(taken: set[str]) -> str:
    n = max((int(m.group(1)) for c in taken if (m := re.fullmatch(r"EU-(\d+)", c or ""))), default=0) + 1
    while f"EU-{n:02d}" in taken:
        n += 1
    return f"EU-{n:02d}"


def ensure_requirements(db: Session, actor_id: str | None = None) -> dict:
    """Add the EU AI Act requirements the library lacks. Returns {"added": [...], "found": [...], "missing_law": bool}."""
    from app.audit_log import service as audit
    from app.regmaster.models import Requirement, RoleCatalog, Source

    reg, v = eu_ai_act(db)
    if v is None:
        return {"added": [], "found": [], "missing_law": True}
    reqs = _requirements(db, v.id)
    roles = {r.code: r.id for r in db.scalars(select(RoleCatalog))}
    eurlex = db.scalar(select(Source).where(Source.regulation_id == reg.id, Source.url.contains("eur-lex")).limit(1))
    taken = {r.code for r in reqs}
    order = max((r.order or 0 for r in reqs), default=0)
    added, found = [], []
    for row in rules.data().get("library") or []:
        have = _covering(reqs, row["ref"])
        if have is not None:
            found.append({"ref": row["ref"], "code": have.code})
            continue
        code = _next_code(taken)
        taken.add(code)
        order += 1
        req = Requirement(
            law_version_id=v.id, code=code, order=order, text=row["text"], applies_to=row.get("applies_to"), needed_by_stage=row.get("needed_by"),
            evidence_text=row.get("evidence"), role_id=roles.get(row.get("role") or ""), ai_types=row.get("ai_types"), citation=row.get("citation"),
            source_quote=row.get("quote"), source_id=eurlex.id if eurlex else None, source_url=eurlex.url if eurlex else None, verify_flag=True,
        )
        db.add(req)
        reqs.append(req)
        added.append({"ref": row["ref"], "code": code})
    if added:
        db.flush()
        audit.record(db, actor_id=actor_id, actor_name=None if actor_id else "Platform seed", action="law.requirements_seeded", object_type="Regulation", object_id=reg.id,
                     organization_id="futran", after={"added": added}, summary=f"Added {len(added)} EU AI Act requirements to the law library for the EU AI Act workspace "
                     f"({', '.join(a['code'] for a in added)}); {len(found)} were already there")
    return {"added": added, "found": found, "missing_law": False}


def seed_on_start(app) -> None:
    """Start-up hook: add missing EU AI Act requirements; a failure is logged and never stops the app."""
    db = app.state.sessionmaker()
    try:
        out = ensure_requirements(db)
        db.commit()
        if out["added"]:
            log.info("EU AI Act requirements added to the law library: %s", out["added"])
    except Exception as exc:  # an unmigrated or locked database
        db.rollback()
        log.warning("EU AI Act requirements were not checked on start-up: %s", exc)
    finally:
        db.close()
