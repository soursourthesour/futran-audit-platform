from datetime import date, datetime

import pytest

from tests.policies.conftest import world  # noqa: F401


@pytest.fixture
def signed(db, world):
    """ABC's engagement has a final, signed report (v1.1) and a published LL144 bias audit summary."""
    from app.reports.models import PublicSummary, Report

    e = world["engagement"]
    e.overall_rating = "medium"
    r = Report(organization_id=e.client_id, engagement_id=e.id, version="v1.1", status="final", body_md="# Report", content_hash="x" * 64,
               signed_by=world["chief"].id, signed_at=datetime(2026, 9, 30, 15, 0))
    db.add(r)
    ps = PublicSummary(organization_id=e.client_id, engagement_id=e.id, tool_name="ScreenRank résumé screening", audit_date=date(2026, 9, 1),
                       distribution_date=date(2025, 3, 1), data_source="Historical data from ABC Corp, 1 Jan – 30 Jun 2026", unknown_category_count=41,
                       impact_ratios=[{"category": "sex", "group": "Female", "selection_rate": 0.31, "impact_ratio": 0.94},
                                      {"category": "sex", "group": "Male", "selection_rate": 0.33, "impact_ratio": 1.0}])
    db.add(ps)
    db.commit()
    return {"report": r, "summary": ps}


@pytest.fixture
def unsigned_client(db, world):
    """Other Co has an engagement but no signed report."""
    from app.engagements.models import Engagement

    e = Engagement(organization_id=world["other"].id, client_id=world["other"].id, name="Other Co audit", audit_ref="FSL-AI-AUD-2026-002", status="in_progress", stage=5)
    db.add(e)
    db.commit()
    return e
