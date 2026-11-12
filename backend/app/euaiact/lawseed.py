"""EU AI Act requirements for the G-08 workspace (spec B8), proposed to the law library for a Futran reviewer.

The law library changes only through approved proposals (§25.1 principle 1). For each row under `library:` in
`seeds/eu_ai_act.yaml` that no requirement on the EU AI Act's current version already covers (by the article in its
citation), a ProposedChange `requirement.EU-nn` is written in one batch, with its client impact, and appears in
Law library > Refresh and review. Approving it there writes the next EU AI Act version; until then nothing reaches a
client's systems. The batch is proposed once: a second start-up, a rejection or a later approved version never brings
it back. Rows an earlier build inserted straight into the approved version are withdrawn first (unless someone has
already answered them on a system), so they go through review like the rest."""
from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.euaiact import rules

log = logging.getLogger(__name__)
LAW_MATCH = ("EU", "2024/1689")  # the regulatory master seed's match for the EU AI Act
BATCH = "r6b-eu-ai-act-g08-requirements-v1"  # marks the one-time proposal; never proposed again once it exists
ORIGIN = "platform_seed"
MARKER = "law.eu_ai_act_requirements_proposed"


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


def withdraw_direct_rows(db: Session) -> list[str]:
    """Remove requirement rows an earlier build of this workstream wrote straight into an approved EU AI Act version
    (audit action `law.requirements_seeded`), unless a system already has an answer recorded against one: those stay."""
    from app.audit_log import service as audit
    from app.audit_log.models import AuditLog
    from app.laws.publish import chain_ids
    from app.regmaster.models import LawRoleMap, LawVersion, Requirement
    from app.register.models import RequirementStatus

    out = []
    for entry in db.scalars(select(AuditLog).where(AuditLog.action == "law.requirements_seeded")):
        codes = {a.get("code") for a in (entry.after or {}).get("added") or [] if isinstance(a, dict)}
        regs = chain_ids(db, entry.object_id) or [entry.object_id]
        vids = list(db.scalars(select(LawVersion.id).where(LawVersion.regulation_id.in_(regs))))
        for req in db.scalars(select(Requirement).where(Requirement.law_version_id.in_(vids), Requirement.code.in_(codes), Requirement.verify_flag.is_(True))):
            if db.scalar(select(RequirementStatus.id).where(RequirementStatus.requirement_id == req.id, RequirementStatus.deleted_at.is_(None)).limit(1)):
                continue
            for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == req.law_version_id)):
                if req.id in (m.requirement_ids or []):
                    m.requirement_ids = [i for i in m.requirement_ids if i != req.id]
            out.append(req.code)
            db.delete(req)
    if out:
        db.flush()
        audit.record(db, actor_id=None, actor_name="Platform seed", action="law.requirements_seed_withdrawn", object_type="Regulation", organization_id="futran",
                     after={"codes": out}, summary=f"Withdrew {len(out)} EU AI Act rows added without review ({', '.join(out)}); they are proposed for review instead")
    return out


def ensure_requirements(db: Session) -> dict:
    """Propose the EU AI Act requirements the library lacks, once. Returns
    {"proposed": [{"ref", "code"}], "found": [...], "withdrawn": [...], "missing_law": bool, "already_seeded": bool}."""
    from app.regmaster.changes import propose
    from app.regmaster.models import ProposedChange

    out = {"proposed": [], "found": [], "withdrawn": [], "missing_law": False, "already_seeded": False}
    out["withdrawn"] = withdraw_direct_rows(db)
    reg, v = eu_ai_act(db)
    if v is None:
        out["missing_law"] = True
        return out
    from app.audit_log import service as audit
    from app.audit_log.models import AuditLog

    if db.scalar(select(ProposedChange.id).where(ProposedChange.batch_id == BATCH).limit(1)) is not None or \
            db.scalar(select(AuditLog.id).where(AuditLog.action == MARKER).limit(1)) is not None:
        out["already_seeded"] = True
        return out
    reqs = _requirements(db, v.id)
    taken = {r.code for r in reqs}
    for row in rules.data().get("library") or []:
        have = _covering(reqs, row["ref"])
        if have is not None:
            out["found"].append({"ref": row["ref"], "code": have.code})
            continue
        code = _next_code(taken)
        taken.add(code)
        value = {"text": row["text"], "applies_to": row.get("applies_to"), "needed_by_stage": row.get("needed_by"), "evidence_text": row.get("evidence"),
                 "role": row.get("role"), "ai_types": row.get("ai_types"), "citation": row.get("citation"), "source_quote": row.get("quote"),
                 "source_url": row.get("source_url") or rules.data().get("library_source_url"), "verify_flag": True}
        propose(db, actor_id=None, regulation_id=reg.id, field_path=f"requirement.{code}", new_value=value, origin=ORIGIN, change_type="new_rule", batch_id=BATCH,
                summary=f"EU AI Act: add {row['citation']} ({row['text'][:120]})",
                reason="Needed by the EU AI Act conformity workspace (Release 2 G-08); not in the law library. The quote was not re-read against the Official Journal: check it before approving.",
                source_url=row.get("source_url") or rules.data().get("library_source_url"), source_quote=row.get("quote"))
        out["proposed"].append({"ref": row["ref"], "code": code})
    # the marker: proposed once, whatever comes of it (approval, rejection, a later version removing a row)
    audit.record(db, actor_id=None, actor_name="Platform seed", action=MARKER, object_type="Regulation", object_id=reg.id, organization_id="futran",
                 after={"proposed": out["proposed"], "found": [f["code"] for f in out["found"]], "base_version_id": v.id},
                 summary=(f"Proposed {len(out['proposed'])} EU AI Act requirements for review in Refresh and review" if out["proposed"]
                          else "Checked the EU AI Act requirements for the EU AI Act workspace: all already in the law library"))
    db.flush()
    return out


def seed_on_start(app) -> None:
    """Start-up hook: propose the missing EU AI Act requirements for review, once. A failure is logged and never stops
    the app."""
    db = app.state.sessionmaker()
    try:
        out = ensure_requirements(db)
        db.commit()
        if out["proposed"]:
            log.info("EU AI Act requirements proposed for review in Refresh and review: %s", out["proposed"])
    except Exception as exc:  # an unmigrated or locked database
        db.rollback()
        log.warning("EU AI Act requirements were not proposed on start-up: %s", exc)
    finally:
        db.close()
