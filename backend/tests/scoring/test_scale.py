"""The single risk level scale: 5 Critical, 4 High, 3 Medium, 2 Low, 1 Observation."""
from pathlib import Path

import yaml

from app.scoring import scale

BANDS = yaml.safe_load((Path(__file__).parents[2] / "seeds" / "risk_methodology_v1.yaml").read_text())["bands"]


def test_levels_and_labels():
    assert [(r.key, r.level) for r in scale.RISK_LEVELS] == [("critical", 5), ("high", 4), ("medium", 3), ("low", 2), ("observation", 1)]
    assert scale.labelled("high") == "High (4)" and scale.labelled("observation") == "Observation (1)"
    assert scale.labelled(None) == "Not rated"
    assert scale.from_labelled("Critical (5)").key == "critical" and scale.from_labelled("High") is None


def test_residual_ranges_come_from_the_methodology_bands():
    assert scale.residual_ranges(BANDS) == {"critical": "75–100", "high": "50–74.9", "medium": "25–49.9", "low": "0–24.9"}
    rows = {r["key"]: r for r in scale.scale_rows(BANDS)}
    assert rows["observation"]["residual_range"] == "Not used for systems"
    assert rows["high"]["response_days"] == 90


def test_finding_due_dates_use_the_scale():
    from app.findings.service import DEFAULT_DUE_DAYS

    assert DEFAULT_DUE_DAYS == {"critical": 30, "high": 90, "medium": 182, "low": 365, "observation": 365}
    assert DEFAULT_DUE_DAYS is scale.RESPONSE_DAYS


def test_report_labels_come_from_the_scale():
    from app.reports import service

    assert service.SEVERITY_LABEL["high"] == "High (4)" and service.RATING_LABEL["critical"] == "Critical (5)"
    assert service.DUE_TEXT["high"] == "90 days"
