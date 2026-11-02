"""The bias calculator's thresholds ship in the risk methodology (spec §21 F11: 0.80 and 2% by default)."""
from sqlalchemy import select

from app.reference.catalogs import load_catalogs
from app.reference.models import RiskMethodology


def test_the_methodology_carries_the_bias_thresholds(db):
    load_catalogs(db)
    m = db.scalar(select(RiskMethodology))
    assert m.config["bias_calculator"] == {"impact_ratio_threshold": 0.80, "small_category_share": 0.02, "exclude_small_categories": True}
