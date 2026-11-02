"""Reading an applicant data CSV for the bias calculator: column names, values and the validation report."""
from app.biascalc import dataset


def csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def test_reads_selection_data_with_common_column_names_and_values():
    p = dataset.parse(csv("Applicant ID,Selected,Gender,Race/Ethnicity,Age band",
                          "a1,Yes,M,White,25-34", "a2,no,Female,Hispanic or Latino,35-44", "a3,1,female,Black or African American (Not Hispanic or Latino),",
                          "a4,0,,Two or More Races,", "a5,TRUE,Male,Declined to state,"))
    assert p.ok and p.report["errors"] == []
    assert p.report["rows_read"] == 5 and p.report["rows_valid"] == 5
    assert p.report["columns"] == {"id": "Applicant ID", "selected": "Selected", "sex": "Gender", "race": "Race/Ethnicity", "age_band": "Age band"}
    assert p.methods == ["selection_rate"]
    r = {x.id: x for x in p.rows}
    assert (r["a1"].selected, r["a1"].sex, r["a1"].race, r["a1"].age_band) == (True, "male", "white", "25-34")
    assert (r["a3"].sex, r["a3"].race) == ("female", "black")
    assert r["a4"].sex is None and r["a5"].race is None
    assert p.report["unknown"] == {"sex": 1, "race": 1, "either": 2}


def test_reads_scores_and_outcome_labels():
    p = dataset.parse(csv("id,score,sex,race_ethnicity,qualified", "1,71.5,male,asian,yes", "2,64,female,white,no"))
    assert p.ok and p.methods == ["scoring_rate"] and p.report["has_labels"]
    assert p.rows[0].score == 71.5 and p.rows[0].label is True and p.rows[1].label is False
    p = dataset.parse(csv("id,score,selected,sex,race", "1,71.5,yes,male,asian", "2,,no,female,white"))
    assert not p.ok and p.report["errors"] == [{"row": 3, "field": "score", "message": "Row 3: enter the score as a number."}]


def test_unrecognised_values_duplicate_ids_and_bad_numbers_are_errors_with_row_numbers():
    p = dataset.parse(csv("id,selected,sex,race", "1,yes,male,white", "1,no,female,white", "2,maybe,female,white", "3,yes,femal,white", "4,yes,male,martian", ",yes,male,white"))
    assert not p.ok
    msgs = {(e["row"], e["field"]) for e in p.report["errors"]}
    assert msgs == {(3, "id"), (4, "selected"), (5, "sex"), (6, "race"), (7, "id")}
    assert next(e for e in p.report["errors"] if e["field"] == "sex")["message"] == 'Row 5: "femal" is not a sex category. Use Male, Female or leave it blank for unknown.'


def test_missing_required_columns_are_reported():
    p = dataset.parse(csv("id,sex,race", "1,male,white"))
    assert not p.ok and p.report["errors"][0]["message"] == "Add a column named selected (yes or no) or score (a number)."
    p = dataset.parse(csv("selected,sex", "yes,male"))
    assert {e["field"] for e in p.report["errors"]} == {"id", "race"}


def test_empty_file_and_non_utf8_text():
    assert not dataset.parse(b"").ok
    p = dataset.parse("id,selected,sex,race\n1,yes,male,white\n2,no,female,Hispanic or Latino\n".encode("cp1252"))
    assert p.ok
    p = dataset.parse("﻿id,selected,sex,race\n1,yes,male,white\n".encode())  # Excel's byte order mark
    assert p.ok and p.rows[0].id == "1"


def test_non_binary_and_declined_answers_are_unknown_category_with_a_warning():
    p = dataset.parse(csv("id,selected,sex,race", "1,yes,Non-binary,white", "2,no,male,white"))
    assert p.ok and p.rows[0].sex is None
    assert any("not an EEO-1 component 1 sex category" in w for w in p.report["warnings"])


def test_separate_ethnicity_and_race_columns_are_combined_as_eeo1_does():
    """The usual two-column format: Hispanic or Latino counts as Hispanic or Latino whatever the race; otherwise the race;
    Not Hispanic or Latino with no race recorded is unknown."""
    p = dataset.parse(csv("id,selected,sex,ethnicity,race",
                          "1,yes,male,Hispanic or Latino,White", "2,no,female,Not Hispanic or Latino,White", "3,yes,female,Not Hispanic or Latino,Black or African American",
                          "4,no,male,Hispanic or Latino,", "5,no,male,Not Hispanic or Latino,", "6,yes,female,,Asian"))
    assert p.ok, p.report["errors"]
    r = {x.id: x.race for x in p.rows}
    assert r == {"1": "hispanic_latino", "2": "white", "3": "black", "4": "hispanic_latino", "5": None, "6": "asian"}
    assert p.report["columns"]["race"] == "race" and p.report["columns"]["ethnicity"] == "ethnicity"
    assert any("ethnicity" in w and "Hispanic or Latino" in w for w in p.report["warnings"])
    assert p.report["unknown"]["race"] == 1


def test_an_unrecognised_ethnicity_is_an_error_and_a_single_ethnicity_column_still_reads_as_race():
    p = dataset.parse(csv("id,selected,sex,ethnicity,race", "1,yes,male,Martian,White"))
    assert not p.ok and p.report["errors"][0]["row"] == 2 and p.report["errors"][0]["field"] == "ethnicity"
    p = dataset.parse(csv("id,selected,sex,ethnicity", "1,yes,male,White", "2,no,female,Hispanic or Latino"))
    assert p.ok and [x.race for x in p.rows] == ["white", "hispanic_latino"]


def test_non_finite_scores_are_errors_with_row_numbers():
    p = dataset.parse(csv("id,score,sex,race", "1,71.5,male,white", "2,nan,female,white", "3,inf,male,asian", "4,-Infinity,female,asian"))
    assert not p.ok
    assert [(e["row"], e["field"]) for e in p.report["errors"]] == [(3, "score"), (4, "score"), (5, "score")]
    assert p.report["errors"][0]["message"] == "Row 3: enter the score as a number."


def test_a_field_over_the_csv_limit_is_a_validation_error_not_a_crash():
    import csv as _csv

    big = "x" * (_csv.field_size_limit() + 10)
    p = dataset.parse(csv("id,selected,sex,race", "1,yes,male,white", f'2,no,female,"{big}"', "3,yes,male,white"))
    assert not p.ok
    e = p.report["errors"][0]
    assert e["field"] == "file" and e["row"] == 3 and "could not be read" in e["message"]
