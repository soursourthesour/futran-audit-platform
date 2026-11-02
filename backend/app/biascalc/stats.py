"""Bias audit statistics for automated employment decision tools (NYC Local Law 144), in plain Python.

Source: NYC Department of Consumer and Worker Protection, Notice of Adoption of Final Rule, Title 6 RCNY Chapter 5
Subchapter T, §§ 5-300 to 5-304 (adopted 6 April 2023; text read from
https://rules.cityofnewyork.us/wp-content/uploads/2023/04/DCWP-NOA-for-Use-of-Automated-Employment-Decisionmaking-Tools-2.pdf).
The definitions this module implements, quoted:

  § 5-300 "Selection rate" means the rate at which individuals in a category are either selected to move forward in the
  hiring process or assigned a classification by an AEDT. Such rate may be calculated by dividing the number of
  individuals in the category moving forward or assigned a classification by the total number of individuals in the
  category who applied for a position or were considered for promotion.

  § 5-300 "Scoring Rate" means the rate at which individuals in a category receive a score above the sample's median
  score, where the score has been calculated by an AEDT.

  § 5-300 "Impact ratio" means either (1) the selection rate for a category divided by the selection rate of the most
  selected category or (2) the scoring rate for a category divided by the scoring rate for the highest scoring category.

  § 5-300 "Category" means any component 1 category required to be reported by employers pursuant to subsection (c) of
  section 2000e-8 of title 42 of the United States Code as specified in part 1602.7 of title 29 of the Code of Federal
  Regulations, as designated on the Equal Employment Opportunity Commission Employer Information Report EEO-1.

  § 5-301(b) [selection] ... (3) Ensure that the calculations ... separately calculate the impact of the AEDT on: i. Sex
  categories ..., ii. Race/Ethnicity categories ..., and iii. intersectional categories of sex, ethnicity, and race ...
  (5) Indicate the number of individuals the AEDT assessed that are not included in the required calculations because
  they fall within an unknown category.

  § 5-301(c) [scoring] (1) Calculate the median score for the full sample of applicants; (2) Calculate the scoring rate
  for individuals in each category; (3) Calculate the impact ratio for each category; (4) [sex, race/ethnicity and
  intersectional, as above]; and (5) Indicate the number of individuals the AEDT assessed that are not included in the
  required calculations because they fall within an unknown category.

  § 5-301(d) ... an independent auditor may exclude a category that represents less than 2% of the data being used for
  the bias audit from the required calculations for impact ratio. Where such a category is excluded, the summary of
  results must include the independent auditor's justification for the exclusion, as well as the number of applicants
  and scoring rate or selection rate for the excluded category.

The rule's two worked examples (résumé screening by selection rate; "culture fit" by scoring rate) are reproduced in
tests/biascalc/test_stats.py.

Rulings where the rule is silent (each is a choice an auditor can defend; see the WS-K report):
- Categories are the EEO-1 component 1 categories: sex Male/Female; race/ethnicity Hispanic or Latino, then six races
  that are Not Hispanic or Latino. Intersectional categories are sex × race/ethnicity (14), as in the rule's tables.
- Unknowns are left out per table: a person with a known race but unknown sex is in the race/ethnicity table and not in
  the sex or intersectional tables. Each table reports its own unknown count; `unknown_count` is the number with an
  unknown sex or race/ethnicity, which is how the rule's notes count them. (The rule's selection example has 13 more
  people in the race table than in the sex and intersectional tables, which this reading explains.)
- The median for the scoring-rate method is taken over every scored individual in the data, including those in an
  unknown category ("the full sample of applicants"). "Above" the median is strictly greater.
- The 2% test for an excluded category is measured against the people in that table (known categories only). An excluded
  category keeps its applicants and rate, has no impact ratio and is never the reference ("most selected") category.
- Impact ratios are computed from unrounded rates. Exactly the threshold (0.80 by default) is not flagged.
- When no included category has a positive rate, no impact ratio can be calculated.
- Additional metrics (spec §21 F11): statistical parity difference = category rate − reference rate; equal opportunity
  difference = category true positive rate − reference true positive rate, where the true positive rate is the
  selection (or scoring) rate among people whose outcome label is positive, only when the data has outcome labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field

LIBRARY_VERSION = "futran-biascalc 1.0 (6 RCNY § 5-301, rule adopted 6 April 2023)"

SEX = {"male": "Male", "female": "Female"}
RACE = {
    "hispanic_latino": "Hispanic or Latino",
    "white": "White",
    "black": "Black or African American",
    "nhpi": "Native Hawaiian or Pacific Islander",
    "asian": "Asian",
    "aian": "Native American or Alaska Native",
    "two_or_more": "Two or More Races",
}
NOT_HISPANIC = " (not Hispanic or Latino)"
DIMENSIONS = {"sex": "Sex", "race": "Race/ethnicity", "intersectional": "Intersectional"}
METHODS = {"selection_rate": "Selection rate", "scoring_rate": "Scoring rate"}


def inter_key(sex: str, race: str) -> str:
    return f"{race}|{sex}"


def label(dimension: str, key: str) -> str:
    if dimension == "sex":
        return SEX[key]
    if dimension == "race":
        return RACE[key] + ("" if key == "hispanic_latino" else NOT_HISPANIC)
    race, sex = key.split("|")
    return f"{RACE[race]} {SEX[sex].lower()}" + ("" if race == "hispanic_latino" else NOT_HISPANIC)


def _order(dimension: str) -> list[str]:
    if dimension == "sex":
        return list(SEX)
    if dimension == "race":
        return list(RACE)
    return [inter_key(s, r) for r in RACE for s in SEX]


@dataclass
class Row:
    id: str
    selected: bool | None = None
    score: float | None = None
    sex: str | None = None  # a SEX key, or None for unknown
    race: str | None = None  # a RACE key, or None for unknown
    age_band: str | None = None
    label: bool | None = None  # outcome label (e.g. qualified), for equal opportunity


@dataclass
class CategoryResult:
    key: str
    label: str
    applicants: int
    selected: int  # selected, or scoring above the median
    rate: float
    share: float  # of the people in this table
    impact_ratio: float | None = None
    excluded: bool = False
    below_threshold: bool = False
    parity_difference: float | None = None
    true_positive_rate: float | None = None
    equal_opportunity_difference: float | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Table:
    dimension: str
    categories: list[CategoryResult]
    unknown: int = 0
    unknown_selected: int = 0
    reference: str | None = None
    excluded: list[str] = field(default_factory=list)
    note: str | None = None

    @property
    def lowest(self) -> tuple[str, float] | None:
        rated = [c for c in self.categories if c.impact_ratio is not None]
        if not rated:
            return None
        c = min(rated, key=lambda c: c.impact_ratio)
        return c.key, c.impact_ratio

    def as_dict(self) -> dict:
        low = self.lowest
        return {"dimension": self.dimension, "label": DIMENSIONS[self.dimension], "categories": [c.as_dict() for c in self.categories], "unknown": self.unknown,
                "unknown_selected": self.unknown_selected, "reference": self.reference, "excluded": self.excluded, "note": self.note,
                "lowest": {"key": low[0], "impact_ratio": low[1]} if low else None}


def table_from_counts(dimension: str, counts: dict[str, tuple[int, int]], *, exclude_small: bool = True, small_share: float = 0.02, threshold: float = 0.80,
                      tp: dict[str, tuple[int, int]] | None = None, unknown: int = 0, unknown_selected: int = 0) -> Table:
    """One table from (applicants, selected) per category. `tp` holds (labelled positive, selected among them) per category."""
    total = sum(n for n, _ in counts.values())
    cats: list[CategoryResult] = []
    for key in _order(dimension):
        if key not in counts or counts[key][0] == 0:
            continue
        n, k = counts[key]
        share = n / total if total else 0.0
        c = CategoryResult(key=key, label=label(dimension, key), applicants=n, selected=k, rate=k / n, share=share)
        c.excluded = exclude_small and share < small_share
        if tp is not None and tp.get(key, (0, 0))[0]:
            pos, hit = tp[key]
            c.true_positive_rate = hit / pos
        cats.append(c)
    t = Table(dimension=dimension, categories=cats, unknown=unknown, unknown_selected=unknown_selected, excluded=[c.key for c in cats if c.excluded])
    included = [c for c in cats if not c.excluded]
    ref = max(included, key=lambda c: c.rate, default=None)
    if ref is None or ref.rate == 0:
        t.note = "No category has a positive rate, so impact ratios cannot be calculated."
        return t
    t.reference = ref.key
    for c in included:
        c.impact_ratio = 1.0 if c is ref else c.rate / ref.rate
        c.below_threshold = c.impact_ratio < threshold
        c.parity_difference = c.rate - ref.rate
        if c.true_positive_rate is not None and ref.true_positive_rate is not None:
            c.equal_opportunity_difference = c.true_positive_rate - ref.true_positive_rate
    return t


def median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        raise ValueError("median of no values")
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2


@dataclass
class Result:
    method: str
    tables: dict[str, Table]
    total: int
    selected_total: int
    unknown_count: int
    median: float | None
    has_labels: bool
    settings: dict

    def as_dict(self) -> dict:
        return {"method": self.method, "total": self.total, "selected_total": self.selected_total, "unknown_count": self.unknown_count, "median": self.median,
                "has_labels": self.has_labels, "settings": self.settings, "tables": {k: t.as_dict() for k, t in self.tables.items()}, "library_version": LIBRARY_VERSION}


def compute(rows: list[Row], *, method: str, exclude_small: bool = True, small_share: float = 0.02, threshold: float = 0.80) -> Result:
    """Selection or scoring rates and impact ratios by sex, race/ethnicity and intersectional category."""
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}")
    med = None
    if method == "scoring_rate":
        med = median([r.score for r in rows if r.score is not None])
        hit = [r.score is not None and r.score > med for r in rows]
    else:
        hit = [bool(r.selected) for r in rows]
    has_labels = any(r.label is not None for r in rows)

    def key_of(dim: str, r: Row) -> str | None:
        if dim == "sex":
            return r.sex
        if dim == "race":
            return r.race
        return inter_key(r.sex, r.race) if r.sex and r.race else None

    tables = {}
    for dim in DIMENSIONS:
        counts: dict[str, list[int]] = {}
        tp: dict[str, list[int]] = {}
        unk = unk_sel = 0
        for r, h in zip(rows, hit):
            k = key_of(dim, r)
            if k is None:
                unk += 1
                unk_sel += h
                continue
            c = counts.setdefault(k, [0, 0])
            c[0] += 1
            c[1] += h
            if r.label:
                p = tp.setdefault(k, [0, 0])
                p[0] += 1
                p[1] += h
        tables[dim] = table_from_counts(dim, {k: (n, s) for k, (n, s) in counts.items()}, exclude_small=exclude_small, small_share=small_share, threshold=threshold,
                                        tp={k: (n, s) for k, (n, s) in tp.items()} if has_labels else None, unknown=unk, unknown_selected=unk_sel)
    return Result(method=method, tables=tables, total=len(rows), selected_total=sum(hit), unknown_count=sum(1 for r in rows if not (r.sex and r.race)), median=med,
                  has_labels=has_labels, settings={"exclude_small": exclude_small, "small_share": small_share, "threshold": threshold})
