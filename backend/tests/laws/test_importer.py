from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from app.laws.importer import parse_workbook

WORKBOOK = Path(__file__).resolve().parents[2] / "seeds" / "law_matrix.xlsx"


@pytest.fixture(scope="module")
def preview():
    return parse_workbook(WORKBOOK)


def regs(preview):
    return [r for r in preview.rows if r.kind == "regulation"]


def test_status_date(preview):
    assert preview.status_date == date(2026, 10, 5)


def test_federal_count(preview):
    fed = [r for r in regs(preview) if r.source_sheet == "Federal Laws"]
    assert len(fed) == 26
    assert {r.jurisdiction_code for r in fed} == {"US"}
    title_vii = next(r for r in fed if r.short_name.startswith("Title VII"))
    assert title_vii.feature == "employment_hiring"
    assert title_vii.type == "statute"
    assert title_vii.enforcer == "EEOC; private lawsuits"


def test_state_matrix_states(preview):
    state = [r for r in regs(preview) if r.source_sheet == "State Matrix"]
    codes = {r.jurisdiction_code for r in state} - {"US-NYC"}
    assert len(codes) == 26
    assert {"US-NY", "US-CA", "US-CO", "US-IL", "US-TX"} <= codes


def test_state_cells_split_into_laws_with_short_names(preview):
    ca_hiring = [r for r in regs(preview) if r.jurisdiction_code == "US-CA" and r.feature == "employment_hiring"]
    names = [r.short_name for r in ca_hiring]
    assert any(n.startswith("FEHA automated-decision system regulations") for n in names)
    assert any(n.startswith("SB 947") for n in names)
    assert all(len(n) <= 120 for n in names)


def test_continuation_lines_fold_into_previous_law(preview):
    co = [r for r in regs(preview) if r.jurisdiction_code == "US-CO" and r.feature == "consequential_decisions_admt"]
    assert len(co) == 1
    assert "Deployers:" in co[0].full_text and "Developers:" in co[0].full_text


def test_key_dates_and_vetoes_become_notes(preview):
    notes = [r for r in preview.rows if r.kind == "note" and r.jurisdiction_code == "US-CA"]
    assert any(n.full_text.startswith("Key dates") for n in notes)
    assert any(n.full_text.startswith("Vetoed 2026") for n in notes)
    assert not any(r.short_name.startswith("Vetoed") for r in regs(preview))


def test_ll144_routed_to_nyc(preview):
    nyc = [r for r in regs(preview) if r.jurisdiction_code == "US-NYC"]
    assert any("Local Law 144" in r.full_text for r in nyc)
    assert all(r.feature for r in nyc)


def test_global_notes_12_jurisdictions(preview):
    assert set(preview.jurisdiction_notes) >= {"EU", "GB", "CA", "MX", "BR", "IN", "AE", "SA", "QA", "BH", "AU", "SG"}
    assert "employment_hiring" in preview.jurisdiction_notes["EU"]


def test_country_sheet_counts(preview):
    by_sheet = Counter(r.source_sheet for r in regs(preview))
    assert {k: by_sheet[k] for k in ["EU", "UK", "Canada", "Mexico", "Brazil", "India", "Gulf", "Australia", "Singapore"]} == {
        "EU": 9, "UK": 8, "Canada": 8, "Mexico": 6, "Brazil": 7, "India": 8, "Gulf": 12, "Australia": 9, "Singapore": 8,
    }
    assert {r.jurisdiction_code for r in regs(preview) if r.source_sheet == "UK"} == {"GB"}


def test_gulf_rows_split_by_country(preview):
    gulf = [r for r in regs(preview) if r.source_sheet == "Gulf"]
    assert {r.jurisdiction_code for r in gulf} == {"AE", "SA", "QA", "BH", "OM"}
    difc = next(r for r in gulf if "DIFC" in r.short_name)
    assert difc.jurisdiction_code == "AE" and difc.feature == "privacy_profiling"


def test_frontier_marked_developer(preview):
    sb53 = next(r for r in regs(preview) if r.jurisdiction_code == "US-CA" and r.short_name.startswith("SB 53"))
    assert sb53.applies_to == "developer"
    assert next(r for r in regs(preview) if r.short_name.startswith("Title VII")).applies_to == "deployer"


def test_verify_flag_detected(preview):
    flagged = [r for r in regs(preview) if r.verify_flag]
    assert flagged
    assert all("(verify)" in " ".join(filter(None, [r.full_text, r.trigger_text, r.obligations_text, r.developments_text, r.most_affected])) for r in flagged)


def test_sources_34(preview):
    assert len(preview.sources) == 34
    assert preview.sources[0]["url"].startswith("https://")


def test_every_regulation_has_valid_feature_and_type(preview):
    from app.laws.importer import FEATURES, TYPES

    for r in regs(preview):
        assert r.feature in FEATURES, r
        assert r.type in TYPES, r
        assert r.short_name and r.row_key
    assert len({r.row_key for r in preview.rows}) == len(preview.rows)
