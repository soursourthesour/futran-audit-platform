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
        _tell_admins(app, exc)
        return None
    finally:
        db.close()


SEED_PROBLEM = "The governance role catalogue and law content did not load"


def _tell_admins(app, exc: Exception) -> None:
    """Show a failed seed to every Futran Admin in the app (once while it stays unread). Go-live in client registers
    is refused until the catalogue loads (register.gate.catalogue_missing)."""
    from app.notifications.models import Notification
    from app.notifications.service import notify
    from app.staffalerts.service import futran_users_with

    db = app.state.sessionmaker()
    try:
        admins = [u for u in futran_users_with(db, {"admin"})
                  if db.scalar(select(Notification.id).where(Notification.user_id == u.id, Notification.kind == "platform_problem", Notification.title == SEED_PROBLEM,
                                                             Notification.read_at.is_(None)).limit(1)) is None]
        notify(db, admins, "platform_problem", SEED_PROBLEM,
               f"The platform could not load the regulatory master on start-up ({str(exc)[:300]}). Until it loads, clients cannot take AI systems live. "
               "Run seed-reference on the server, or restart the platform after fixing the cause.", "/reg/roles")
        db.commit()
    except Exception:  # the database itself is the problem: the log line above is all we can do
        db.rollback()
    finally:
        db.close()


def repair_replaced_links(db) -> int:
    """Move register links, client applicability rows and sources still on a replaced law row to the live row.

    Rows have been moved when a law row is replaced since the fix; this repairs data written before it. Idempotent:
    a second call finds nothing to move. Returns the number of rows moved or merged."""
    from app.laws.models import Regulation
    from app.laws.publish import carry_forward, current_version_of
    from app.regmaster.models import ClientLawApplicability, Source

    dead = set(db.scalars(select(Regulation.id).where(Regulation.superseded_by_id.is_not(None))))
    if not dead:
        return 0
    olds: set[str] = set(db.scalars(select(ClientLawApplicability.regulation_id).where(ClientLawApplicability.regulation_id.in_(dead))))
    olds |= set(db.scalars(select(Source.regulation_id).where(Source.regulation_id.in_(dead))))
    try:
        from app.register.models import RegisterSystemLaw

        olds |= set(db.scalars(select(RegisterSystemLaw.regulation_id).where(RegisterSystemLaw.regulation_id.in_(dead))))
    except ImportError:
        pass
    moved = 0
    for old_id in sorted(olds):
        live = current_version_of(db, old_id)
        if live is not None and live.id != old_id:
            moved += carry_forward(db, old_id, live.id)
    return moved


def repair_on_start(app) -> int:
    """Run `repair_replaced_links` once at start-up; a failure is logged and never stops the app."""
    db = app.state.sessionmaker()
    try:
        n = repair_replaced_links(db)
        db.commit()
        if n:
            log.info("Moved %s rows from replaced law records to the live records", n)
        return n
    except Exception as exc:  # an unmigrated or locked database
        db.rollback()
        log.warning("Links on replaced law records were not repaired on start-up: %s", exc)
        return 0
    finally:
        db.close()
