"""Wires the bias calculator into the daily jobs: raw applicant data is deleted at the end of the retention period."""
from app.notifications import jobs


def _retention(db, settings, now) -> int:
    from app.biascalc.retention import purge_expired_raw_data

    return purge_expired_raw_data(db, settings, now)


jobs.JOBS.setdefault("bias_raw_data_retention", _retention)
