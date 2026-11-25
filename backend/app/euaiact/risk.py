"""EU AI Act risk level beside the Futran tier (11-25 change).

The Futran tier (1 baseline, 2 elevated, 3 high-risk) rates harm from data, accounts and decisions about people. The EU
level is a separate answer to a different question: what the Act makes of the use. Three screening questions decide it,
first match wins: an Art. 5 practice → prohibited; an Annex I product or an Annex III area (unless a documented
Art. 6(3) assessment) → high-risk; an Art. 50 situation → limited risk; otherwise minimal risk. General-purpose AI is a
flag, not a level. Labels and question wording live in `seeds/eu_ai_act.yaml` so the legal reviewer can change them.

Screening shape: {"art5": [keys] | ["none"], "annex_iii_area": key | "none", "annex_i": bool, "art6_3_exception": bool,
"art50": [keys] | ["none"], "gpai": bool}. An empty list or a missing area means the question is unanswered."""
from __future__ import annotations

from app.euaiact import rules

NONE = "none"
NOT_SCREENED = "Not screened against the EU AI Act yet."


def _d() -> dict:
    return rules.data()


def _levels() -> dict[str, str]:
    return dict(_d()["risk_levels"])


LEVELS = _levels()


def art5_practices() -> dict[str, str]:
    return dict(_d()["art5_practices"])


def art50_situations() -> dict[str, str]:
    return dict(_d()["art50_situations"])


def label(level: str | None) -> str:
    return _levels().get(level or "", "Not screened")


def options() -> dict:
    """Everything a form needs to ask the three screening questions."""
    d = _d()
    return {
        "levels": _levels(), "art5": art5_practices(), "art50": art50_situations(),
        "annex_iii_areas": {k: v["label"] for k, v in rules.areas().items()},
        "annex_i_label": d["annex_i_label"], "art6_3_label": d["art6_3_label"], "gpai_label": d["gpai_label"],
    }


def _picked(values) -> list[str]:
    return [v for v in (values or []) if v != NONE]


def complete(s: dict | None) -> bool:
    return bool(s) and bool(s.get("art5")) and bool(s.get("annex_iii_area")) and bool(s.get("art50"))


def level_for(s: dict | None) -> tuple[str | None, str]:
    """(level, reason) from a screening; (None, NOT_SCREENED) until all three questions are answered."""
    practices = _picked((s or {}).get("art5"))
    if practices:  # shown even when the other answers are blank (review 11-25 #6)
        names = art5_practices()
        return "prohibited", "Prohibited practice: " + "; ".join(names.get(p, p) for p in practices) + "."
    if not complete(s):
        return None, NOT_SCREENED
    area = s.get("annex_iii_area")
    area_label = rules.areas().get(area or "", {}).get("label") if area and area != NONE else None
    also = " Art. 50 transparency duties also apply." if _picked(s.get("art50")) else ""
    if s.get("annex_i"):
        return "high_risk", "Product-safety component or product under Annex I." + also
    if area_label and not s.get("art6_3_exception"):
        return "high_risk", f"Used in an Annex III area: {area_label}." + also
    note = f" Annex III area ({area_label}), but a documented Art. 6(3) assessment shows no significant risk." if area_label else ""
    situations = _picked(s.get("art50"))
    if situations:
        names = art50_situations()
        return "limited", "Transparency duties apply: " + "; ".join(names.get(x, x) for x in situations) + "." + note
    return "minimal", "No prohibited practice, no high-risk use and no Art. 50 transparency situation." + note


def level_from_classification(classification: str | None) -> str | None:
    """The level a signed-off EU workspace classification stands for. GPAI is a model, not a level: None."""
    return dict(_d()["classification_levels"]).get(classification or "")


def clean_screening(raw, errs: list[dict]) -> dict | None:
    """Validate a screening payload. None clears it. Unknown keys are reported against `eu_screening.<question>`."""
    if raw in (None, "", {}):
        return None
    if not isinstance(raw, dict):
        errs.append({"field": "eu_screening", "message": "Answer the EU AI Act screening questions."})
        return None
    out: dict = {}
    for q, allowed in (("art5", art5_practices()), ("art50", art50_situations())):
        vals = raw.get(q) or []
        if not isinstance(vals, list) or any(v != NONE and v not in allowed for v in vals):
            errs.append({"field": f"eu_screening.{q}", "message": "Choose from the listed situations, or none of them."})
            vals = []
        picked = list(dict.fromkeys(_picked(vals)))
        out[q] = picked or ([NONE] if NONE in vals else [])
    area = raw.get("annex_iii_area") or None
    if area is not None and area != NONE and area not in rules.areas():
        errs.append({"field": "eu_screening.annex_iii_area", "message": "Choose an Annex III area, or none."})
        area = None
    out["annex_iii_area"] = area
    for flag in ("annex_i", "art6_3_exception", "gpai"):
        v = raw.get(flag)
        out[flag] = v is True or (isinstance(v, str) and v.lower() in ("yes", "true", "1")) or (isinstance(v, int) and not isinstance(v, bool) and v == 1)
    if not out["annex_iii_area"] or out["annex_iii_area"] == NONE:
        out["art6_3_exception"] = False
    return out


ORDER = {"prohibited": 4, "high_risk": 3, "limited": 2, "minimal": 1}


def highest(levels) -> str | None:
    """The most severe level among several use cases (for a system that serves them all); None if none is screened."""
    known = [x for x in levels if x in ORDER]
    return max(known, key=ORDER.get) if known else None


def summary(s: dict | None) -> str | None:
    """One line for change history: the three answers in plain words."""
    if not s:
        return None
    area = s.get("annex_iii_area")
    parts = [
        "Art. 5: " + (", ".join(art5_practices().get(x, x).split(" (Art.")[0] for x in _picked(s.get("art5"))) or ("none" if s.get("art5") else "not answered")),
        "Annex III: " + (rules.areas().get(area, {}).get("label", area) if area and area != NONE else ("none" if area else "not answered"))
        + (" (Art. 6(3) assessment)" if s.get("art6_3_exception") else ""),
        "Annex I product: " + ("yes" if s.get("annex_i") else "no"),
        "Art. 50: " + (", ".join(art50_situations().get(x, x).split(" (Art.")[0] for x in _picked(s.get("art50"))) or ("none" if s.get("art50") else "not answered")),
    ]
    if s.get("gpai"):
        parts.append("general-purpose AI model")
    return "; ".join(parts)


def out(screening: dict | None, level: str | None, reason: str | None, *, set_by_futran: bool = False) -> dict:
    """The EU fields every serializer adds next to the tier."""
    return {"eu_screening": screening, "eu_risk_level": level, "eu_risk_label": label(level), "eu_risk_reason": reason or NOT_SCREENED,
            "eu_gpai": bool((screening or {}).get("gpai")), "eu_set_by_futran": set_by_futran}
