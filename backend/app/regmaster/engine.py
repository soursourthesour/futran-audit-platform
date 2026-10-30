"""Applicability engine (spec §25.4).

Inputs: the client's geographies and the answers to each law's scope tests, pre-filled from the client's AI use.
Output: one ClientLawApplicability row per law the master has a view on, each with a reason. Laws with scope tests
are decided by the tests; laws the client confirmed in set-up (ClientRequirement) are in scope as confirmed.

Required roles are the union of LawRoleMap over in-scope laws; where laws differ, the stricter level and the earlier
stage win and every source is listed. Required committees are the union of CommitteeRule.

Re-run triggers: `add_geography`/`remove_geography`, `sync_from_locations` (wizard step 2), `set_answers`, and
`rerun_for_regulation` after an approved law version. The register (WS-B) calls `run(db, org_id)` when a system's
laws change.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import Invalid
from app.engagements.models import ClientLocation, ClientRequirement
from app.laws.models import Regulation
from app.reference.models import Jurisdiction, JurisdictionMembership
from app.regmaster.models import STAGES, ClientGeography, ClientLawApplicability, CommitteeRule, LawRoleMap, LawVersion, RoleCatalog, ScopeTest

BASES = ("office", "employees", "candidates", "customers", "data")
EMPLOYMENT = re.compile(r"hir|recruit|candidat|applicant|employ|promot|talent|interview|resume|résumé|workforce|\bhr\b|human resources", re.I)


# ------------------------------------------------------------------ geographies

def geographies(db: Session, org_id: str) -> list[ClientGeography]:
    return list(db.scalars(select(ClientGeography).where(ClientGeography.organization_id == org_id, ClientGeography.deleted_at.is_(None)).order_by(ClientGeography.created_at)))


def expand(db: Session, jurisdiction_ids: set[str]) -> dict[str, Jurisdiction]:
    """Each geography plus everything above it: city -> state -> country -> groups the country belongs to."""
    out: dict[str, Jurisdiction] = {}
    todo = list(jurisdiction_ids)
    while todo:
        j = db.get(Jurisdiction, todo.pop())
        if j is None or j.id in out:
            continue
        out[j.id] = j
        if j.parent_id:
            todo.append(j.parent_id)
        todo.extend(db.scalars(select(JurisdictionMembership.group_id).where(JurisdictionMembership.member_id == j.id)))
    return out


def add_geography(db: Session, org_id: str, jurisdiction_id: str, basis: str, actor_id: str | None, source: str = "manual", location_id: str | None = None, rerun: bool = True) -> ClientGeography:
    if basis not in BASES:
        raise Invalid(errors=[{"field": "basis", "message": "Choose office, employees, candidates, customers or data."}])
    if db.get(Jurisdiction, jurisdiction_id) is None:
        raise Invalid(errors=[{"field": "jurisdiction_id", "message": "Unknown geography."}])
    row = db.scalar(select(ClientGeography).where(ClientGeography.organization_id == org_id, ClientGeography.jurisdiction_id == jurisdiction_id, ClientGeography.basis == basis))
    if row is None:
        row = ClientGeography(organization_id=org_id, jurisdiction_id=jurisdiction_id, basis=basis, source=source, location_id=location_id, created_by=actor_id)
        db.add(row)
    else:
        row.deleted_at, row.updated_by = None, actor_id
        row.location_id = location_id or row.location_id
    db.flush()
    if rerun:
        run(db, org_id, actor_id)
    return row


def remove_geography(db: Session, row: ClientGeography, actor_id: str | None) -> None:
    row.deleted_at, row.updated_by = utcnow(), actor_id
    db.flush()
    run(db, row.organization_id, actor_id)


def sync_from_locations(db: Session, org_id: str, actor_id: str | None) -> None:
    """Wizard step 2: every in-scope site is an office geography at its most specific jurisdiction."""
    locs = list(db.scalars(select(ClientLocation).where(ClientLocation.organization_id == org_id, ClientLocation.deleted_at.is_(None), ClientLocation.in_scope.is_(True))))
    wanted: dict[str, str] = {}
    for loc in locs:
        if loc.jurisdiction_ids:
            wanted.setdefault(loc.jurisdiction_ids[0], loc.id)
    for g in geographies(db, org_id):
        if g.source == "wizard" and g.basis == "office" and g.jurisdiction_id not in wanted:
            g.deleted_at, g.updated_by = utcnow(), actor_id
    for jid, loc_id in wanted.items():
        add_geography(db, org_id, jid, "office", actor_id, source="wizard", location_id=loc_id, rerun=False)
    db.flush()
    run(db, org_id, actor_id)


# ------------------------------------------------------------------ facts used to pre-fill scope answers

def _facts(db: Session, org_id: str) -> dict:
    from app.inventory.models import UseCase

    ucs = list(db.scalars(select(UseCase).where(UseCase.organization_id == org_id, UseCase.deleted_at.is_(None))))
    consequential = [u for u in ucs if u.decision_impact == "consequential"]
    employment = [u for u in ucs if u.aedt_determination == "in_scope" or (u.decision_impact == "consequential" and EMPLOYMENT.search(f"{u.name} {u.purpose or ''}"))]
    return {"use_cases": len(ucs), "consequential": consequential, "employment": employment}


def _prefill(test: ScopeTest, geo: dict[str, Jurisdiction], facts: dict) -> tuple[str, str]:
    """(answer, why): answer is yes | no | unknown."""
    rule = test.in_scope_rule or {}
    if test.prefill_from == "client_geographies":
        codes = rule.get("codes") or []
        hit = [j for j in geo.values() if j.code in codes]
        return ("yes", hit[0].name) if hit else ("no", "")
    if test.prefill_from == "decision_impact":
        pool = facts["employment"] if rule.get("feature") == "employment" else facts["consequential"]
        if pool:
            return "yes", pool[0].name
        return ("no", "") if facts["use_cases"] else ("unknown", "")
    return ("yes", "") if rule.get("any") else ("unknown", "")


def _passes(rule: dict, answer: str) -> bool:
    if rule.get("any"):
        return True
    if "equals" in rule:
        return answer == rule["equals"] or answer == "unknown"
    if "in" in rule:
        return answer in rule["in"] or answer == "unknown"
    return True


def _jurisdiction_name(db: Session, reg: Regulation) -> str:
    j = db.get(Jurisdiction, reg.jurisdiction_id)
    return j.name if j else ""


def _decide(db: Session, reg: Regulation, version: LawVersion, tests: list[ScopeTest], geo: dict[str, Jurisdiction], facts: dict, answers: dict) -> tuple[bool, str, dict]:
    used: dict[str, str] = {}
    to_confirm: list[str] = []
    where = ""
    for t in tests:
        key = str(t.order)
        answer, why = (answers[key], "answered") if key in answers else _prefill(t, geo, facts)
        used[key] = answer
        if not t.decisive:
            continue
        if not _passes(t.in_scope_rule or {}, answer):
            if t.prefill_from == "client_geographies":
                return False, f"No {_jurisdiction_name(db, reg)} operations or residents", used
            if t.prefill_from == "decision_impact":
                kind = "employment" if (t.in_scope_rule or {}).get("feature") == "employment" else "consequential"
                return False, f"No AI system makes {kind} decisions in scope of this law", used
            return False, f"Out of scope: {t.question_text}", used
        if answer == "unknown":
            to_confirm.append(t.question_text.rstrip("?").lower())
        elif t.prefill_from == "client_geographies" and why not in ("answered", ""):
            where = why
        elif t.prefill_from == "decision_impact" and why not in ("answered", ""):
            where = f"{where}; " if where else ""
            where += f"AI system '{why}' is in scope"
    reason = f"Operates in {where}" if where and not where.startswith("AI system") else (where or "Applies to every client")
    if to_confirm:
        reason += f" (to confirm: {to_confirm[0]})"
    return True, reason[:600], used


def candidate_laws(db: Session, org_id: str) -> list[tuple[Regulation, LawVersion]]:
    """Laws with scope tests on their approved version, plus laws the client confirmed in set-up."""
    out: dict[str, tuple[Regulation, LawVersion]] = {}
    rows = db.execute(
        select(Regulation, LawVersion).join(LawVersion, LawVersion.id == Regulation.current_version_id)
        .where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None))
    ).all()
    tested = set(db.scalars(select(ScopeTest.law_version_id).distinct()))
    confirmed = set(db.scalars(select(ClientRequirement.regulation_id).where(ClientRequirement.organization_id == org_id, ClientRequirement.deleted_at.is_(None), ClientRequirement.in_scope.is_(True), ClientRequirement.regulation_id.is_not(None))))
    for reg, v in rows:
        if v.id in tested or reg.id in confirmed:
            out[reg.id] = (reg, v)
    return list(out.values())


def run(db: Session, org_id: str, actor_id: str | None = None) -> list[ClientLawApplicability]:
    from app.laws.publish import current_version_of

    from app.regmaster.seed import ensure_versions

    ensure_versions(db)
    geo = expand(db, {g.jurisdiction_id for g in geographies(db, org_id)})
    facts = _facts(db, org_id)
    confirmed = {}
    for cr in db.scalars(select(ClientRequirement).where(ClientRequirement.organization_id == org_id, ClientRequirement.deleted_at.is_(None), ClientRequirement.in_scope.is_(True), ClientRequirement.regulation_id.is_not(None))):
        cur = current_version_of(db, cr.regulation_id)
        if cur is not None:
            confirmed[cur.id] = cr
    existing = {r.regulation_id: r for r in db.scalars(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org_id, ClientLawApplicability.deleted_at.is_(None)))}
    now = utcnow()
    seen: set[str] = set()
    out = []
    for reg, v in candidate_laws(db, org_id):
        seen.add(reg.id)
        row = existing.get(reg.id)
        if row is None:
            row = ClientLawApplicability(organization_id=org_id, regulation_id=reg.id, created_by=actor_id)
            db.add(row)
        row.law_version_id = v.id
        if not row.override:
            tests = list(db.scalars(select(ScopeTest).where(ScopeTest.law_version_id == v.id).order_by(ScopeTest.order)))
            answers = {k: v_ for k, v_ in ((row.scope_answers or {}).get("manual") or {}).items()}
            if tests:
                in_scope, reason, used = _decide(db, reg, v, tests, geo, facts, answers)
            else:
                in_scope, reason, used = True, "Confirmed in client set-up", {}
            if not in_scope and reg.id in confirmed:
                in_scope, reason = True, f"Confirmed in client set-up; {reason[:1].lower()}{reason[1:]}"
            row.in_scope, row.reason_text = in_scope, reason
            row.scope_answers = {"used": used, "manual": answers}
            row.decided_by, row.decided_at = None, now
        out.append(row)
    for reg_id, row in existing.items():
        if reg_id not in seen and not row.override:
            row.deleted_at = now
    db.flush()
    return out


def rerun_for_regulation(db: Session, regulation_id: str) -> list[str]:
    """After an approved version: re-run every client that has a view on this law or any geography."""
    orgs = set(db.scalars(select(ClientLawApplicability.organization_id).where(ClientLawApplicability.regulation_id == regulation_id)))
    orgs |= set(db.scalars(select(ClientGeography.organization_id).where(ClientGeography.deleted_at.is_(None))))
    for o in orgs:
        run(db, o)
    return sorted(orgs)


def _row_for(db: Session, org_id: str, regulation_id: str) -> ClientLawApplicability:
    row = db.scalar(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org_id, ClientLawApplicability.regulation_id == regulation_id))
    if row is None:
        reg = db.get(Regulation, regulation_id)
        if reg is None:
            raise Invalid(errors=[{"field": "regulation_id", "message": "Unknown law."}])
        row = ClientLawApplicability(organization_id=org_id, regulation_id=regulation_id, law_version_id=reg.current_version_id)
        db.add(row)
    row.deleted_at = None
    return row


def set_answers(db: Session, org_id: str, regulation_id: str, answers: dict, actor_id: str | None) -> ClientLawApplicability:
    row = _row_for(db, org_id, regulation_id)
    manual = dict((row.scope_answers or {}).get("manual") or {})
    for k, v in answers.items():
        if v in (None, ""):
            manual.pop(str(k), None)
        elif v in ("yes", "no"):
            manual[str(k)] = v
        else:
            raise Invalid(errors=[{"field": f"answers.{k}", "message": "Answer yes or no."}])
    row.scope_answers = {**(row.scope_answers or {}), "manual": manual}
    row.updated_by = actor_id
    db.flush()
    run(db, org_id, actor_id)
    return row


def override(db: Session, org_id: str, regulation_id: str, in_scope: bool | None, reason: str | None, actor_id: str | None) -> ClientLawApplicability:
    """A person's decision. `in_scope=None` hands the law back to the engine."""
    row = _row_for(db, org_id, regulation_id)
    if in_scope is None:
        row.override = False
        db.flush()
        run(db, org_id, actor_id)
        return row
    if not (reason or "").strip():
        raise Invalid(errors=[{"field": "reason", "message": "Give the reason for this decision."}])
    row.override, row.in_scope, row.reason_text = True, in_scope, reason.strip()[:600]
    row.decided_by, row.decided_at = actor_id, utcnow()
    db.flush()
    return row


# ------------------------------------------------------------------ roles and committees

LEVEL_RANK = {"required": 2, "recommended": 1}
STAGE_RANK = {s: i for i, s in enumerate(STAGES)}


def law_label(reg: Regulation) -> str:
    return reg.label or reg.short_name


def in_scope_versions(db: Session, org_id: str) -> list[tuple[Regulation, LawVersion]]:
    rows = db.execute(
        select(Regulation, LawVersion).join(ClientLawApplicability, ClientLawApplicability.regulation_id == Regulation.id)
        .join(LawVersion, LawVersion.id == ClientLawApplicability.law_version_id)
        .where(ClientLawApplicability.organization_id == org_id, ClientLawApplicability.deleted_at.is_(None), ClientLawApplicability.in_scope.is_(True))
    ).all()
    return [(r, v) for r, v in rows]


def roles_for_versions(db: Session, pairs: list[tuple[Regulation, LawVersion]]) -> list[dict]:
    """Strictest-wins union of role maps over the given law versions (also used by the register, WS-B)."""
    by_role: dict[str, dict] = {}
    for reg, v in pairs:
        for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == v.id)):
            if m.level not in LEVEL_RANK:
                continue
            role = db.get(RoleCatalog, m.role_id)
            stage = m.needed_by_stage or role.default_stage
            cur = by_role.setdefault(role.code, {"role_id": role.id, "code": role.code, "number": role.number, "name": role.name, "level_kind": role.level, "description": role.description, "level": m.level, "needed_by": stage, "sources": []})
            if LEVEL_RANK[m.level] > LEVEL_RANK[cur["level"]]:
                cur["level"] = m.level
            if STAGE_RANK.get(stage, 99) < STAGE_RANK.get(cur["needed_by"], 99):
                cur["needed_by"] = stage
            cur["sources"].append({"law": law_label(reg), "regulation_id": reg.id, "law_version_id": v.id, "level": m.level, "needed_by": stage, "basis": m.basis_text})
    return sorted(by_role.values(), key=lambda r: r["number"])


def required_roles(db: Session, org_id: str) -> list[dict]:
    return roles_for_versions(db, in_scope_versions(db, org_id))


def committees(db: Session, org_id: str) -> list[dict]:
    out: dict[str, dict] = {}
    for reg, v in in_scope_versions(db, org_id):
        for c in db.scalars(select(CommitteeRule).where(CommitteeRule.law_version_id == v.id)):
            cur = out.setdefault(c.committee_type, {"committee_type": c.committee_type, "title": c.title, "level": c.level, "composition_text": c.composition_text, "cadence": c.cadence, "triggers_text": c.triggers_text, "condition_text": c.condition_text, "items": list(c.items or []), "sources": []})
            if LEVEL_RANK.get(c.level, 0) > LEVEL_RANK.get(cur["level"], 0):
                cur["level"] = c.level
            for it in c.items or []:
                if it not in cur["items"]:
                    cur["items"].append(it)
            cur["sources"].append({"law": law_label(reg), "level": c.level, "basis": c.basis_text})
    return sorted(out.values(), key=lambda c: (-LEVEL_RANK.get(c["level"], 0), c["title"] or ""))
