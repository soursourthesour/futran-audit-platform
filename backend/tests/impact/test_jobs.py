"""The daily run includes the weekly regulatory digest and the 12-month reassessment schedule."""
from app.notifications.jobs import JOBS


def test_daily_jobs_include_the_digest_and_the_reassessment_schedule():
    assert "regulatory_digest" in JOBS and "reassessment_schedule" in JOBS
