"""Report content that explains itself: how risk and maturity are rated (from the methodology version the engagement
was scored with), the scope and evidence behind the report, and each finding's references."""
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engagements.models import Engagement
from app.scoring import engine, scale

BUILD_TYPE_LABEL = {"in_house": "In house", "vendor": "Vendor", "open_source_customized": "Open source, customized", "hybrid": "Hybrid"}
WEIGHT_SET_LABEL = {"in_house": "In-house weights", "vendor": "Vendor weights"}
RISK_PREFIX = re.compile(r"^(?:risk and impact|risk|impact)\s*[:.]\s*", re.I)


def pct(x: float) -> str:
    v = round(100 * float(x), 1)
    return f"{v:g}%"


def num(x) -> str:
    return f"{float(x):g}" if isinstance(x, (int, float)) else str(x)


# ---- questions and their answers
def _questions(db: Session) -> dict:
    from app.questionnaire.models import Question
    from app.questionnaire.seed import active_template_version

    tv = active_template_version(db)
    if tv is None:
        return {}
    return {q.code: q for q in db.scalars(select(Question).where(Question.template_version_id == tv.id))}


def section_titles(db: Session, questions: dict) -> dict[str, str]:
    from app.questionnaire.models import ChecklistItem

    out = {q.sub_section: q.section_title for q in questions.values() if q.sub_section and q.section_title}
    for section, title in db.execute(select(ChecklistItem.section, ChecklistItem.section_title)):
        out.setdefault(section, title)
    return out


def option_label(q, value) -> str:
    opts = {str(o.get("value")).casefold(): o.get("label") for o in (q.options or []) if isinstance(o, dict)}
    if isinstance(value, list):
        return ", ".join(option_label(q, v) for v in value)
    if isinstance(value, dict):
        return ", ".join(str(v) for v in value.values() if v)
    if value is None or value == "":
        return ""
    return opts.get(str(value).casefold()) or {"yes": "Yes", "no": "No", "unknown": "Unknown"}.get(str(value).casefold(), str(value))


# ---- how the report rates risk and maturity
def _factor_definitions(key: str, spec: dict, questions: dict) -> dict[int, str]:
    if key == "consequence":
        return {n: f"{name}: {text}" for n, name, text in scale.CONSEQUENCE_LEVELS}
    if "bands" in spec:
        out, lo = {}, 0
        for b in spec["bands"]:
            out[b["score"]] = f"{lo:,} or more a month" if b["max"] is None else (f"Up to {b['max']:,} a month" if lo == 0 else f"{lo:,} to {b['max']:,} a month")
            lo = (b["max"] or 0) + 1
        return out
    if "levels" in spec:
        return {lv["score"]: _describe_rule(lv["rule"], questions) for lv in spec["levels"]}
    q = questions.get(spec.get("question"))
    grouped: dict[int, list[str]] = {}
    for value, score in spec["scores"].items():
        grouped.setdefault(int(score), []).append(option_label(q, value) if q else str(value).replace("_", " ").capitalize())
    return {s: "; ".join(dict.fromkeys(v)) for s, v in grouped.items()}


def _describe_rule(rule, questions: dict) -> str:
    if rule is None:
        return "Any other answer"
    if "any" in rule:
        return "; or ".join(_describe_rule(r, questions) for r in rule["any"])
    if "all" in rule:
        return " and ".join(_describe_rule(r, questions) for r in rule["all"])
    q = questions.get(rule.get("q"))
    name = f"{rule.get('q')} ({q.label})" if q else str(rule.get("q"))
    values = rule.get("in") or [rule.get("eq")]
    answers = " or ".join(option_label(q, v) if q else str(v) for v in values)
    return f"{name}: {answers}"


def scoring_explained(db: Session, e: Engagement, systems: list) -> dict:
    """Everything section 2 and Appendix A state, read from the methodology version the systems were scored with."""
    from app.reference.models import RiskMethodology
    from app.scoring.service import methodology

    version = next((s.methodology_version for s in systems if s.methodology_version), None)
    m = methodology(db, version)
    row = db.scalar(select(RiskMethodology).where(RiskMethodology.version == m.version))
    questions = _questions(db)
    factors = []
    for key, spec in m.factors.items():
        defs = _factor_definitions(key, spec, questions)
        code = spec.get("question") or ", ".join(spec.get("questions", []))
        q = questions.get(spec.get("question"))
        short = {n: name for n, name, _ in scale.CONSEQUENCE_LEVELS} if key == "consequence" else defs
        between = [f"{s}: {short[s]}" for s in sorted(short, reverse=True) if 1 < s < 5]
        factors.append({"key": key, "label": engine.FACTOR_LABELS.get(key, key), "weight": pct(spec["weight"]), "question": f"{code} {q.label}" if q else code,
                        "lowest": short.get(1, "No answer scores 1"), "between": "; ".join(between) or "Scored 1 or 5 only", "highest": short.get(5, "No answer scores 5"),
                        "all": [{"score": s, "meaning": defs[s]} for s in sorted(defs, reverse=True)]})
    sets_used = sorted({m.build_type_weights.get(s.built_by or "in_house", "in_house") for s in systems}) or sorted(m.domain_weights_by_build_type)
    weight_rows = [{"label": label, "weights": [pct(m.domain_weights_by_build_type[ws].get(key, 0)) for ws in sets_used]} for key, label in m.domains.items()]
    light = [s for s in systems if s.assessment_depth == "light"]
    light_sets = sorted({m.build_type_weights.get(s.built_by or "in_house", "in_house") for s in light})
    light_rows = []
    if light:
        for key in m.light_domains:
            light_rows.append({"label": m.domains[key], "weights": [pct(engine.domain_weights(next(b for b, w in m.build_type_weights.items() if w == ws), "light", m)[key]) for ws in light_sets]})
    applied = []
    for s in systems:
        ws = m.build_type_weights.get(s.built_by or "in_house", "in_house")
        applied.append({"ref": s.reference_id, "name": s.name, "built_by": BUILD_TYPE_LABEL.get(s.built_by or "", "Not recorded"),
                        "depth": "Light (Tier 2)" if s.assessment_depth == "light" else "Full",
                        "weights": WEIGHT_SET_LABEL.get(ws, ws) + (", rescaled for a light assessment" if s.assessment_depth == "light" else "")})
    reduction = float(m.max_control_reduction)
    return {
        "version": m.version, "effective_date": _date(row.effective_date) if row else "",
        "factors": factors, "weight_sets": [WEIGHT_SET_LABEL.get(ws, ws) for ws in sets_used], "weight_rows": weight_rows,
        "light_sets": [WEIGHT_SET_LABEL.get(ws, ws) for ws in light_sets], "light_rows": light_rows, "light_domains": [m.domains[k] for k in m.light_domains],
        "has_open_source_or_hybrid": any(s.built_by in ("open_source_customized", "hybrid") for s in systems),
        "applied": applied, "maturity_levels": scale.maturity_rows(), "consequence_levels": scale.consequence_rows(),
        "reduction_pct": pct(reduction), "formula": f"Residual risk = inherent × (1 − {num(reduction)} × (maturity − 1) ÷ 4)",
        "reduction": num(reduction), "levels": scale.scale_rows(m.bands),
        "knockouts": [{"label": k["label"], "force": scale.labelled(k["force"])} for k in m.knockout_rules],
        "eu_floor": num(m.eu_ai_act.get("high_floor", 70)), "eu_prohibited": scale.labelled(m.eu_ai_act.get("prohibited", "critical")),
        "proposed_bands": [{"min": b["min_pct"], "score": b["score"]} for b in sorted((row.config or {}).get("proposed_score_bands", []) if row else [], key=lambda b: -b["min_pct"])],
    }


def _date(text: str | None) -> str:
    from datetime import date

    from app.initiation.context import fmt

    try:
        return fmt(date.fromisoformat(str(text))) or ""
    except ValueError:
        return str(text or "")


def calculation(inherent, maturity, residual, reduction: str) -> str | None:
    """The residual risk worked through for one system: '76.0 × (1 − 0.75 × (2.25 − 1) ÷ 4) = 58.2'."""
    if inherent is None or maturity is None or residual is None:
        return None
    return f"{inherent:.1f} × (1 − {reduction} × ({maturity:g} − 1) ÷ 4) = {residual:.1f}"


# ---- scope and evidence
def scope_facts(db: Session, e: Engagement, systems: list) -> dict:
    from app.attestation.models import Attestation
    from app.docrequests.models import DocumentRequest, EvidenceRequest
    from app.inventory.models import UseCase
    from app.questionnaire.models import Response
    from app.tenancy.models import Department

    ucs = list(db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None), UseCase.status == "dept_approved")))
    dept_ids = list(dict.fromkeys([s.department_id for s in systems if s.department_id] + [u.department_id for u in ucs if u.department_id]))
    depts = [d.name for d in (db.get(Department, i) for i in dept_ids) if d is not None]
    count = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    docs = list(db.scalars(select(DocumentRequest).where(DocumentRequest.engagement_id == e.id, DocumentRequest.deleted_at.is_(None))))
    return {
        "systems": len(systems), "use_cases": len(ucs), "departments": join_and(depts),
        "answers": count(select(func.count(Response.id)).where(Response.engagement_id == e.id, Response.deleted_at.is_(None), Response.status.in_(["answered", "not_yet_in_place"]))),
        "documents_requested": len(docs), "documents_received": sum(1 for d in docs if d.status == "received"),
        "evidence_requests": count(select(func.count(EvidenceRequest.id)).where(EvidenceRequest.engagement_id == e.id, EvidenceRequest.deleted_at.is_(None))),
        "attestations": count(select(func.count(Attestation.id)).where(Attestation.engagement_id == e.id, Attestation.deleted_at.is_(None))),
    }


def join_and(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---- findings
def split_description(text: str | None) -> tuple[str, str]:
    """The condition, and the risk or impact: a paragraph that starts 'Risk:' or 'Impact:' is shown under its own heading."""
    condition, risk = [], []
    for para in re.split(r"\n\s*\n", (text or "").strip()):
        if not para.strip():
            continue
        if RISK_PREFIX.match(para.strip()):
            risk.append(RISK_PREFIX.sub("", para.strip(), count=1))
        else:
            condition.append(para.strip())
    return "\n\n".join(condition), "\n\n".join(risk)


def _related(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a == b or a.startswith(b + ".") or b.startswith(a + ".")


def _files(db: Session, ids) -> str:
    from app.files.models import FileObject

    return ", ".join(f.filename for f in (db.get(FileObject, i) for i in ids or []) if f is not None and f.deleted_at is None)


class FindingReferences:
    """Loads the engagement's evidence once and answers per finding."""

    def __init__(self, db: Session, e: Engagement, systems: list):
        from app.docrequests.models import DocumentRequest, EvidenceRequest
        from app.questionnaire.models import Response
        from app.reference.models import DocumentCatalogItem

        self.db, self.e = db, e
        self.questions = _questions(db)
        self.sections = section_titles(db, self.questions)
        self.systems = {s.id: s for s in systems}
        self.docs = [(d, db.get(DocumentCatalogItem, d.catalog_item_id)) for d in db.scalars(select(DocumentRequest).where(DocumentRequest.engagement_id == e.id, DocumentRequest.deleted_at.is_(None)))]
        self.ers = list(db.scalars(select(EvidenceRequest).where(EvidenceRequest.engagement_id == e.id, EvidenceRequest.deleted_at.is_(None)).order_by(EvidenceRequest.ref)))
        by_q = {q.id: q.code for q in self.questions.values()}
        self.answers: dict[tuple[str, str | None], object] = {}
        for r in db.scalars(select(Response).where(Response.engagement_id == e.id, Response.deleted_at.is_(None))):
            code = by_q.get(r.question_id)
            if code:
                self.answers[(code, r.ai_system_id)] = r

    def section(self, code: str | None) -> str:
        if not code:
            return ""
        title = self.sections.get(code)
        return f"{code} {title}" if title else code

    def _answer(self, code: str, system_id: str | None) -> str:
        r = self.answers.get((code, system_id)) or self.answers.get((code, None))
        if r is None:
            return ""
        if r.status == "not_yet_in_place":
            return "Not yet in place"
        if r.status == "na":
            return "Not applicable"
        if r.status != "answered":
            return ""
        q = self.questions.get(code)
        text = option_label(q, r.value) if q else str(r.value)
        return text if len(text) <= 240 else text[:237].rsplit(" ", 1)[0] + "..."

    def questions_for(self, f) -> list[dict]:
        out = []
        for code in f.source_question_ids or []:
            q = self.questions.get(code)
            out.append({"code": code, "label": q.label if q else "Question not in the current questionnaire", "answer": self._answer(code, f.ai_system_id)})
        return out

    def evidence_for(self, f) -> list[dict]:
        out = []
        s = self.systems.get(f.ai_system_id or "")
        ucs = set(f.use_case_ids or []) | set((s.use_case_ids or []) if s else [])
        for er in self.ers:
            if not ((er.use_case_id and er.use_case_id in ucs) or (er.ai_system_id and er.ai_system_id == f.ai_system_id)):
                continue
            status = {"received": "provided", "answered": "answered", "outstanding": "requested, not yet provided", "waived": "waived"}.get(er.status, er.status)
            files = _files(self.db, er.file_ids)
            detail = f"{status}: {files}" if files else status
            out.append({"ref": er.ref, "text": er.description.rstrip("."), "status": detail, "answer": (er.answer or "").strip()})
        for d, item in self.docs:
            if item is None:
                continue
            linked = d.finding_id == f.id
            same_system = d.ai_system_id is None or d.ai_system_id == f.ai_system_id
            if not (linked or (same_system and _related(item.template_section, f.template_section))):
                continue
            sys = self.systems.get(d.ai_system_id or "")
            title = item.title + (f" ({sys.reference_id})" if sys else "")
            files = _files(self.db, d.evidence_ids)
            status = {"received": f"received: {files}" if files else "received", "pending": "requested, not provided",
                      "not_available": "the client confirmed it does not exist"}.get(d.status, d.status)
            out.append({"ref": item.code if getattr(item, "code", None) else "", "text": title, "status": status, "answer": ""})
        return out
