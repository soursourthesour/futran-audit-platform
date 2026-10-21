"""The one risk level scale used everywhere: system ratings, finding severities, the report, the PDF and Word files and
the screens. Change the wording here and nowhere else.

Level 5 is the most serious. Critical to Low come from the residual risk score (methodology bands); Observation is for
findings only and is never a system rating.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLevel:
    key: str
    level: int
    label: str
    definition: str
    response_days: int
    response_text: str
    fill: str  # cell shading in the PDF and Word report
    ink: str  # text on that shading (contrast at least 4.5:1)


RISK_LEVELS: tuple[RiskLevel, ...] = (
    RiskLevel("critical", 5, "Critical",
              "A control failure that exposes the organization to a likely breach of law or regulation, or to serious harm to "
              "the people the system affects. Management should consider suspending or restricting use until it is fixed.",
              30, "30 days", "7A1F1F", "FFFFFF"),
    RiskLevel("high", 4, "High",
              "A significant weakness that could lead to a breach of law or regulation, or to material harm, if it is not "
              "corrected. It needs prompt action and senior management oversight.",
              90, "90 days", "B93A0B", "FFFFFF"),
    RiskLevel("medium", 3, "Medium",
              "A control weakness that raises risk but is partly offset by other controls. Correct it within the normal "
              "planning cycle.",
              182, "182 days (6 months)", "F2C14E", "1D2433"),
    RiskLevel("low", 2, "Low",
              "A minor weakness or documentation gap with limited impact on its own. Correct it as part of routine improvement.",
              365, "365 days (12 months)", "2F6B45", "FFFFFF"),
    RiskLevel("observation", 1, "Observation",
              "No material risk. A good practice worth extending, or an improvement to consider. Used for findings only, "
              "never as a system rating.",
              365, "No deadline; consider within 12 months", "E2E8F0", "334155"),
)
BY_KEY = {r.key: r for r in RISK_LEVELS}
BY_LABEL = {r.label: r for r in RISK_LEVELS}
RATING_KEYS = ("critical", "high", "medium", "low")  # system ratings; findings add "observation"
RESPONSE_DAYS = {r.key: r.response_days for r in RISK_LEVELS}


def level(key: str | None) -> int | None:
    r = BY_KEY.get(key or "")
    return r.level if r else None


def label(key: str | None) -> str | None:
    r = BY_KEY.get(key or "")
    return r.label if r else None


def labelled(key: str | None, missing: str = "Not rated") -> str:
    """'High (4)': the label with its level number, as the report shows every rating and severity."""
    r = BY_KEY.get(key or "")
    return f"{r.label} ({r.level})" if r else missing


def from_labelled(text: str) -> RiskLevel | None:
    """The level a cell such as 'High (4)' shows, for shading it. None for any other text."""
    text = " ".join((text or "").split())
    for r in RISK_LEVELS:
        if text == f"{r.label} ({r.level})":
            return r
    return None


def _num(x: float) -> str:
    return f"{x:g}"


def residual_ranges(bands: list[dict]) -> dict[str, str]:
    """Residual score range for each rating, from the methodology bands: {'high': '50–74.9', ...}."""
    ordered = sorted(bands, key=lambda b: b["min"])
    out = {}
    for i, b in enumerate(ordered):
        top = f"{_num(ordered[i + 1]['min'] - 0.1)}" if i + 1 < len(ordered) else "100"
        out[b["rating"]] = f"{_num(b['min'])}–{top}"
    return out


def scale_rows(bands: list[dict]) -> list[dict]:
    """The scale as the report prints it, most serious first."""
    ranges = residual_ranges(bands)
    return [{"key": r.key, "level": r.level, "label": r.label, "labelled": f"{r.label} ({r.level})", "definition": r.definition,
             "residual_range": ranges.get(r.key, "Not used for systems"), "response": r.response_text, "response_days": r.response_days}
            for r in RISK_LEVELS]


def public_scale() -> list[dict]:
    """For the screens: key, level and label."""
    return [{"key": r.key, "level": r.level, "label": r.label} for r in RISK_LEVELS]


# ---- maturity and consequence
MATURITY_LEVELS: tuple[tuple[int, str, str], ...] = (
    (1, "None", "No control exists, or it exists only as an intention. Staff cannot point to a policy, owner or record, and the "
                "auditor finds nothing to test."),
    (2, "Initial or ad hoc", "Some practice exists but depends on individuals. It is informal, undocumented or applied to some "
                             "systems and not others, and results vary from one occasion to the next."),
    (3, "Defined and documented", "A written, approved procedure with a named owner is in place and staff follow it. Records "
                                  "exist, but the organization does not yet measure whether the control works."),
    (4, "Managed and measured", "The documented control is monitored with metrics, exceptions are tracked and escalated, and "
                                "management reviews the results on a set schedule. Evidence shows it operating over time."),
    (5, "Optimized", "The control is measured, reviewed independently and improved from lessons learned and incidents. It is "
                     "built into the system life cycle and applied consistently across all AI systems."),
)

CONSEQUENCE_LEVELS: tuple[tuple[int, str, str], ...] = (
    (1, "Negligible", "Errors cause minor inconvenience that is noticed and corrected in normal work, with no effect on anyone's "
                      "rights, money or access to services."),
    (2, "Minor", "Errors cause limited, reversible effects on individuals or the business, corrected through normal processes."),
    (3, "Moderate", "Errors cause noticeable harm, such as delay, financial loss or poor service, that can be reversed with effort."),
    (4, "Serious", "Errors significantly affect people's access to employment, credit, insurance, healthcare, housing or similar "
                 "opportunities, or create material regulatory exposure. Harm is hard to reverse."),
    (5, "Severe", "Errors cause serious or irreversible harm to health, safety, liberty or livelihood, or severe legal, "
                  "regulatory or financial consequences."),
)


def maturity_rows() -> list[dict]:
    return [{"level": n, "name": name, "description": text} for n, name, text in MATURITY_LEVELS]


def consequence_rows() -> list[dict]:
    return [{"level": n, "name": name, "description": text} for n, name, text in CONSEQUENCE_LEVELS]
