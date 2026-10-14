"""Per-system risk scoring (spec §19.2–19.4). Pure functions: no database, no clock.

Ratings are lower-case keys: low < medium < high < critical.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.questionnaire.rules import EngagementFacts, SystemContext, is_applicable

RATINGS = ("low", "medium", "high", "critical")
FACTOR_LABELS = {
    "decision_type": "Decision type", "consequence": "Consequence of error", "protected_classes": "Protected classes", "data_sensitivity": "Data sensitivity",
    "regulated_context": "Regulated context", "volume": "Volume", "system_type": "System type", "exposure": "Exposure",
}


def r1(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def r2(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass
class Methodology:
    version: str
    factors: dict
    domains: dict
    domain_weights_by_build_type: dict
    build_type_weights: dict
    light_domains: list
    proposed_score_bands: list
    bands: list
    knockout_rules: list
    eu_ai_act: dict
    override_rationale_threshold: int = 1
    max_control_reduction: float = 0.75

    @classmethod
    def from_yaml(cls, d: dict) -> "Methodology":
        return cls(version=str(d["version"]), factors=d["factors"], domains=d["domains"], domain_weights_by_build_type=d["domain_weights_by_build_type"], build_type_weights=d["build_type_weights"],
                   light_domains=d["light_domains"], proposed_score_bands=d["proposed_score_bands"], bands=d["bands"], knockout_rules=d["knockouts"], eu_ai_act=d["eu_ai_act"],
                   override_rationale_threshold=d.get("override_rationale_threshold", 1), max_control_reduction=d.get("max_control_reduction", 0.75))

    @classmethod
    def from_row(cls, row) -> "Methodology":
        c = row.config or {}
        return cls(version=row.version, factors=row.factor_weights, domains=c["domains"], domain_weights_by_build_type=row.domain_weights_by_build_type, build_type_weights=c["build_type_weights"],
                   light_domains=c["light_domains"], proposed_score_bands=c["proposed_score_bands"], bands=row.bands, knockout_rules=row.knockout_rules, eu_ai_act=c["eu_ai_act"],
                   override_rationale_threshold=c.get("override_rationale_threshold", 1), max_control_reduction=c.get("max_control_reduction", 0.75))


@dataclass
class FactorInputs:
    scores: dict[str, int | None]
    eu_classification: str | None = None  # 3.3.08: prohibited | high | limited | minimal | ...


@dataclass
class FactorRow:
    key: str
    label: str
    question: str
    score: int | None
    weight: float
    points: float | None


@dataclass
class Knockout:
    code: str
    force: str
    label: str


@dataclass
class DomainInputs:
    pct_confirmed: dict[str, float | None] = field(default_factory=dict)  # None: no applicable checklist item
    open_high_or_critical: dict[str, int] = field(default_factory=dict)


# ---- inherent risk (§19.2)
def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def factor_scores(answers: dict, m: Methodology) -> dict[str, int | None]:
    """Factor scores 1–5 from the answers (question code → value). None when the answer is missing."""
    out: dict[str, int | None] = {}
    for key, f in m.factors.items():
        if "levels" in f:
            if all(answers.get(q) in (None, "", []) for q in f["questions"]):
                out[key] = None
                continue
            ctx, facts = SystemContext(), EngagementFacts()
            out[key] = next((lv["score"] for lv in f["levels"] if lv["rule"] is None or is_applicable(lv["rule"], answers, ctx, facts)), None)
        elif "bands" in f:
            n = _num(answers.get(f["question"]))
            out[key] = None if n is None else next(b["score"] for b in f["bands"] if b["max"] is None or n <= b["max"])
        else:
            v = answers.get(f["question"])
            scores = {str(k).casefold(): s for k, s in f["scores"].items()}
            if isinstance(v, list):
                hits = [scores[str(x).casefold()] for x in v if str(x).casefold() in scores]
                out[key] = max(hits) if hits else None
            else:
                out[key] = scores.get(str(v).casefold()) if v not in (None, "") else None
    return out


def inherent(f: FactorInputs, m: Methodology) -> tuple[float | None, list[FactorRow]]:
    """Σ weight × (score ÷ 5) × 100, rounded to 1 dp; None until every factor has a score. EU AI Act high-risk: at least 70."""
    rows = []
    for key, spec in m.factors.items():
        s = f.scores.get(key)
        w = float(spec["weight"])
        rows.append(FactorRow(key=key, label=FACTOR_LABELS.get(key, key), question=spec.get("question") or ", ".join(spec.get("questions", [])), score=s, weight=w, points=r1(w * s / 5 * 100) if s is not None else None))
    if any(r.score is None for r in rows):
        return None, rows
    total = r1(sum(r.weight * r.score / 5 * 100 for r in rows))
    if (f.eu_classification or "").casefold() == "high":
        total = max(total, float(m.eu_ai_act.get("high_floor", 70)))
    return total, rows


# ---- control maturity (§19.3)
def proposed_domain_score(pct_confirmed: float, open_high_or_critical: int) -> int:
    """Band the evidence-confirmed share of checklist items, minus 1 per open High or Critical finding, minimum 1."""
    bands = [(80, 5), (60, 4), (40, 3), (20, 2), (0, 1)]
    base = next(score for floor, score in bands if pct_confirmed >= floor)
    return max(1, base - open_high_or_critical)


def domain_weights(build_type: str | None, depth: str, m: Methodology) -> dict[str, float]:
    """Weights for the build type (open source and hybrid use in-house weights); a light assessment rescales over its domains (D17)."""
    w = dict(m.domain_weights_by_build_type[m.build_type_weights.get(build_type or "in_house", "in_house")])
    if depth == "light":
        w = {k: v for k, v in w.items() if k in m.light_domains}
        total = sum(w.values())
        w = {k: v / total for k, v in w.items()}
    return w


def maturity(domain_scores: dict[str, int | None], build_type: str | None, depth: str, m: Methodology) -> float | None:
    w = domain_weights(build_type, depth, m)
    if any(domain_scores.get(d) is None for d in w):
        return None
    return r2(sum(weight * domain_scores[d] for d, weight in w.items()))


def control_effectiveness(m_score: float) -> float:
    return (m_score - 1) / 4


# ---- residual and rating (§19.4)
def residual(inherent_score: float, m_score: float, m: Methodology) -> float:
    return r1(inherent_score * (1 - m.max_control_reduction * control_effectiveness(m_score)))


def band(residual_score: float, m: Methodology) -> str:
    return next(b["rating"] for b in sorted(m.bands, key=lambda b: -b["min"]) if residual_score >= b["min"])


def knockouts(answers: dict, m: Methodology) -> list[Knockout]:
    """Answers here already count "not yet in place" as "no"."""
    ctx, facts = SystemContext(), EngagementFacts()
    return [Knockout(code=k["code"], force=k["force"], label=k["label"]) for k in m.knockout_rules if is_applicable(k["rule"], answers, ctx, facts)]


def worst(*ratings: str | None) -> str | None:
    present = [r for r in ratings if r]
    return max(present, key=RATINGS.index) if present else None


def final_rating(computed: str | None, kos: list[Knockout], eu_prohibited: bool) -> str | None:
    if eu_prohibited:
        return "critical"
    return worst(computed, *(k.force for k in kos))
