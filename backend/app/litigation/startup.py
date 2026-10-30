"""Add the court sites to the source allowlist on start-up when they are missing (run.bat only migrates), so the
litigation refresh reads official court sources on an upgraded laptop database. Idempotent; never stops the app."""
import logging

log = logging.getLogger(__name__)


def court_sources_on_start(app) -> int:
    from app.litigation.seed import seed_court_sources

    db = app.state.sessionmaker()
    try:
        n = seed_court_sources(db)
        db.commit()
        return n
    except Exception as exc:  # an unmigrated or locked database: start anyway
        db.rollback()
        log.warning("Court sources were not added on start-up: %s", exc)
        return 0
    finally:
        db.close()
