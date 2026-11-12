"""Load the service template starter content (Release 2 B6) on start-up when it is missing (run.bat only runs
`alembic upgrade head`). Idempotent: existing templates and versions are never touched. A failure is logged and never
stops the app."""
import logging

log = logging.getLogger(__name__)


def seed_if_empty(app) -> str | None:
    from app.servicetemplates.service import seed

    db = app.state.sessionmaker()
    try:
        result = seed(db)
        db.commit()
        if result != "already loaded":
            log.info("Service templates loaded on start-up: %s", result)
        return result
    except Exception as exc:  # an unmigrated or locked database: start anyway
        db.rollback()
        log.warning("Service templates were not loaded on start-up: %s", exc)
        return None
    finally:
        db.close()
