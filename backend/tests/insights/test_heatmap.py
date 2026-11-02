"""Screen 35: the risk heat map (F13) placed from the existing scores, the findings grid and the report export."""
from app.insights import heatmap
from app.scoring import engine
from tests.factories import login_as

BANDS = [{"min": 75, "rating": "critical"}, {"min": 50, "rating": "high"}, {"min": 25, "rating": "medium"}, {"min": 0, "rating": "low"}]


def test_columns_are_the_inherent_bands_and_rows_the_maturity_levels():
    assert heatmap.columns(BANDS) == [{"label": "0–24.9", "min": 0, "max": 25}, {"label": "25–49.9", "min": 25, "max": 50}, {"label": "50–74.9", "min": 50, "max": 75}, {"label": "75–100", "min": 75, "max": 100}]
    assert [heatmap.column_of(x, BANDS) for x in (0, 24.9, 25, 74.9, 76, 100)] == [0, 0, 1, 2, 3, 3]
    assert [heatmap.row_of(m) for m in (1.0, 1.99, 2.0, 2.25, 3.0, 3.99, 4.0, 5.0)] == ["1", "1", "2", "2", "3", "3", "4–5", "4–5"]


def test_each_cell_is_coloured_by_the_residual_band_at_its_centre():
    m = engine.Methodology(version="1.0", factors={}, domains={}, domain_weights_by_build_type={}, build_type_weights={}, light_domains=[], proposed_score_bands=[], bands=BANDS,
                           knockout_rules=[], eu_ai_act={})
    grid = heatmap.cell_bands(m)
    assert grid == {"4–5": ["low", "low", "low", "medium"], "3": ["low", "low", "medium", "medium"], "2": ["low", "medium", "medium", "high"], "1": ["low", "medium", "high", "critical"]}


def test_the_worked_example_lands_in_the_top_inherent_column_at_maturity_2(client, db, ats, people):
    from app.scoring import service as scoring
    from tests.scoring.test_service import ATS_DOMAINS, _all_domains

    cid, e, maria, s = ats
    _all_domains(db, people, s, ATS_DOMAINS)
    db.commit()
    login_as(client, db, people["chief"])
    r = client.get(f"/api/v1/clients/{cid}/heatmap")
    assert r.status_code == 200, r.text
    out = r.json()
    sys1 = next(x for x in out["systems"] if x["reference_id"] == "SYS-001")
    assert (sys1["inherent"], sys1["maturity"], sys1["residual"], sys1["final_rating"]) == (76.0, 2.25, 58.2, "high")
    assert (sys1["column"], sys1["row"], sys1["provisional"]) == (3, "2", True)  # not locked until sign-off 5
    assert sys1["knockouts"] == ["No bias testing on a system affecting people (6.2.01)", "Null-compliance risk High (5.1a.05)"]
    cell = out["grid"]["2"][3]
    assert cell["band"] == "high" and [c["reference_id"] for c in cell["systems"]] == ["SYS-001"]
    assert out["unplaced"] == [x["reference_id"] for x in out["systems"] if x["column"] is None]
    assert scoring.latest(db, s).locked_at is None
    # findings view: severity × domain from the template section of each finding
    fg = out["findings_grid"]
    assert fg["domains"][3] == {"key": "bias", "label": "Bias, fairness and ethics"}
    assert sum(fg["rows"][1]["counts"]) >= 1  # the auto-drafted "No bias testing" finding (High) is in a domain column
    # filters
    assert client.get(f"/api/v1/clients/{cid}/heatmap?build_type=in_house").json()["systems"] == [x for x in out["systems"] if x["built_by"] == "in_house"]
    assert client.get(f"/api/v1/clients/{cid}/heatmap?framework=ISO_42001").json()["findings_grid"]["total"] == 0
    # exports
    svg = client.get(f"/api/v1/clients/{cid}/heatmap.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and b"SYS-001" in svg.content
    png = client.get(f"/api/v1/clients/{cid}/heatmap.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_only_futran_reviewers_on_the_engagement_see_it(client, db, ats, people):
    cid, e, maria, s = ats
    for u, ok in ((people["aud"], True), (people["aud2"], False), (maria, False)):
        login_as(client, db, u)
        r = client.get(f"/api/v1/clients/{cid}/heatmap")
        assert (r.status_code == 200) is ok, (u.email, r.status_code)
