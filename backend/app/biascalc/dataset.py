"""Reading applicant or employee data for the bias calculator (spec §21 F11): one row per person assessed by the tool.

Columns (names are matched without regard to case, spaces or punctuation):
  id            applicant or candidate identifier, unique in the file (required)
  selected      yes/no, true/false or 1/0: moved forward or assigned the classification (selection-rate method)
  score         the score the tool gave (scoring-rate method)
  sex           Male or Female; blank or "unknown" for the unknown category
  race          race/ethnicity, one of the seven EEO-1 component 1 categories; blank or "unknown" for unknown
  ethnicity     optional, Hispanic or Latino / Not Hispanic or Latino, beside a race column (the two-question format).
                Combined as EEO-1 does: Hispanic or Latino whatever the race; otherwise the race; unknown with no race.
                A file with an ethnicity column and no race column reads it as the race/ethnicity column.
  age_band      optional, kept for reference (Local Law 144 does not require it)
  qualified     optional outcome label (yes/no) for the equal opportunity difference

Values that cannot be read are errors with their row number (the file's own line number, header = 1), so the auditor
cleans the data at source rather than the calculator guessing.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field

from app.biascalc.stats import Row

MAX_ROWS = 200_000
MAX_LISTED_ERRORS = 200
ALIASES = {
    "id": ("id", "applicantid", "candidateid", "personid", "employeeid", "applicant", "candidate"),
    "selected": ("selected", "advanced", "movedforward", "selectedyn"),
    "score": ("score", "aedtscore", "toolscore"),
    "sex": ("sex", "gender"),
    "race": ("raceethnicity", "race", "raceandethnicity"),
    "ethnicity": ("ethnicity", "hispanicorlatino", "hispaniclatino", "hispanicethnicity"),
    "age_band": ("ageband", "age", "agegroup"),
    "label": ("qualified", "label", "outcomelabel", "outcome", "actualoutcome"),
}
TRUE = {"yes", "y", "true", "t", "1", "selected", "advanced"}
FALSE = {"no", "n", "false", "f", "0", "notselected", "rejected", "notadvanced"}
UNKNOWN = {"", "unknown", "notknown", "notspecified", "notprovided", "declined", "declinedtostate", "declinetostate", "prefernottosay", "prefernottoanswer",
           "notdisclosed", "na", "none", "null", "blank", "unanswered", "selfidentifynotprovided"}
OUTSIDE_EEO1_SEX = {"nonbinary", "x", "other", "anothergender", "genderqueer", "intersex"}
SEX = {"male": "male", "m": "male", "man": "male", "female": "female", "f": "female", "woman": "female"}
RACE = {
    "hispanicorlatino": "hispanic_latino", "hispanic": "hispanic_latino", "latino": "hispanic_latino", "latina": "hispanic_latino", "latinx": "hispanic_latino", "hispaniclatino": "hispanic_latino",
    "white": "white", "caucasian": "white",
    "blackorafricanamerican": "black", "black": "black", "africanamerican": "black",
    "nativehawaiianorpacificislander": "nhpi", "nativehawaiianorotherpacificislander": "nhpi", "pacificislander": "nhpi", "nativehawaiian": "nhpi", "nhpi": "nhpi",
    "asian": "asian",
    "nativeamericanoralaskanative": "aian", "americanindianoralaskanative": "aian", "americanindian": "aian", "nativeamerican": "aian", "alaskanative": "aian", "aian": "aian",
    "twoormoreraces": "two_or_more", "twoormore": "two_or_more", "multiracial": "two_or_more", "multipleraces": "two_or_more", "twoormore races": "two_or_more",
}
RACE.update({k.replace("_", ""): k for k in ("hispanic_latino", "white", "black", "nhpi", "asian", "aian", "two_or_more")})
HISPANIC = {"hispanicorlatino", "hispanic", "latino", "latina", "latinx", "hispaniclatino", "yes", "y", "true", "1"}
NOT_HISPANIC = {"nothispanicorlatino", "nothispanic", "nonhispanic", "nonhispanicorlatino", "notlatino", "notlatinx", "no", "n", "false", "0"}


def _norm(s: str) -> str:
    s = re.sub(r"\(\s*not\s+hispanic\s+or\s+latino\s*\)|,?\s*not\s+hispanic\s+or\s+latino", "", s, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", s.casefold())


@dataclass
class Parsed:
    rows: list[Row] = field(default_factory=list)
    report: dict = field(default_factory=dict)
    methods: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.report.get("errors")


def _text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse(data: bytes) -> Parsed:
    errors: list[dict] = []
    warnings: list[str] = []
    p = Parsed(report={"rows_read": 0, "rows_valid": 0, "columns": {}, "errors": errors, "warnings": warnings, "has_labels": False,
                       "unknown": {"sex": 0, "race": 0, "either": 0}, "error_count": 0})

    def err(row: int | None, fld: str, msg: str) -> None:
        p.report["error_count"] += 1
        if len(errors) < MAX_LISTED_ERRORS:
            errors.append({"row": row, "field": fld, "message": msg})

    text = _text(data or b"")
    if not text.strip():
        err(None, "file", "The file is empty. Upload a CSV file with a header row and one row per person.")
        return p
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except (StopIteration, csv.Error):
        err(None, "file", "The file could not be read as CSV.")
        return p
    cols: dict[str, int] = {}
    for i, h in enumerate(header):
        key = _norm(h)
        for name, aliases in ALIASES.items():
            if key in aliases and name not in cols:
                cols[name] = i
    if "ethnicity" in cols and "race" not in cols:  # one column holding the combined race/ethnicity categories
        cols["race"] = cols.pop("ethnicity")
    p.report["columns"] = {k: header[i].strip() for k, i in sorted(cols.items(), key=lambda kv: list(ALIASES).index(kv[0]))}
    if "id" not in cols:
        err(1, "id", "Add a column named id for the applicant or candidate identifier.")
    if "selected" not in cols and "score" not in cols:
        err(1, "selected", "Add a column named selected (yes or no) or score (a number).")
    if "sex" not in cols:
        err(1, "sex", "Add a column named sex (Male, Female, or blank for unknown).")
    if "race" not in cols:
        err(1, "race", "Add a column named race_ethnicity (the EEO-1 categories, or blank for unknown).")
    if errors:
        return p
    p.methods = [m for m, c in (("selection_rate", "selected"), ("scoring_rate", "score")) if c in cols]
    p.report["has_labels"] = "label" in cols
    seen: set[str] = set()
    outside = Counter()
    for line_no, rec in enumerate(reader, start=2):
        if not any(v.strip() for v in rec):
            continue
        p.report["rows_read"] += 1
        if p.report["rows_read"] > MAX_ROWS:
            err(None, "file", f"The file has more than {MAX_ROWS:,} rows. Split it by period or role and run each part.")
            break
        get = lambda name: rec[cols[name]].strip() if name in cols and cols[name] < len(rec) else ""  # noqa: E731
        bad = False
        rid = get("id")
        if not rid:
            err(line_no, "id", f"Row {line_no}: enter the applicant id.")
            bad = True
        elif rid in seen:
            err(line_no, "id", f'Row {line_no}: the id "{rid[:40]}" appears more than once. Each person is one row.')
            bad = True
        seen.add(rid)
        row = Row(id=rid, age_band=get("age_band") or None)
        if "selected" in cols:
            v = _norm(get("selected"))
            if v in TRUE or v in FALSE:
                row.selected = v in TRUE
            else:
                err(line_no, "selected", f"Row {line_no}: enter selected as yes or no.")
                bad = True
        if "score" in cols:
            try:
                row.score = float(get("score").replace(",", ""))
            except ValueError:
                err(line_no, "score", f"Row {line_no}: enter the score as a number.")
                bad = True
        raw_sex, raw_race = get("sex"), get("race")
        sx = _norm(raw_sex)
        if sx in SEX:
            row.sex = SEX[sx]
        elif sx in OUTSIDE_EEO1_SEX:
            outside[raw_sex] += 1
        elif sx not in UNKNOWN:
            err(line_no, "sex", f'Row {line_no}: "{raw_sex[:40]}" is not a sex category. Use Male, Female or leave it blank for unknown.')
            bad = True
        rc = _norm(raw_race)
        if rc in RACE:
            row.race = RACE[rc]
        elif rc not in UNKNOWN:
            err(line_no, "race", f'Row {line_no}: "{raw_race[:40]}" is not a race/ethnicity category. Use one of the seven EEO-1 categories or leave it blank for unknown.')
            bad = True
        if "ethnicity" in cols:  # EEO-1: Hispanic or Latino whatever the race; otherwise the race
            raw_eth = get("ethnicity")
            eth = re.sub(r"[^a-z0-9]", "", raw_eth.casefold())
            if eth in HISPANIC:
                row.race = "hispanic_latino"
            elif eth not in NOT_HISPANIC and eth not in UNKNOWN:
                err(line_no, "ethnicity", f'Row {line_no}: "{raw_eth[:40]}" is not an ethnicity. Use Hispanic or Latino, Not Hispanic or Latino, or leave it blank for unknown.')
                bad = True
        if "label" in cols:
            v = _norm(get("label"))
            if v in TRUE or v in FALSE:
                row.label = v in TRUE
            elif v:
                err(line_no, "qualified", f"Row {line_no}: enter qualified as yes, no or blank.")
                bad = True
        if bad:
            continue
        p.rows.append(row)
        p.report["unknown"]["sex"] += row.sex is None
        p.report["unknown"]["race"] += row.race is None
        p.report["unknown"]["either"] += row.sex is None or row.race is None
    p.report["rows_valid"] = len(p.rows)
    if "ethnicity" in cols:
        warnings.append(f'Race/ethnicity combines the "{header[cols["ethnicity"]].strip()}" and "{header[cols["race"]].strip()}" columns as EEO-1 does: anyone recorded as '
                        "Hispanic or Latino is counted as Hispanic or Latino whatever their race; everyone else is counted by race, and in the unknown category "
                        "when no race is recorded.")
    for value, n in sorted(outside.items()):
        warnings.append(f'"{value}" ({n} {"person" if n == 1 else "people"}) is not an EEO-1 component 1 sex category, so it is counted in the unknown category.')
    if p.report["rows_read"] == 0:
        err(None, "file", "The file has a header row but no data rows.")
    return p
