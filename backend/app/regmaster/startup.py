"""Seed the regulatory master on start-up when its role catalogue is empty.

run.bat only runs `alembic upgrade head`, so a database upgraded on a laptop would otherwise have no role catalogue
and no cited requirements until `python -m app.cli seed-reference` runs. Seeding is idempotent and never overwrites
content already on a law version; a failure is logged and never stops the app."""
import logging

from sqlalchemy import select

log = logging.getLogger(__name__)


def seed_if_empty(app) -> str | None:
    from app.regmaster.models import RoleCatalog
    from app.regmaster.seed import seed_regmaster

    db = app.state.sessionmaker()
    try:
        if db.scalar(select(RoleCatalog.id).limit(1)) is not None:
            return None
        result = seed_regmaster(db)
        db.commit()
        log.info("Regulatory master seeded on start-up: %s", result)
        return result
    except Exception as exc:  # an unmigrated or locked database: start anyway, seed-reference can be run later
        db.rollback()
        log.warning("Regulatory master was not seeded on start-up: %s", exc)
        return None
    finally:
        db.close()
