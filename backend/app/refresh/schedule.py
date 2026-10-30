"""Scheduled refreshes (spec §25.3 step 1: default every 2 weeks) and the other WS-D daily jobs, run by the daily
scheduler in app.notifications.jobs."""
import logging
import threading
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.refresh.claude import client_for
from app.refresh.models import RefreshRun
from app.refresh.pipeline import execute_run, get_run_setting, start_run

log = logging.getLogger(__name__)
CLIENT_FACTORY = None  # tests set a factory; otherwise client_for decides (fake in demo, Anthropic with a key)


def _client(settings: Settings):
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY(settings)
    return client_for(None, settings)


def _execute_in_thread(bind, settings: Settings, run_id: str) -> None:
    def work():
        import time

        db = sessionmaker(bind=bind, expire_on_commit=False)()
        try:
            run = None
            for _ in range(240):  # the daily jobs commit the run row when they all finish
                run = db.get(RefreshRun, run_id)
                if run is not None:
                    break
                db.rollback()
                time.sleep(0.5)
            if run is None:
                log.error("Scheduled refresh %s was never saved", run_id)
                return
            execute_run(db, settings, run, _client(settings), commit=db.commit)
            db.commit()
        except Exception:
            log.exception("Scheduled refresh %s failed", run_id)
            db.rollback()
        finally:
            db.close()

    threading.Thread(target=work, name=f"refresh-{run_id[:8]}", daemon=True).start()


def run_scheduled(db: Session, settings: Settings, now, background: bool = True) -> int:
    """Start every refresh that is due. With background=True the research runs in its own thread and session, so the
    daily jobs' transaction is not held open while Claude searches."""
    if _client(settings) is None:
        return 0
    started = 0
    for kind in ("law", "litigation"):
        s = get_run_setting(db, kind)
        if not s.schedule_enabled:
            continue
        if s.last_scheduled_at is not None and now - s.last_scheduled_at < timedelta(days=s.every_days):
            continue
        run = start_run(db, kind=kind, actor=None, settings=settings, scope_mode=s.scope_mode,
                        jurisdiction_codes=None, checks=s.checks, source_set=s.source_set, cost_cap_usd=s.cost_cap_usd, trigger="scheduled")
        if s.scope_mode == "chosen":
            run.jurisdiction_ids = list(s.jurisdiction_ids or [])
        s.last_scheduled_at = now
        db.flush()
        if background:
            _execute_in_thread(db.get_bind(), settings, run.id)
        else:
            execute_run(db, settings, run, _client(settings))
        started += 1
    return started


def run_reminders(db: Session, settings: Settings, now) -> int:
    from app.staffalerts.service import run_reminders as remind

    return remind(db, settings, now)


def client_alert_dates(db: Session, settings: Settings, now) -> int:
    from app.clientalerts.service import queue_effective_dates

    return len(queue_effective_dates(db, settings, now.date()))


def opportunity_dates(db: Session, settings: Settings, now) -> int:
    from app.sales.service import open_effective_date_opportunities

    return len(open_effective_date_opportunities(db, now.date()))
