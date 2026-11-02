"""§ 5-303(a)(1): the published summary gives "the number of applicants or candidates, the selection or scoring rates, as
applicable, and the impact ratios for all categories". Rows written by the bias calculator carry the applicant count and
the rate kind; rows typed by hand keep working without them."""
from app.reports.models import PublicSummary
from app.reports.public_summary import _ratios, summary_text


def test_rows_keep_the_applicant_count_and_the_rate_kind():
    errs: list = []
    rows = _ratios([{"category": "Race/ethnicity", "group": "White", "applicants": 228, "selection_rate": 0.45, "impact_ratio": 1.0, "rate_kind": "selection"},
                    {"category": "Sex", "group": "Female", "selection_rate": 0.41, "impact_ratio": 0.91}], errs)
    assert errs == []
    assert rows[0] == {"category": "Race/ethnicity", "group": "White", "applicants": 228, "selection_rate": 0.45, "impact_ratio": 1.0, "rate_kind": "selection"}
    assert rows[1] == {"category": "Sex", "group": "Female", "selection_rate": 0.41, "impact_ratio": 0.91}


def test_a_bad_applicant_count_is_an_error():
    errs: list = []
    _ratios([{"category": "Sex", "group": "Male", "applicants": "many", "impact_ratio": 1}], errs)
    assert errs == [{"field": "impact_ratios.0", "message": "Row 1: enter the number of applicants as a whole number."}]


def test_summary_text_names_applicants_and_the_scoring_rate():
    s = PublicSummary(tool_name="Fit score", data_source="Historical data", unknown_category_count=15,
                      impact_ratios=[{"category": "Sex", "group": "Female", "applicants": 76, "selection_rate": 0.447, "impact_ratio": 0.82, "rate_kind": "scoring"}])
    assert "- Sex · Female: 76 applicants, scoring rate 0.45, impact ratio 0.82" in summary_text(s)


def test_an_excluded_category_is_listed_with_its_count_rate_and_the_justification():
    """§ 5-301(d): the summary must include the justification and the number of applicants and rate of an excluded category."""
    errs: list = []
    rows = _ratios([{"category": "Race/ethnicity", "group": "Native American or Alaska Native", "applicants": 9, "selection_rate": 0.4444, "impact_ratio": None, "excluded": True,
                     "justification": "Under 2% of the data; a ratio on nine people is not meaningful.", "rate_kind": "selection"}], errs)
    assert errs == [] and rows[0]["excluded"] is True and rows[0]["impact_ratio"] is None
    s = PublicSummary(tool_name="ScreenRank", data_source="Historical data", impact_ratios=rows)
    assert ("- Race/ethnicity · Native American or Alaska Native: 9 applicants, selection rate 0.44, excluded from the impact ratio calculation. "
            "Justification: Under 2% of the data; a ratio on nine people is not meaningful.") in summary_text(s)
    errs = []
    _ratios([{"category": "Sex", "group": "Male", "impact_ratio": None, "excluded": True}], errs)
    assert errs == [{"field": "impact_ratios.0", "message": "Row 1: give the number of applicants, the rate and the justification for an excluded category."}]


def test_a_not_calculable_row_keeps_its_applicants_rate_and_reason():
    """§ 5-304: applicants and rates are published even when the table has no positive rate (no impact ratio)."""
    errs: list = []
    rows = _ratios([{"category": "Sex", "group": "Male", "applicants": 50, "selection_rate": 0, "impact_ratio": "", "not_calculable": True,
                     "reason": "No category has a positive rate, so impact ratios cannot be calculated.", "rate_kind": "selection"}], errs)
    assert errs == [] and rows[0]["impact_ratio"] is None and rows[0]["not_calculable"] is True and rows[0]["applicants"] == 50
    assert "- Sex · Male: 50 applicants, selection rate 0.00, impact ratio not calculable. No category has a positive rate" in summary_text(PublicSummary(tool_name="T", impact_ratios=rows))
    errs = []
    _ratios([{"category": "Sex", "group": "Male", "impact_ratio": None, "not_calculable": True}], errs)
    assert errs == [{"field": "impact_ratios.0", "message": "Row 1: give the number of applicants, the rate and why the impact ratio cannot be calculated."}]
