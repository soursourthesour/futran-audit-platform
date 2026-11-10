"""Laws suggested for one AI system from where it runs, where the people whose data it uses are, and what it does
(11-03 C14). No AI: this is the law library's own logic.

1. Laws with scope questions are decided exactly as the applicability engine decides them for a client
   (`regmaster.engine._prefill` and `_passes`), with the system's places as the geographies and the system as the only
   AI fact. The client's own manual answers to questions that are not about places or decisions still count.
2. Laws without scope questions (most of the law matrix) are suggested when the law belongs to a place the system
   reaches (the place, its state, its country and the groups the country belongs to, as the engine expands them) and
   the law's AI feature in the law library is one the system has. Developer-only laws are left out for bought systems,
   and only statutes and regulations are suggested (not bills, guidance or voluntary frameworks).

3. A law a person decided for the whole company (an override in the applicability results) follows that decision:
   ruled out, it is not suggested; ruled in, it is suggested as in scope for the company.

Nothing is added to a system until a person accepts a suggestion.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.laws.importer import FEATURE_LABELS
from app.laws.models import Regulation
from app.reference.jurisdictions import resolve_jurisdictions
from app.reference.models import Jurisdiction
from app.regmaster import engine
from app.regmaster.models import ClientLawApplicability, LawVersion, ScopeTest
from app.regmaster.versioning import repealed

PERSONAL = {"personal", "health", "biometric", "sensitive", "children"}
SUGGESTED_TYPES = {"statute", "regulation"}
BUILT = {"in_house", "contractor"}


@dataclass
class Draft:
    """What the suggestion needs to know about a system, saved or still being added."""

    name: str = ""
    purpose: str = ""
    department_name: str = ""
    type: str | None = None
    sourcing: str | None = None
    algorithm_type: str | None = None
    decision_impact: str | None = None
    data_categories: list = field(default_factory=list)
    data_subjects: list = field(default_factory=list)
    run_location: dict | None = None
    data_locations: list = field(default_factory=list)


def draft_of(db: Session, s, data_row=None) -> Draft:
    from app.tenancy.models import Department

    dept = db.get(Department, s.department_id) if s.department_id else None
    return Draft(name=s.name or "", purpose=s.purpose or "", department_name=dept.name if dept else "", type=s.type, sourcing=s.sourcing, algorithm_type=s.algorithm_type,
                 decision_impact=s.decision_impact, data_categories=list(data_row.data_categories or []) if data_row else [],
                 data_subjects=list(data_row.data_subjects or []) if data_row else [], run_location=s.run_location, data_locations=list(s.data_locations or []))


def employment(d: Draft) -> bool:
    return bool(engine.EMPLOYMENT.search(f"{d.name} {d.purpose} {d.department_name}")) or bool({"candidates", "employees"} & set(d.data_subjects))


def facts(d: Draft) -> dict:
    """The engine's facts with this system as the only AI system (`engine._facts` shape)."""
    me = _Named(d.name or "This system")
    consequential = [me] if d.decision_impact == "consequential" else []
    return {"use_cases": 1 if d.decision_impact else 0, "consequential": consequential, "employment": consequential if consequential and employment(d) else []}


@dataclass
class _Named:
    name: str


def features(d: Draft) -> set[str]:
    """The law library's AI features this system has."""
    cats, impact = set(d.data_categories), d.decision_impact
    out: set[str] = set()
    hiring = employment(d)
    if impact == "consequential" and not hiring:  # hiring systems take the employment laws, not the credit, housing and finance ones
        out.add("consequential_decisions_admt")
    if impact in ("informs", "consequential") and hiring:
        out.add("employment_hiring")
    if impact in ("informs", "consequential") and cats & PERSONAL:
        out.add("privacy_profiling")
    if "health" in cats:
        out.add("health_insurance")
    if "biometric" in cats:
        out.add("biometrics_pricing")
    if "children" in cats or d.type == "genai_chat_tool":
        out.add("chatbots_minors")
    if d.type in ("genai_chat_tool", "foundation_model_api") or d.algorithm_type in ("llm", "llm_agent"):
        out.add("synthetic_content")
    return out


def _places(db: Session, places: list[dict]) -> dict[str, Jurisdiction]:
    ids: set[str] = set()
    for p in places:
        if p and p.get("country"):
            ids |= {j.id for j in resolve_jurisdictions(db, p["country"], p.get("region"), p.get("city"))}
    return engine.expand(db, ids)


def suggest(db: Session, org_id: str, d: Draft, *, exclude: set[str] | None = None) -> list[dict]:
    run_geo = _places(db, [d.run_location] if d.run_location else [])
    data_geo = _places(db, list(d.data_locations or []))
    geo = {**run_geo, **data_geo}
    if not geo:
        return []
    exclude = exclude or set()
    f = facts(d)
    feats = features(d)
    manual, decided_for_company = {}, {}
    for row in db.scalars(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org_id, ClientLawApplicability.deleted_at.is_(None))):
        manual[row.regulation_id] = ((row.scope_answers or {}).get("manual") or {})
        if row.override and row.in_scope is not None:  # a person decided the law for the whole company (as the engine keeps it)
            decided_for_company[row.regulation_id] = row
    tested = set(db.scalars(select(ScopeTest.law_version_id).distinct()))
    rows = db.execute(select(Regulation, LawVersion).join(LawVersion, LawVersion.id == Regulation.current_version_id)
                      .where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None))).all()
    decided: set[str] = set()
    out: list[dict] = []

    def where(code_hit: set[str]) -> str:
        r = [j for j in run_geo.values() if j.code in code_hit]
        if r:
            return f"Runs in {_the(_most_specific(r).name)}"
        dd = [j for j in data_geo.values() if j.code in code_hit]
        return f"The people whose data it uses are in {_the(_most_specific(dd).name)}" if dd else ""

    for reg, v in rows:
        row = decided_for_company.get(reg.id)
        if row is None or reg.id in exclude:
            continue
        decided.add(reg.id)
        if row.in_scope:
            why = " ".join((row.reason_text or "").split())
            out.append(_out(db, reg, (f"In scope for the company: {why}" if why else "In scope for the company")[:600], "company"))

    for reg, v in rows:
        if v.id not in tested or reg.id in exclude or reg.id in decided:
            continue
        decided.add(reg.id)
        if repealed(v):
            continue
        tests = list(db.scalars(select(ScopeTest).where(ScopeTest.law_version_id == v.id).order_by(ScopeTest.order)))
        answers = manual.get(reg.id, {})
        ok, parts, confirm = True, [], []
        for t in tests:
            key = str(t.order)
            if t.prefill_from in ("client_geographies", "decision_impact") or key not in answers:
                answer, _why = engine._prefill(t, geo, f)
            else:
                answer = answers[key]
            if not t.decisive:
                continue
            if not engine._passes(t.in_scope_rule or {}, answer):
                ok = False
                break
            if answer == "unknown":
                confirm.append(t.question_text.rstrip("?").lower())
            elif t.prefill_from == "client_geographies":
                parts.append(where(set((t.in_scope_rule or {}).get("codes") or [])))
            elif t.prefill_from == "decision_impact":
                parts.append("makes employment decisions" if (t.in_scope_rule or {}).get("feature") == "employment" else "makes or substantially makes decisions about people")
        if not ok:
            continue
        reason = "; ".join(p for p in parts if p) or "Applies to every AI system"
        reason = reason[:1].upper() + reason[1:]
        if confirm:
            reason += f" (to confirm: {confirm[0]})"
        out.append(_out(db, reg, reason[:600], "scope_test"))

    for reg, v in rows:
        if reg.id in decided or reg.id in exclude or reg.type not in SUGGESTED_TYPES or repealed(v):
            continue
        if reg.feature not in feats or reg.jurisdiction_id not in geo or _note_row(reg.short_name):
            continue
        if reg.applies_to == "developer" and d.sourcing not in BUILT:
            continue
        j = geo[reg.jurisdiction_id]
        place = where(_codes_under(j, run_geo)) or where(_codes_under(j, data_geo))
        label = FEATURE_LABELS.get(reg.feature, reg.feature)
        reason = f"{j.name} law on {label[:1].lower()}{label[1:]}. {place}."
        out.append(_out(db, reg, reason[:600], "feature"))
    order = {"company": 0, "scope_test": 1, "feature": 2}
    return sorted(out, key=lambda x: (order[x["basis"]], x["jurisdiction"] or "", x["short_name"]))


def _codes_under(j: Jurisdiction, geo: dict[str, Jurisdiction]) -> set[str]:
    """The codes of the places in `geo` that `j` covers (itself and anything below it there)."""
    return {g.code for g in geo.values() if g.id == j.id} | ({j.code} if j.id in geo else set())


def _the(name: str) -> str:
    """"the United States", "the European Union"."""
    return f"the {name}" if name.startswith(("United ", "European ", "Republic of ")) or name in ("Netherlands", "Philippines", "Czechia (the)") else name


def _note_row(short_name: str) -> bool:
    """Law matrix rows that only say a place has no such law ("No comprehensive state privacy law", "Only through ...")."""
    return short_name.split(" ", 1)[0] in ("No", "Only")


LEVEL_RANK = {"city": 0, "state": 1, "country": 2, "supranational": 3}


def _most_specific(js: list[Jurisdiction]) -> Jurisdiction:
    return sorted(js, key=lambda j: LEVEL_RANK.get(j.level, 9))[0]


def _out(db: Session, reg: Regulation, reason: str, basis: str) -> dict:
    j = db.get(Jurisdiction, reg.jurisdiction_id)
    return {"regulation_id": reg.id, "short_name": reg.short_name, "jurisdiction": j.name if j else None, "jurisdiction_code": j.code if j else None, "reason": reason, "basis": basis}
