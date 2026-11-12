"""Load the starter price list on start-up when the catalog is empty (run.bat only runs `alembic upgrade head`).
Idempotent; a failure is logged and never stops the app."""
import logging

log = logging.getLogger(__name__)


def seed_if_empty(app) -> str | None:
    from app.catalog.seed import seed_starter

    db = app.state.sessionmaker()
    try:
        result = seed_starter(db)
        db.commit()
        if result != "already loaded":
            log.info("Master price list starter items loaded on start-up: %s", result)
        return result
    except Exception as exc:  # an unmigrated or locked database: start anyway; seed-reference can be run later
        db.rollback()
        log.warning("Master price list starter items were not loaded on start-up: %s", exc)
        return None
    finally:
        db.close()
