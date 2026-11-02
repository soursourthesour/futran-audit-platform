"""The bias calculator's statistics, checked against the worked examples DCWP published with the final rule
(6 RCNY § 5-301(b) and (d), Notice of Adoption, 6 April 2023) and against small cases computed by hand.

Each rule table is computed independently from its own counts, as the rule does: the example's tables are not
consistent with one another (for example, 408 Hispanic or Latino applicants in the race table but 205 + 190 in the
intersectional table), so a row-level reconstruction is only possible for the scoring example, whose tables agree.
"""
import pytest

from app.biascalc import stats
from app.biascalc.stats import Row

R = round

# ---- 6 RCNY § 5-301(b), example: résumé screening, selection rates -----------------------------------------------
SEX_COUNTS = {"male": (1390, 667), "female": (1181, 555)}
RACE_COUNTS = {"hispanic_latino": (408, 204), "white": (797, 412), "black": (390, 170), "nhpi": (119, 52), "asian": (616, 302), "aian": (41, 18), "two_or_more": (213, 96)}
RACE_RATIOS_PUBLISHED = {"hispanic_latino": 0.97, "white": 1.00, "black": 0.84, "nhpi": 0.85, "asian": 0.95, "aian": 0.85, "two_or_more": 0.87}
INTER_COUNTS = {
    ("male", "hispanic_latino"): (205, 90), ("female", "hispanic_latino"): (190, 82),
    ("male", "white"): (412, 215), ("male", "black"): (226, 95), ("male", "nhpi"): (87, 37), ("male", "asian"): (321, 167), ("male", "aian"): (24, 11), ("male", "two_or_more"): (115, 52),
    ("female", "white"): (385, 197), ("female", "black"): (164, 75), ("female", "nhpi"): (32, 15), ("female", "asian"): (295, 135), ("female", "aian"): (17, 7), ("female", "two_or_more"): (98, 44),
}
INTER_RATIOS_PUBLISHED = {
    ("male", "hispanic_latino"): 0.841, ("female", "hispanic_latino"): 0.827,
    ("male", "white"): 1.000, ("male", "black"): 0.806, ("male", "nhpi"): 0.815, ("male", "asian"): 0.997, ("male", "aian"): 0.878, ("male", "two_or_more"): 0.866,
    ("female", "white"): 0.981, ("female", "black"): 0.876, ("female", "nhpi"): 0.898, ("female", "asian"): 0.877, ("female", "aian"): 0.789, ("female", "two_or_more"): 0.860,
}


def by_cat(table):
    return {c.key: c for c in table.categories}


def test_rule_example_sex_selection_rates_and_impact_ratios():
    t = stats.table_from_counts("sex", SEX_COUNTS, exclude_small=False)
    c = by_cat(t)
    assert R(c["male"].rate, 2) == 0.48 and R(c["female"].rate, 2) == 0.47
    assert c["male"].impact_ratio == 1.0
    assert R(c["female"].impact_ratio, 3) == 0.979
    assert t.reference == "male"


def test_rule_example_race_impact_ratios_match_the_published_table():
    c = by_cat(stats.table_from_counts("race", RACE_COUNTS, exclude_small=False))
    assert {k: R(v.impact_ratio, 2) for k, v in c.items()} == RACE_RATIOS_PUBLISHED
    assert R(c["white"].rate, 2) == 0.52 and R(c["black"].rate, 2) == 0.44


def test_rule_example_intersectional_impact_ratios_match_the_published_table():
    c = by_cat(stats.table_from_counts("intersectional", {stats.inter_key(s, r): n for (s, r), n in INTER_COUNTS.items()}, exclude_small=False))
    assert {k: R(v.impact_ratio, 3) for k, v in c.items()} == {stats.inter_key(s, r): v for (s, r), v in INTER_RATIOS_PUBLISHED.items()}
    assert c[stats.inter_key("male", "hispanic_latino")].label == "Hispanic or Latino male"
    assert c[stats.inter_key("female", "black")].label == "Black or African American female (not Hispanic or Latino)"


def test_categories_under_two_percent_are_excluded_from_impact_ratios_but_still_reported():
    """§ 5-301(d): Native American or Alaska Native is 41 of 2,584 (1.6%). The number of applicants and the rate stay."""
    t = stats.table_from_counts("race", RACE_COUNTS, exclude_small=True, small_share=0.02)
    c = by_cat(t)
    assert c["aian"].excluded and c["aian"].impact_ratio is None
    assert c["aian"].applicants == 41 and R(c["aian"].rate, 4) == R(18 / 41, 4)
    assert not c["nhpi"].excluded  # 119 of 2,584 is 4.6%
    assert t.excluded == ["aian"]
    assert R(c["black"].impact_ratio, 2) == 0.84  # the reference is unchanged


def test_an_excluded_category_is_never_the_reference_group():
    """A tiny category with the highest rate would otherwise set every other ratio (mockup: NHPI 25.8%, White 25.0% = 1.00)."""
    t = stats.table_from_counts("race", {"white": (812, 203), "asian": (402, 92), "nhpi": (31, 8)}, exclude_small=True, small_share=0.05)
    c = by_cat(t)
    assert t.reference == "white" and c["white"].impact_ratio == 1.0
    assert c["nhpi"].excluded and c["nhpi"].impact_ratio is None
    assert R(c["asian"].impact_ratio, 2) == 0.92


def test_four_fifths_flag_is_below_the_threshold_only():
    t = stats.table_from_counts("sex", {"male": (100, 50), "female": (100, 40)}, exclude_small=False, threshold=0.80)
    c = by_cat(t)
    assert c["female"].impact_ratio == 0.8 and not c["female"].below_threshold  # exactly 0.80 meets the guide
    t = stats.table_from_counts("sex", {"male": (100, 50), "female": (100, 39)}, exclude_small=False, threshold=0.80)
    assert by_cat(t)["female"].below_threshold and t.lowest == ("female", pytest.approx(0.78))


def test_no_one_selected_gives_no_impact_ratio():
    t = stats.table_from_counts("sex", {"male": (10, 0), "female": (12, 0)}, exclude_small=False)
    assert all(c.impact_ratio is None for c in t.categories) and t.reference is None
    assert t.note == "No category has a positive rate, so impact ratios cannot be calculated."


def test_statistical_parity_difference_is_rate_minus_the_reference_rate():
    c = by_cat(stats.table_from_counts("sex", {"male": (200, 90), "female": (100, 30)}, exclude_small=False))
    assert R(c["female"].parity_difference, 4) == R(0.30 - 0.45, 4)
    assert c["male"].parity_difference == 0.0


# ---- 6 RCNY § 5-301(d), example: "culture fit" scores, scoring rates ----------------------------------------------
# (sex, race): (applicants, scoring above the median). The tables are consistent: 168 people, 84 above the median.
SCORING_CELLS = {
    ("male", "hispanic_latino"): (16, 12), ("female", "hispanic_latino"): (12, 6),
    ("male", "white"): (20, 7), ("male", "black"): (20, 10), ("male", "nhpi"): (4, 3), ("male", "asian"): (12, 7), ("male", "aian"): (8, 5), ("male", "two_or_more"): (12, 6),
    ("female", "white"): (20, 8), ("female", "black"): (12, 6), ("female", "nhpi"): (4, 2), ("female", "asian"): (12, 3), ("female", "aian"): (8, 5), ("female", "two_or_more"): (8, 4),
}


def scoring_rows() -> list[Row]:
    rows, n = [], 0
    for (sex, race), (total, above) in SCORING_CELLS.items():
        for i in range(total):
            n += 1
            rows.append(Row(id=f"A{n}", score=90.0 if i < above else 10.0, sex=sex, race=race))
    for i in range(15):  # "15 individuals with an unknown sex or race/ethnicity category"
        n += 1
        rows.append(Row(id=f"A{n}", score=90.0 if i < 7 else 10.0, sex=None, race=None))  # every table totals 168, so neither is known
    return rows


def test_rule_example_scoring_rates_reproduce_the_published_tables():
    res = stats.compute(scoring_rows(), method="scoring_rate", exclude_small=False)
    assert res.median == 10.0  # 92 scores of 10 and 91 of 90: the median of the full sample, including unknowns
    sex = by_cat(res.tables["sex"])
    assert (sex["male"].applicants, R(sex["male"].rate, 3)) == (92, 0.543)
    assert (sex["female"].applicants, R(sex["female"].rate, 3)) == (76, 0.447)
    assert R(sex["female"].impact_ratio, 2) == 0.82
    race = by_cat(res.tables["race"])
    assert {k: R(v.impact_ratio, 2) for k, v in race.items()} == {"hispanic_latino": 1.00, "white": 0.58, "black": 0.78, "nhpi": 0.97, "asian": 0.65, "aian": 0.97, "two_or_more": 0.78}
    inter = by_cat(res.tables["intersectional"])
    published = {("male", "hispanic_latino"): 1.00, ("female", "hispanic_latino"): 0.67, ("male", "white"): 0.47, ("male", "black"): 0.67, ("male", "nhpi"): 1.00, ("male", "asian"): 0.78,
                 ("male", "aian"): 0.83, ("male", "two_or_more"): 0.67, ("female", "white"): 0.53, ("female", "black"): 0.67, ("female", "nhpi"): 0.67, ("female", "asian"): 0.33,
                 ("female", "aian"): 0.83, ("female", "two_or_more"): 0.67}
    assert {k: R(v.impact_ratio, 2) for k, v in inter.items()} == {stats.inter_key(s, r): v for (s, r), v in published.items()}
    assert res.unknown_count == 15


def test_scoring_rate_counts_only_scores_strictly_above_the_median():
    rows = [Row(id=str(i), score=s, sex="male" if i < 4 else "female", race="white") for i, s in enumerate([1, 2, 3, 4, 2, 3, 3, 5])]
    res = stats.compute(rows, method="scoring_rate", exclude_small=False)
    assert res.median == 3.0  # sorted 1 2 2 3 3 3 4 5: mean of the 4th and 5th values
    sex = by_cat(res.tables["sex"])
    assert (sex["male"].selected, sex["female"].selected) == (1, 1)  # 4 and 5; the threes are not above


# ---- unknown categories ---------------------------------------------------------------------------------------------
def test_unknowns_are_left_out_of_each_table_where_they_are_unknown_and_counted():
    rows = [Row(id="1", selected=True, sex="male", race="white"), Row(id="2", selected=False, sex=None, race="white"),
            Row(id="3", selected=True, sex="female", race=None), Row(id="4", selected=False, sex=None, race=None), Row(id="5", selected=False, sex="female", race="asian")]
    res = stats.compute(rows, method="selection_rate", exclude_small=False)
    assert res.tables["sex"].unknown == 2 and sum(c.applicants for c in res.tables["sex"].categories) == 3
    assert res.tables["race"].unknown == 2 and sum(c.applicants for c in res.tables["race"].categories) == 3
    assert res.tables["intersectional"].unknown == 3 and sum(c.applicants for c in res.tables["intersectional"].categories) == 2
    assert res.unknown_count == 3  # unknown sex or race/ethnicity, as the rule's notes count them
    assert res.total == 5 and res.selected_total == 2


def test_small_share_is_measured_against_the_people_in_that_table():
    rows = [Row(id=str(i), selected=i % 2 == 0, sex="male", race="white") for i in range(98)] + [Row(id="x", selected=True, sex="female", race="white"), Row(id="y", selected=False, sex="female", race=None)]
    res = stats.compute(rows, method="selection_rate", exclude_small=True, small_share=0.02)
    assert not by_cat(res.tables["sex"])["female"].excluded  # 2 of 100 is not below 2%
    assert by_cat(res.tables["race"])["white"].applicants == 99  # y has an unknown race, so it is not in this table
    res = stats.compute(rows[:-1], method="selection_rate", exclude_small=True, small_share=0.02)
    assert by_cat(res.tables["sex"])["female"].excluded  # 1 of 99


# ---- equal opportunity --------------------------------------------------------------------------------------------
def test_equal_opportunity_difference_uses_people_with_a_positive_outcome_label():
    rows = []
    # men: 10 qualified, 8 selected among them; women: 10 qualified, 5 selected among them; plus unqualified people
    for i in range(10):
        rows.append(Row(id=f"m{i}", selected=i < 8, sex="male", race="white", label=True))
        rows.append(Row(id=f"f{i}", selected=i < 5, sex="female", race="white", label=True))
    for i in range(10):
        rows.append(Row(id=f"mu{i}", selected=i < 2, sex="male", race="white", label=False))
        rows.append(Row(id=f"fu{i}", selected=False, sex="female", race="white", label=False))
    res = stats.compute(rows, method="selection_rate", exclude_small=False)
    sex = by_cat(res.tables["sex"])
    assert res.has_labels
    assert R(sex["female"].true_positive_rate, 2) == 0.5 and R(sex["male"].true_positive_rate, 2) == 0.8
    assert R(sex["female"].equal_opportunity_difference, 2) == -0.3
    res = stats.compute([Row(id="1", selected=True, sex="male", race="white")], method="selection_rate", exclude_small=False)
    assert not res.has_labels and by_cat(res.tables["sex"])["male"].equal_opportunity_difference is None
